"""S9 patch options."""

from .patch_options import ALL_PATCHES, Patch, Phase, Platform


PLATFORM = Platform('s9', phases=(
    Phase('Bootloader', (
        Patch('patch-tamper', 'Patch bootloader integrity calls.', True, 'tamper'),
    )),
    Phase('Configuration', (
        Patch('patch-extra-modes', 'Enable declared therapy mode options.', True, 'extra_modes'),
        Patch('patch-respiratory-events', 'Enable CEN, respiratory statistics, EVE recording.',
              True, 'respiratory_events'),
        Patch('patch-gui-config', 'Activate named clinical settings.', True, 'gui_config'),
        Patch('patch-defaults',
              'Set AutoSet, cmH2O, Pillows, SlimLine, Full access and Patient control defaults.',
              True, 'patch_defaults'),
        Patch('patch-unlock-uilimits', 'Extend pressure UI ranges and set Ti Min/Max to 0.1..4 s.',
              True, 'ui_limits'),
        Patch('patch-asv-ps-range', 'Unlock ASV/ASVAuto PS ranges and fixed separation.',
              True, 'ps_ranges'),
        Patch('patch-motor-nagscreen', 'Extend motor life warning threshold.', True, 'motor'),
        Patch('patch-alarm-board',
              'Set AOA.default=0 and hide HLE when present; skip images without AOA.',
              True, 'no_alarm_board'),
    )),
    Phase('Compiled payloads', (
        Patch('patch-fw-lcd', 'Automatically select a compatible LCD driver.', False, 'lcd'),
    )),
), parameters=(ALL_PATCHES,))
