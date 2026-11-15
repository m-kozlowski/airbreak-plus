"""Injection guards for generated layouts, including flash-to-RAM mappings."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.compiled_payload import CompiledPayloadError, CompiledPayloadMixin


class PayloadMappingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        caves = Path(self.directory.name) / 'caves.tsv'
        caves.write_text('test blx 0x08000100 0x08000110 0x08000100 0x20000000 0\n')
        self.entry = {'runtime': 0x20000000, 'storage': 0x08000100, 'size': 4}
        self.payload = b'code'
        self.patcher = CompiledPayloadMixin()
        self.patcher.PAYLOAD_CAVES_FILE = str(caves)
        self.patcher._load_payload_layout = Mock(return_value=('test', {'loader': self.entry}))
        self.patcher._require_versioned_artifact = Mock(return_value='loader.elf')
        fw = bytearray(b'\xff' * 512)
        self.patcher.asf = SimpleNamespace(FLASH_BASE=0x08000000, fw=fw)
        self.patcher.asf.patch = Mock(side_effect=lambda data, off, **kw:
                                     fw.__setitem__(slice(off, off + len(data)), data))
        # Let the ELF agree with a forged layout, so the independent cave table
        # must reject invalid storage and runtime mappings before any write.
        self.addCleanup(patch.stopall)
        patch('lib.compiled_payload.elf_text_address',
              side_effect=lambda _: self.entry['runtime']).start()
        patch('lib.compiled_payload.elf_binary_data', return_value=self.payload).start()

    def test_valid_mapping_and_reapplication(self):
        self.assertEqual(self.patcher._inject_payload('loader', self.payload), (0x08000100, 256))
        self.assertEqual(self.patcher.asf.fw[256:260], self.payload)
        self.patcher._inject_payload('loader', self.payload)
        self.assertEqual(self.patcher.asf.patch.call_count, 1)

    def test_invalid_mapping_does_not_modify_image(self):
        for storage, runtime in ((0x08000104, 0x20000000),
                                 (0x08000100, 0x20000004),
                                 (0x08000110, 0x20000010)):
            with self.subTest(storage=storage, runtime=runtime):
                self.entry.update(storage=storage, runtime=runtime)
                with self.assertRaises(CompiledPayloadError):
                    self.patcher._inject_payload('loader', self.payload)
                self.patcher.asf.patch.assert_not_called()

    def test_exact_cave_end_is_allowed(self):
        self.entry.update(storage=0x0800010c, runtime=0x2000000c)
        self.patcher._inject_payload('loader', self.payload)
        self.assertEqual(self.patcher.asf.fw[268:272], self.payload)

    def test_crossing_cave_end_is_rejected(self):
        self.entry.update(storage=0x0800010e, runtime=0x2000000e)
        with self.assertRaises(CompiledPayloadError):
            self.patcher._inject_payload('loader', self.payload)
        self.patcher.asf.patch.assert_not_called()

    def test_abi_value_is_checked_before_injection_and_reapplication(self):
        with patch('lib.compiled_payload.elf_symbol_address', return_value=0x20000002), \
                patch('lib.compiled_payload.elf_symbol_size', return_value=2):
            abi = {'expected_crc': b'\x12\x34'}
            self.patcher._inject_payload('loader', self.payload, abi=abi)
            self.assertEqual(self.patcher.asf.fw[256:260], b'co\x12\x34')
            self.patcher._inject_payload('loader', self.payload, abi=abi)
            self.assertEqual(self.patcher.asf.patch.call_count, 1)
            with self.assertRaises(CompiledPayloadError):
                self.patcher._inject_payload('loader', self.payload, abi={'expected_crc': b'\x56\x78'})
            self.assertEqual(self.patcher.asf.patch.call_count, 1)

    def test_abi_rejects_wrong_size_or_outside_payload_without_writing(self):
        for address, value in ((0x20000002, b'x'), (0x20000004, b'xx')):
            with self.subTest(address=address, value=value), \
                    patch('lib.compiled_payload.elf_symbol_address', return_value=address), \
                    patch('lib.compiled_payload.elf_symbol_size', return_value=2), \
                    self.assertRaises(CompiledPayloadError):
                self.patcher._inject_payload('loader', self.payload, abi={'expected_crc': value})
            self.patcher.asf.patch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
