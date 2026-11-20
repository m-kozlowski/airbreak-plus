"""Interactive AT terminal for the Air11 modem DatagramCan endpoint."""

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue

from as11_rpc import TransportError


def _receive(t, timeout, *, display=True):
    data = t.recv_payload(timeout=timeout)
    if display:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    return data


def _result(t, timeout, *, opening=False, display=True):
    deadline = time.monotonic() + timeout
    pending = bytearray()
    while (remaining := deadline - time.monotonic()) > 0:
        pending.extend(_receive(t, remaining, display=display))
        while b"\n" in pending:
            line, _, pending = pending.partition(b"\n")
            line = line.rstrip(b"\r")
            if line == b"OK":
                return True
            if opening:
                if line == b"NOT-READY":
                    return False
            elif (line in (b"ERROR", b"NO CARRIER", b"NO DIALTONE", b"BUSY", b"NO ANSWER")
                  or line.startswith((b"+CME ERROR:", b"+CMS ERROR:"))):
                return False
            elif line == b"CONNECT" or line.startswith(b"CONNECT "):
                return True
    raise TimeoutError("no final modem result")


def _pump(t, commands):
    # SLCAN transmit also reads adapter feedback. Keep both directions on
    # one thread so the receiver cannot consume that feedback.
    while True:
        try:
            line = commands.get_nowait()
        except Empty:
            pass
        else:
            if line is None:
                return
            t.send_payload(line)
        try:
            _receive(t, 0.05)
        except TimeoutError:
            pass


def modem_terminal(t, command=None, *, timeout=30):
    t.send_payload(b"AT-PASSTHROUGH-ON\r\n")
    release = True
    try:
        release = _result(t, 5, opening=True, display=command is None)
        if not release:
            raise TransportError("modem passthrough: NOT-READY")
        if command is not None:
            t.send_payload(command.encode() + b"\r\n")
            return 0 if _result(t, timeout) else 1
        commands = Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pump = pool.submit(_pump, t, commands)
            def report_failure(future):
                if future.exception() and sys.stdin.isatty():
                    print(f"Modem terminal stopped: {future.exception()}. Press Enter to leave.",
                          file=sys.stderr, flush=True)
            pump.add_done_callback(report_failure)
            try:
                for line in sys.stdin:
                    if pump.done():
                        break
                    commands.put(line.rstrip("\r\n").encode() + b"\r\n")
            finally:
                commands.put(None)
                pump.result()
        return 0
    finally:
        if release:
            t.send_payload(b"AT-PASSTHROUGH-OFF\r\n")
