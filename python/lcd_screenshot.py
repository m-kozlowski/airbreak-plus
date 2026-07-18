#!/usr/bin/env python3

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


TCL_RPC_SEPARATOR = b"\x1a"


class OpenOcdError(RuntimeError):
    pass


class OpenOcdTclRpc:
    def __init__(self, host, port, timeout):
        self.sock = socket.create_connection((host, port), timeout)
        self.sock.settimeout(timeout)
        self.buffer = bytearray()

    def close(self):
        self.sock.close()

    def command(self, command):
        self.sock.sendall(command.encode("utf-8") + TCL_RPC_SEPARATOR)
        while TCL_RPC_SEPARATOR not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OpenOcdError("OpenOCD closed the Tcl RPC connection")
            self.buffer.extend(chunk)

        response, _, remainder = self.buffer.partition(TCL_RPC_SEPARATOR)
        self.buffer = bytearray(remainder)
        return response.decode("utf-8", errors="replace")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def tcl_quote(value):
    if any(char in value for char in "\x00\r\n"):
        raise ValueError("Tcl arguments cannot contain NUL or newlines")
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("$", "\\$")
    value = value.replace("[", "\\[")
    value = value.replace("]", "\\]")
    return f'"{value}"'


def openocd_call(rpc, *words):
    command = " ".join(tcl_quote(str(word)) for word in words)
    wrapped = (
        f"set __lcd_status [catch [list {command}] __lcd_result __lcd_options]; "
        "if {$__lcd_status && $__lcd_result eq \"\"} { "
        "set __lcd_result [dict get $__lcd_options -errorcode] }; "
        'format "%d\\n%s" $__lcd_status $__lcd_result'
    )
    response = rpc.command(wrapped)
    status, separator, result = response.partition("\n")
    if not separator or status not in ("0", "1"):
        raise OpenOcdError(f"invalid Tcl RPC response: {response!r}")
    if status == "1":
        raise OpenOcdError(f"{words[0]} failed: {result}")
    return result


def temporary_path(directory, stem, suffix):
    descriptor, name = tempfile.mkstemp(
        prefix=f".{stem}.", suffix=suffix, dir=directory
    )
    os.close(descriptor)
    return Path(name)


def convert_screenshot(convert, ppm_path, png_path):
    subprocess.run(
        [
            convert,
            f"{ppm_path}[0]",
            "-channel", "R", "-evaluate", "multiply", "0.90",
            "-channel", "G", "-evaluate", "multiply", "1.20",
            "-channel", "B", "-evaluate", "multiply", "1.75",
            "+channel",
            "-gamma", "1.25",
            f"png:{png_path}",
        ],
        check=True,
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Capture the Air 10 LCD through an existing OpenOCD server."
    )
    parser.add_argument("output", nargs="?", type=Path, default=Path("lcd.png"))
    parser.add_argument("--host", default="127.0.0.1", help="OpenOCD Tcl RPC host")
    parser.add_argument("--port", type=int, default=6666, help="OpenOCD Tcl RPC port")
    parser.add_argument(
        "--timeout", type=float, default=30.0,
        help="TCP timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--controller", choices=("auto", "ili9341", "ili932x"), default="auto"
    )
    parser.add_argument(
        "--tcl",
        type=Path,
        default="tcl/lcd_screenshot.tcl",
        help="LCD capture Tcl backend",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.timeout <= 0:
        print("[!] --timeout must be greater than zero", file=sys.stderr)
        return 2

    output = args.output.resolve()
    tcl_backend = args.tcl.resolve()
    convert = shutil.which("convert")

    if not tcl_backend.is_file():
        print(f"[!] Tcl backend not found: {tcl_backend}", file=sys.stderr)
        return 1
    if convert is None:
        print("[!] ImageMagick 'convert' not found", file=sys.stderr)
        return 1
    if output.suffix.lower() != ".png":
        print("[!] Output path must end in .png", file=sys.stderr)
        return 1
    if not output.parent.is_dir():
        print(f"[!] Output directory not found: {output.parent}", file=sys.stderr)
        return 1

    ppm_path = None
    png_path = None

    try:
        ppm_path = temporary_path(output.parent, output.stem, ".ppm")
        png_path = temporary_path(output.parent, output.stem, ".png")
        print(
            f"[*] Connecting to OpenOCD Tcl RPC at {args.host}:{args.port}",
            flush=True,
        )
        with OpenOcdTclRpc(args.host, args.port, args.timeout) as rpc:
            print(f"[*] Loading {tcl_backend}", flush=True)
            openocd_call(rpc, "source", tcl_backend)
            print(f"[*] Capturing LCD through {args.controller}", flush=True)
            openocd_call(rpc, "lcd_screenshot", ppm_path, args.controller)

        if ppm_path.stat().st_size == 0:
            raise OpenOcdError("OpenOCD produced an empty PPM file")

        print("[*] Applying color correction", flush=True)
        convert_screenshot(convert, ppm_path, png_path)
        os.replace(png_path, output)
        print(f"[+] Wrote {output}", flush=True)
        return 0
    except (OSError, OpenOcdError, ValueError, subprocess.CalledProcessError) as error:
        print(f"[!] {error}", file=sys.stderr)
        return 1
    finally:
        if ppm_path is not None:
            ppm_path.unlink(missing_ok=True)
        if png_path is not None:
            png_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
