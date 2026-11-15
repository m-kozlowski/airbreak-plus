"""Host protocol/control-flow checks; hardware behavior is not simulated here."""
import io
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import resmed_flash as flash
import tcp_serial


class Serial:
    def __init__(self, reply):
        self.reply = reply
        self.buffer = bytearray()
        self.requests = []
        self.timeout = 1

    def reset_input_buffer(self):
        self.buffer.clear()

    def write(self, wire):
        self.requests.append(wire)
        self.buffer.extend(self.reply(wire, len(self.requests)))
        return len(wire)

    def read(self, n):
        data = bytes(self.buffer[:n])
        del self.buffer[:n]
        return data

    def flush(self):
        pass


def reply(op, offset, data):
    return flash.build_frame('O', op + struct.pack('<IH', offset, len(data)) + data)


def request_payloads(wire):
    while wire:
        length = int(wire[2:5], 16)
        yield wire[5:length - 4].replace(b'UU', b'U')
        wire = wire[length:]


class TcpFlowControlTests(unittest.TestCase):
    def test_hold_and_reply_capacity_are_confirmed_by_bridge(self):
        sock = Mock()
        with patch.object(tcp_serial.socket, 'socket', return_value=sock), \
                patch.object(tcp_serial.TcpSerial, '_read_line', side_effect=[
                    'AirBridge', 'OK: entering transparent mode idle_timeout=0 reply_buffer=8192']):
            ser = tcp_serial.TcpSerial('bridge', hold=True)
        sock.sendall.assert_called_once_with(b'$TRANSPARENT HOLD\n')
        self.assertEqual(ser.reply_buffer, 8192)
        sock.close.assert_not_called()

    def test_unconfirmed_hold_or_invalid_capacity_closes_connection(self):
        for response in ('ERR: unknown command', 'OK: reply_buffer=8192',
                         'OK: idle_timeout=5 reply_buffer=8192',
                         'OK: idle_timeout=0 reply_buffer=0',
                         'OK: idle_timeout=0 reply_buffer=oops'):
            sock = Mock()
            with self.subTest(response=response), \
                    patch.object(tcp_serial.socket, 'socket', return_value=sock), \
                    patch.object(tcp_serial.TcpSerial, '_read_line', side_effect=['AirBridge', response]), \
                    self.assertRaises(ConnectionError):
                tcp_serial.TcpSerial('bridge', hold=True)
            sock.close.assert_called_once()

    def test_ordinary_legacy_session_uses_one_frame_budget(self):
        with patch.object(tcp_serial.socket, 'socket'), \
                patch.object(tcp_serial.TcpSerial, '_read_line', side_effect=['AirBridge', 'OK: transparent']):
            ser = tcp_serial.TcpSerial('bridge')
        self.assertEqual(ser.reply_buffer, 512)


class StreamReadTests(unittest.TestCase):
    def stream(self, command, data, budget=8192):
        sent = acknowledged = 0
        window = None
        def respond(wire, _):
            nonlocal sent, acknowledged, window
            payload, = request_payloads(wire)
            at, n = struct.unpack_from('<IH', payload, 1)
            if payload[:1] == b'X':
                self.assertIsNone(window, 'only one range request')
                self.assertEqual(payload[7:8], command)
                self.assertEqual(struct.unpack_from('<I', payload, 8)[0], len(data))
                self.assertEqual(n, min(128, budget // 511))
                window = n * 240
            else:
                self.assertEqual(payload[:1], b'A')
                if n:  # cancellation on generator close/failure
                    return b''
                self.assertGreater(at, acknowledged)
                self.assertLessEqual(at, sent)
                acknowledged = at
                if at == len(data):
                    return reply(command.lower(), at, b'')
            frames = []
            while sent < len(data) and sent - acknowledged < window:
                chunk = data[sent:sent + 240]
                frames.append(reply(command.lower(), sent, chunk))
                sent += len(chunk)
            self.assertLessEqual(len(ser.buffer) + sum(map(len, frames)), budget,
                                 'unconsumed wire bytes exceed receiver capacity')
            return b''.join(frames)
        ser = Serial(respond)
        ser.reply_buffer = budget
        return ser

    def test_full_dumps_fit_wire_budget_even_with_all_bytes_escaped(self):
        for command in (b'D', b'R'):
            data = b'U' * (0x100000 if command == b'D' else flash.EEPROM_SIZE)
            ser = self.stream(command, data)
            with self.subTest(command=command):
                chunks = list(flash.read_memory(ser, command, len(data)))
                self.assertEqual(b''.join(chunk for _, chunk in chunks), data)
                self.assertEqual([offset for offset, _ in chunks], list(range(0, len(data), 240)))
                self.assertEqual(len(ser.requests), 1 + (len(data) + 1919) // 1920)

    def test_small_and_odd_receive_budgets_and_window_limit(self):
        for budget in (512, 1024, 1533, 4096, 65536, 1000000):
            with self.subTest(budget=budget):
                data = b'U' * 7777
                ser = self.stream(b'R', data, budget)
                self.assertEqual(b''.join(chunk for _, chunk in flash.read_memory(ser, b'R', len(data))), data)

    def test_slow_consumer_does_not_grant_more_credit_and_close_cancels(self):
        ser = self.stream(b'R', b'U' * 10000)
        chunks = flash.read_memory(ser, b'R', 10000)
        for _ in range(8):
            next(chunks)
        self.assertEqual(len(ser.requests), 1, 'ACK must follow consumption, not precede yield')
        buffered = len(ser.buffer)
        next(chunks)
        self.assertEqual(len(ser.requests), 2)
        self.assertGreater(len(ser.buffer), buffered)
        chunks.close()
        payload, = request_payloads(ser.requests[-1])
        self.assertEqual(payload[:1], b'A')
        self.assertEqual(struct.unpack_from('<H', payload, 5)[0], 1)

    def test_missing_or_damaged_data_aborts_without_acknowledging_gap(self):
        good = reply(b'r', 240, b'b' * 240)
        damaged = good[:-1] + (b'0' if good[-1:] != b'0' else b'1')
        for gap in (b'', damaged):
            ser = Serial(lambda wire, count: (reply(b'r', 0, b'a' * 240) + gap +
                         reply(b'r', 480, b'c')) if count == 1 else b'')
            with self.subTest(gap=bool(gap)), self.assertRaisesRegex(RuntimeError, 'expected 0x000F0|CRC'):
                list(flash.read_memory_range(ser, b'R', 0, 481))
            self.assertEqual(len(ser.requests), 2)
            self.assertEqual(list(request_payloads(ser.requests[-1])), [b'A' + struct.pack('<IH', 240, 1)])

    def test_device_error_in_stream_is_fatal(self):
        ser = Serial(lambda *_: reply(b'r', 0, b'a' * 240) + reply(b'e', 240, b'\x02'))
        with self.assertRaisesRegex(RuntimeError, 'EEPROM at 0x000F0'):
            list(flash.read_memory_range(ser, b'R', 0, 481))

    def test_invalid_range_or_buffer_rejected_before_transmission(self):
        ser = self.stream(b'R', b'!')
        with self.assertRaisesRegex(ValueError, 'range'):
            list(flash.read_memory_range(ser, b'R', 0, 262145))
        ser.reply_buffer = 510
        with self.assertRaisesRegex(RuntimeError, 'buffer'):
            list(flash.read_memory_range(ser, b'R', 0, 1))
        self.assertEqual(ser.requests, [])

    def test_lost_completion_cannot_report_success(self):
        ser = Serial(lambda *_: b'')
        with patch.object(flash, 'read_blx_reply', side_effect=[(b'r', 85, b'U'), None]), \
                self.assertRaisesRegex(RuntimeError, 'timed out'):
            list(flash.read_memory_range(ser, b'R', 85, 86))
        self.assertEqual(len(ser.requests), 3)  # range, final data ACK, cancel

    def test_early_completion_never_accepts_a_hole(self):
        ser = Serial(lambda *_: reply(b'r', 480, b''))
        with self.assertRaisesRegex(RuntimeError, 'expected 0x00000'):
            list(flash.read_memory_range(ser, b'R', 0, 480))

    def test_stream_timeout_is_per_reply_not_whole_range(self):
        ser = self.stream(b'R', b'U' * 3840)
        elapsed = 0.0
        original = flash.read_frame
        def read_frame(ser, timeout):
            nonlocal elapsed
            elapsed += 0.09
            return original(ser, timeout)
        with patch.object(flash.time, 'monotonic', side_effect=lambda: elapsed), \
                patch.object(flash, 'read_frame', side_effect=read_frame):
            result = list(flash.read_memory_range(ser, b'R', 0, 3840))
        self.assertEqual(b''.join(chunk for _, chunk in result), b'U' * 3840)
        self.assertGreater(elapsed, 1.0)

    def test_serial_read_does_not_wait_past_end_of_frame(self):
        ser = Serial(lambda *_: b'')
        wire = reply(b'r', 0, b'U' * 240)
        ser.buffer.extend(wire)
        original_read = ser.read
        def read(n):
            self.assertLessEqual(n, len(ser.buffer), 'read would wait for serial timeout')
            return original_read(n)
        ser.read = read
        frame = flash.read_frame(ser)
        self.assertEqual(frame['raw'], wire)
        self.assertTrue(frame['crc_ok'])
        self.assertEqual(ser.timeout, 1)

    def test_stalled_read_can_resume_after_a_long_pause(self):
        ser = Serial(lambda *_: b'')
        elapsed = 0
        wire = reply(b'r', 0, b'!')
        original = ser.read
        def read(n):
            nonlocal elapsed
            if elapsed == 0:
                elapsed = 60
                return b''
            if elapsed == 60:
                ser.buffer.extend(wire)
                elapsed += 1
            return original(n)
        ser.read = read
        with patch.object(flash.time, 'monotonic', side_effect=lambda: elapsed):
            self.assertEqual(flash.read_blx_reply(ser, timeout=None, strict=True), (b'r', 0, b'!'))


class StreamWriteTests(unittest.TestCase):
    def test_full_restore_sends_frames_until_buffer_credit_is_exhausted(self):
        data = b'U' * flash.EEPROM_SIZE
        offset = 0
        credits = 0
        def respond(wire, request):
            nonlocal offset, credits
            self.assertLessEqual(len(wire), 511)
            payload, = request_payloads(wire)
            if request == 1:
                self.assertEqual(payload, b'X' + struct.pack('<IH', 0, 0) + b'W' + struct.pack('<I', len(data)))
                return reply(b'w', 0, b'')
            self.assertFalse(ser.buffer, 'host must consume credit before sending another window')
            self.assertEqual(payload[:1], b'W')
            at, n = struct.unpack_from('<IH', payload, 1)
            self.assertEqual(at, offset)
            self.assertEqual(payload[7:], data[at:at+n])
            self.assertLessEqual(n, flash.EEPROM_WRITE_BUFFER - at % flash.EEPROM_WRITE_BUFFER)
            offset += n
            if offset % flash.EEPROM_WRITE_BUFFER == 0:
                credits += 1
                return reply(b'w', offset, b'')
            return b''
        ser = Serial(respond)
        original_read = ser.read
        def read(n):
            self.assertEqual(offset % flash.EEPROM_WRITE_BUFFER, 0,
                             'host waited for a reply between data frames')
            return original_read(n)
        ser.read = read
        flash.write_eeprom_range(ser, data)
        self.assertEqual(offset, len(data))
        self.assertEqual(credits, 8)
        self.assertEqual(len(ser.requests), 1 + 8 * 137)

    def test_missing_or_wrong_final_completion_cannot_report_success(self):
        for final in (None, (b'w', 1, b''), (b'w', 3, b'bad')):
            ser = Serial(lambda *_: b'')
            with patch.object(flash, 'read_blx_reply', side_effect=[(b'w', 0, b''), final]), \
                    self.assertRaises(RuntimeError):
                flash.write_eeprom_range(ser, b'new')
            self.assertEqual(len(ser.requests), 2)

    def test_write_error_stops_before_next_window(self):
        ser = Serial(lambda *_: b'')
        with patch.object(flash, 'read_blx_reply', side_effect=[(b'w', 0, b''), (b'e', 256, b'\x06')]), \
                self.assertRaisesRegex(RuntimeError, 'readback differs'):
            flash.write_eeprom_range(ser, bytes(flash.EEPROM_SIZE))
        self.assertEqual(len(ser.requests), 138)

    def test_short_stream_write_is_fatal(self):
        ser = Serial(lambda *_: reply(b'w', 0, b''))
        with patch.object(flash, 'write_transfer_frame', side_effect=OSError('short write')), \
                self.assertRaisesRegex(OSError, 'short write'):
            flash.write_eeprom_range(ser, b'x')

    def test_invalid_input_sends_nothing(self):
        ser = Mock()
        for data in (b'', bytes(flash.EEPROM_SIZE + 1)):
            with self.assertRaises(ValueError):
                flash.write_eeprom_range(ser, data)
        ser.write.assert_not_called()


class EEPROMTests(unittest.TestCase):
    def test_upload_and_write_echo_must_match(self):
        for command in (b'U',):
            with self.subTest(command=command):
                ser = Serial(lambda *_: reply(command.lower(), 0, b'bad'))
                with self.assertRaisesRegex(RuntimeError, 'readback mismatch'):
                    flash.request_blx_chunk(ser, command, 0, 3, b'new')
                self.assertEqual(len(ser.requests), 1)

    def test_crc_corruption_is_ignored_before_valid_frame(self):
        valid = reply(b'u', 0x55, b'U' * 240)
        corrupt = valid[:-1] + (b'0' if valid[-1:] != b'0' else b'1')
        ser = Serial(lambda wire, n: (corrupt + valid) if n == 1 else valid)
        self.assertEqual(flash.request_blx_chunk(ser, b'U', 0x55, 240, b'U' * 240), b'U' * 240)
        self.assertLessEqual(len(ser.requests), 2)


    def test_failed_restore_never_resets(self):
        args = SimpleNamespace(eeprom_module=None, no_reset=False)
        with patch.object(flash, 'connect_dump_bootloader', return_value=('SX577-0200', flash.PLATFORMS['SX577'])), \
                patch.object(flash, 'load_eeprom_module', return_value=b'module'), \
                patch.object(flash, 'upload_eeprom_module'), \
                patch.object(flash, 'restore_eeprom_data', side_effect=RuntimeError('verify failed')), \
                patch.object(flash, 'send_cmd') as reset, redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                flash.transfer_eeprom(None, args, bytes(262144))
            reset.assert_not_called()

    def test_stale_response_is_ignored(self):
        ser = Serial(lambda *_: reply(b'd', 0, b'old') + reply(b'd', 3, b'new'))
        self.assertEqual(flash.request_blx_chunk(ser, b'D', 3, 3), b'new')

    def test_errors_stop_without_retry(self):
        for payload in (b'E' + struct.pack('<IH', 0, 0),
                        b'e' + struct.pack('<IH', 0, 1) + b'\x06'):
            ser = Serial(lambda *_: flash.build_frame('O', payload))
            with self.assertRaises(RuntimeError):
                flash.request_blx_chunk(ser, b'U', 0, 1, b'x')
            self.assertEqual(len(ser.requests), 1)

    def test_short_transport_write_is_fatal(self):
        ser = Mock()
        ser.write.return_value = 3
        with self.assertRaisesRegex(OSError, 'short write'):
            flash.request_blx_chunk(ser, b'U', 0, 1, b'x')

    def test_all_u_bytes_fit_native_frame_limit(self):
        ser = Serial(lambda *_: reply(b'u', 0x5555, b'U' * 240))
        self.assertEqual(flash.request_blx_chunk(ser, b'U', 0x5555, 240, b'U' * 240), b'U' * 240)
        self.assertLessEqual(len(ser.requests[0]), 511)


    def test_module_needs_only_a_binary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'module.bin'
            data = b'\x00\x55\xff' * 10
            binary.write_bytes(data)
            self.assertEqual(flash.load_eeprom_module('SX577-0200', binary), data)
            self.assertEqual(list(Path(tmp).iterdir()), [binary])
            with self.assertRaisesRegex(RuntimeError, 'does not support BID'):
                flash.load_eeprom_module('SX525-0300', binary)
            for invalid in (b'', bytes(flash.EEPROM_MODULE_LIMIT + 1)):
                binary.write_bytes(invalid)
                with self.subTest(size=len(invalid)), self.assertRaisesRegex(RuntimeError, 'module size'):
                    flash.load_eeprom_module('SX577-0200', binary)

    def test_rejected_module_never_starts_restore_or_resets(self):
        def reject_module(wire, _):
            payload = wire[5:-4].replace(b'UU', b'U')
            offset, size = struct.unpack_from('<IH', payload, 1)
            if payload[:1] == b'U':
                return reply(b'u', offset, payload[7:])
            self.assertEqual(payload, b'X' + struct.pack('<IH', 0, 0) + b'I')
            return reply(b'E', 0, b'')
        ser = Serial(reject_module)
        args = SimpleNamespace(eeprom_module=None, no_reset=False)
        with patch.object(flash, 'connect_dump_bootloader', return_value=('SX577-0200', flash.PLATFORMS['SX577'])), \
                patch.object(flash, 'load_eeprom_module', return_value=b'wrong module'), \
                patch.object(flash, 'restore_eeprom_data') as restore, \
                patch.object(flash, 'send_cmd') as reset, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'BLX rejected the RAM module'):
                flash.transfer_eeprom(ser, args, bytes(flash.EEPROM_SIZE))
            restore.assert_not_called()
            reset.assert_not_called()
        self.assertEqual(len(ser.requests), 2)

    def test_final_read_detects_corruption_after_write_ack(self):
        data = bytes(range(256)) * 1024
        with patch.object(flash, 'write_eeprom_range') as writes, \
                patch.object(flash, 'read_memory', return_value=[(0, data[:240]), (240, b'!' + data[241:480])]), \
                redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'final EEPROM verification failed'):
                flash.restore_eeprom_data(None, data)
        self.assertEqual(writes.call_count, 1)

    def test_success_requires_complete_final_read(self):
        data = b'U' * 262144
        read = bytearray()
        def read_memory(ser, command, size):
            for offset, n in flash.transfer_ranges(size):
                read.extend(data[offset:offset + n])
                yield offset, data[offset:offset + n]
        with patch.object(flash, 'write_eeprom_range'), \
                patch.object(flash, 'read_memory', side_effect=read_memory), redirect_stdout(io.StringIO()):
            flash.restore_eeprom_data(None, data)
        self.assertEqual(read, data)

    def test_failure_never_sends_reset_and_preserves_dump_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'backup.bin'
            target.write_bytes(b'original')
            args = SimpleNamespace(eeprom_module=None, dump_eeprom=str(target), no_reset=False)
            with patch.object(flash, 'connect_dump_bootloader', return_value=('SX577-0200', flash.PLATFORMS['SX577'])), \
                    patch.object(flash, 'load_eeprom_module', return_value=b'module'), \
                    patch.object(flash, 'upload_eeprom_module'), \
                    patch.object(flash, 'read_memory', side_effect=RuntimeError('timeout')), \
                    patch.object(flash, 'send_cmd') as reset, redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    flash.transfer_eeprom(None, args)
                reset.assert_not_called()
            self.assertEqual(target.read_bytes(), b'original')
            self.assertTrue(Path(str(target) + '.part').exists())

    def test_restore_dry_run_never_opens_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'eeprom.bin'
            path.write_bytes(bytes(262144))
            argv = ['resmed_flash.py', '-p', 'unused', '--restore-eeprom', str(path), '--dry-run']
            with patch.object(sys, 'argv', argv), patch.object(flash.serial, 'Serial') as port, redirect_stdout(io.StringIO()):
                self.assertEqual(flash.main(), 0)
                port.assert_not_called()

    def test_invalid_restore_size_rejected_before_port_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.bin'
            path.write_bytes(b'bad')
            argv = ['resmed_flash.py', '-p', 'unused', '--restore-eeprom', str(path), '--yes']
            with patch.object(sys, 'argv', argv), patch.object(flash.serial, 'Serial') as port, \
                    patch.object(sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit):
                flash.main()
            port.assert_not_called()

    def test_flash_dump_wire_contract_unchanged(self):
        ser = Serial(lambda *_: reply(b'd', 0xfffff, b'U'))
        self.assertEqual(flash.request_blx_chunk(ser, b'D', 0xfffff, 1), b'U')
        self.assertEqual(ser.requests, [flash.build_frame('O', b'D\xff\xff\x0f\x00\x01\x00')])


class SharedTransferTests(unittest.TestCase):
    def test_dump_ignores_stale_error_and_damaged_response(self):
        valid = reply(b'd', 240, b'U' * 240)
        damaged = valid[:-1] + (b'0' if valid[-1:] != b'0' else b'1')
        stale = reply(b'E', 0, b'')
        ser = Serial(lambda *_: stale + damaged + valid)
        self.assertEqual(flash.request_blx_chunk(ser, b'D', 240, 240), b'U' * 240)
        self.assertEqual(len(ser.requests), 1)

    def test_flash_dump_rejection_is_fatal(self):
        ser = Serial(lambda *_: reply(b'E', 0x100000, b''))
        with self.assertRaisesRegex(RuntimeError, 'rejected dump range'):
            flash.request_blx_chunk(ser, b'D', 0x100000, 1)
        self.assertEqual(len(ser.requests), 1)

    def test_failed_dump_keeps_partial_data_and_existing_target(self):
        for command in (b'D', b'R'):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / 'dump.bin'
                target.write_bytes(b'previous dump')
                def interrupted(*args):
                    yield 0, b'U' * 240
                    raise RuntimeError('timeout')
                with patch.object(flash, 'read_memory', side_effect=interrupted), \
                        redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                    flash.dump_memory(None, str(target), 241, command)
                self.assertEqual(target.read_bytes(), b'previous dump')
                self.assertEqual(Path(str(target) + '.part').read_bytes(), b'U' * 240)

    def test_validation_precedes_publishing_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'dump.bin'
            target.write_bytes(b'previous dump')
            validate = Mock(side_effect=RuntimeError('bad CRC'))
            with patch.object(flash, 'read_memory', return_value=[(0, b'new')]), \
                    redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'bad CRC'):
                flash.dump_memory(None, str(target), 3, b'D', validate)
            validate.assert_called_once_with(b'new')
            self.assertEqual(target.read_bytes(), b'previous dump')
            self.assertEqual(Path(str(target) + '.part').read_bytes(), b'new')

    def test_success_publishes_dump(self):
        for command in (b'D', b'R'):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / 'dump.bin'
                data = b'U' * 240 + b'!'
                with patch.object(flash, 'read_memory', return_value=[(0, data[:240]), (240, data[240:])]), \
                        redirect_stdout(io.StringIO()):
                    flash.dump_memory(None, str(target), len(data), command)
                self.assertEqual(target.read_bytes(), data)
                self.assertFalse(Path(str(target) + '.part').exists())

    def test_failed_baud_change_never_sends_reset(self):
        ser = SimpleNamespace(baudrate=460800)
        with patch.object(flash, 'switch_baud', return_value=False), \
                patch.object(flash, 'send_cmd') as send, self.assertRaises(RuntimeError):
            flash.reset_device(ser, flash.PLATFORMS['SX577'])
        send.assert_not_called()

    def test_no_reset_restores_baud_before_disconnect(self):
        ser = SimpleNamespace(baudrate=460800)
        with patch.object(flash, 'switch_baud', return_value=True) as baud, \
                patch.object(flash, 'send_cmd') as send:
            flash.reset_device(ser, flash.PLATFORMS['SX577'], reset=False)
        baud.assert_called_once_with(ser, 57600)
        send.assert_not_called()

    def test_conflicting_operations_rejected_before_opening_port(self):
        for options in ([], ['--dump', 'flash.bin', '--dump-eeprom', 'eeprom.bin'],
                        ['--info', '--restore-eeprom', 'eeprom.bin', '--yes']):
            with self.subTest(options=options), \
                    patch.object(sys, 'argv', ['resmed_flash.py', '-p', 'unused'] + options), \
                    patch.object(sys, 'stderr', io.StringIO()), \
                    patch.object(flash.serial, 'Serial') as port, self.assertRaises(SystemExit):
                flash.main()
            port.assert_not_called()


if __name__ == '__main__':
    unittest.main()
