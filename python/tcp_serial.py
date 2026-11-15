"""
TCP-to-Serial adapters for use with ESP32 AirBridge proxy.

Three TCP modes:
  raw         - plain TCP socket, no handshake (dumb TCP-UART proxy)
  transparent - AirBridge: consume banner, send $TRANSPARENT, raw Q-frames
  text        - AirBridge: arbiter-mediated text protocol (no UART contention)
"""

import socket


class TcpSerial:
    """TCP-to-serial adapter with mode-dependent initialization."""

    text_mode = False

    def __init__(self, host, port=23, timeout=1.0, mode='transparent'):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._baudrate = 57600
        self._mode = mode
        self.text_mode = (mode == 'text')
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(timeout)
        self._sock.connect((host, port))

        if mode == 'raw':
            pass  # no handshake
        elif mode == 'transparent':
            self._read_line(0.5)  # consume banner
            self._sock.sendall(b'$TRANSPARENT\n')
            resp = self._read_line(1.0)
            if not resp.startswith('OK:'):
                self._sock.close()
                raise ConnectionError(f"Failed to enter transparent mode: {resp}")
        elif mode == 'text':
            self._read_line(0.5)  # consume banner

    def _read_line(self, timeout=None):
        if timeout is None:
            timeout = self._timeout
        old_timeout = self._sock.gettimeout()
        self._sock.settimeout(timeout)
        data = b''
        try:
            while True:
                chunk = self._sock.recv(256)
                if not chunk:
                    break
                data += chunk
                if b'\n' in data:
                    break
        except (socket.timeout, OSError):
            pass
        self._sock.settimeout(old_timeout)
        return data.decode(errors='ignore').strip()

    def send_text_cmd(self, cmd_str, timeout=1.0):
        self._sock.sendall(cmd_str.encode() + b'\n')
        return self._read_line(timeout)

    @staticmethod
    def parse_address(port_str):
        rest = port_str[4:]
        if ':' in rest:
            host, p = rest.rsplit(':', 1)
            return (host, int(p))
        return (rest, 23)

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, val):
        self._timeout = val
        self._sock.settimeout(val)

    @property
    def baudrate(self):
        return self._baudrate

    @baudrate.setter
    def baudrate(self, val):
        self._baudrate = val

    def write(self, data):
        try:
            self._sock.sendall(data)
            return len(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return 0

    def read(self, size=1):
        if size == 0:
            return b''
        try:
            data = self._sock.recv(size)
        except socket.timeout:
            return b''
        if not data:
            raise ConnectionError('TCP peer closed the connection')
        return data

    def flush(self):
        # TCP acceptance/ACKs do not establish that the bridge drained its UART.
        pass

    def reset_input_buffer(self):
        try:
            self._sock.setblocking(False)
            while True:
                try:
                    chunk = self._sock.recv(4096)
                    if not chunk:
                        break
                except BlockingIOError:
                    break
            self._sock.setblocking(True)
            self._sock.settimeout(self._timeout)
        except Exception:
            self._sock.setblocking(True)
            self._sock.settimeout(self._timeout)

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass

    @property
    def is_open(self):
        return self._sock.fileno() != -1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def open_tcp(port_str, mode, timeout=1.0):
    host, port = TcpSerial.parse_address(port_str)
    print(f"[*] Connecting to {host}:{port} via TCP ({mode} mode)...")
    return TcpSerial(host, port, timeout=timeout, mode=mode)
