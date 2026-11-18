"""S9 patch options."""

from .patch_options import ALL_PATCHES, Flag, Patch, Phase, Platform


PLATFORM = Platform('s9', phases=(
    Phase('Bootloader', (
        Patch('patch-tamper', 'Bypass bootloader integrity checks', True, 'tamper'),
    )),
    Phase('Configuration', (
        Patch('patch-extra-modes', 'Unlock all therapy modes', True, 'extra_modes'),
        Patch('patch-respiratory-events', 'Enable respiratory event detection, statistics and recording',
              True, 'respiratory_events'),
        Patch('patch-gui-config', 'Enable the clinical settings of the unlocked modes', True, 'gui_config'),
        Patch('patch-defaults', 'Change factory defaults', True, 'patch_defaults'),
        Patch('patch-unlock-uilimits', 'Allow pressure settings from 1 to 30 cmH2O and Ti from 0.1 to 4 s',
              True, 'ui_limits'),
        Patch('patch-asv-ps-range', 'Unlock ASV/ASVAuto PS constraints', True, 'ps_ranges'),
        Patch('patch-motor-nagscreen', 'Remove the motor life warning', True, 'motor'),
        Patch('patch-alarm-board',
              'Default to no alarm module and hide its leak alarm setting',
              True, 'no_alarm_board'),
    )),
    Phase('Compiled payloads', (
        Patch('patch-fw-lcd', 'Support ILI9225 displays (detected at startup)', False, 'lcd'),
    )),
), parameters=(ALL_PATCHES,), run_options=(
    Flag('allow-invalid-input-crc', 'Explicitly allow a research input with invalid region CRCs.'),
))
