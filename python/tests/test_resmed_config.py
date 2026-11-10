import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import resmed_config as config


class CustomSettingsRegistryTests(unittest.TestCase):
    def test_v1_entries(self):
        numeric = config.parse_custom_settings_entry(
            'V4 04 00000FFF LLH 0001 0001 00 00: High', 1)
        self.assertEqual((numeric['units'], numeric['groups'], numeric['label']),
                         ('', [], 'High'))
        enum = config.parse_custom_settings_entry(
            'V8 00 00000040 RPO Custom VAuto', 1)
        self.assertEqual((enum['groups'], enum['label']), ([], 'Custom VAuto'))

    def test_v2_entries(self):
        numeric = config.parse_custom_settings_entry(
            'V4 04 00000FFF LBH 0001 0001 00 00: 02 03:LCD 07:Buttons High', 2)
        self.assertEqual((numeric['units'], numeric['groups'], numeric['label']),
                         ('', ['LCD', 'Buttons'], 'High'))
        enum = config.parse_custom_settings_entry(
            'V8 00 00000040 RPO 00 Custom VAuto', 2)
        self.assertEqual((enum['groups'], enum['label']), ([], 'Custom VAuto'))

    def test_v2_localized_lengths_count_bytes(self):
        value = (b'V4 00 00000040 RCM 0032 000A 01 06:cm H\xc2\xb2 '
                 b'01 0B:Ci\xc5\x9bnienie  Limit')
        numeric = config.parse_custom_settings_entry(value.decode('latin-1'), 2)
        self.assertEqual(numeric['units'], 'cm H\u00b2')
        self.assertEqual(numeric['groups'], ['Ci\u015bnienie '])
        self.assertEqual(numeric['label'], 'Limit')

    def test_v2_rejects_malformed_groups(self):
        for tail in ('XX Label', '01 03:AB', '01 03:LCDLabel', '02 03:LCD Label'):
            with self.subTest(tail=tail), self.assertRaises(ValueError):
                config.parse_custom_settings_entry('V8 00 00000040 RPO ' + tail, 2)

    def test_v2_command_shows_group_path(self):
        replies = {
            'G C &CSG': b'02 01',
            'G C &CSG 00': b'V4 04 00000FFF LBH 0001 0001 00 00: 02 03:LCD 07:Buttons High',
            'G S #LBH': b'64',
            'G C #LBH': b'2 00 64',
        }

        def send_cmd(ser, command, **kwargs):
            payload = command.encode('ascii') + b' = ' + replies[command]
            return payload, [{'type': 'R', 'payload': payload}]

        output = io.StringIO()
        with patch.object(config, 'send_cmd', side_effect=send_cmd), redirect_stdout(output):
            self.assertEqual(config.cmd_custom_settings(None), 0)
        self.assertIn('Configuration > LCD > Buttons: LBH = 64  High', output.getvalue())


if __name__ == '__main__':
    unittest.main()
