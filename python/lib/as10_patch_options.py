"""Air10 patch options."""

import argparse

from .patch_options import Flag, Parameter, Patch, Phase, Platform, Value


def percentage(value):
    try:
        percent = float(value)
    except ValueError:
        percent = None
    if percent is None or not 0 <= percent <= 100:
        raise argparse.ArgumentTypeError('Percentage from 0 to 100 expected.')
    return percent


# Patch order is part of the implementation. Payloads must be present before
# custom settings patch their ABI slots; all MOP handlers must be registered
# before finalization installs the shared dispatcher and expands the variable
# callback table; CRCs are always last.
PLATFORM = Platform('air10', categories=(
    'Therapy unlocks',
    'Therapy data and reporting',
    'Quality of life',
    'Therapy modifications',
    'Miscellaneous',
), phases=(
    Phase('Firmware preparation', (
        Patch('patch-font-repack', 'Reclaim flash space by compacting font bitmaps.',
              True, 'patch_font_repack', category='Miscellaneous'),
    )),

    Phase('Therapy unlocks', (
        Patch('patch-extra-modes', 'Add all modes.',
              True, 'extra_modes', category='Therapy unlocks'),
        Patch('patch-unlock-uilimits', 'Unlock higher UI limits.',
              True, 'unlock_ui_limits', category='Therapy unlocks'),
        Patch('patch-unlock-options', 'Unlock additional enum option masks.',
              True, 'unlock_option_masks', category='Therapy unlocks'),
        Patch('patch-gui-config', 'Enable all editable options in the settings menu.',
              True, 'gui_config', category='Therapy unlocks'),
        Patch('patch-ivaps-settings', 'Restore iVAPS clinical settings.',
              True, 'enable_ivaps_settings', category='Therapy unlocks',
              requires=('patch-custom-settings',)),
        Patch('patch-learn-targets', 'Expose native iVAPS Learn Targets on SX567.',
              True, 'enable_learn_targets', category='Therapy unlocks',
              requires=('patch-custom-settings',)),
        Patch('patch-asv-ps-range', 'Unlock ASV/ASVAuto pressure constraints.',
              True, 'asv_unlock_ps_range', category='Therapy unlocks'),
        Patch('patch-adjustable-mcp', 'Make the ASV pressure limit adjustable.',
              False, 'patch_adjustable_mcp', category='Therapy unlocks'),
        Patch('patch-ivaps-ps-range', 'Unlock iVAPS AutoEPAP pressure support constraints.',
              True, 'ivaps_unlock_ps_range', category='Therapy unlocks'),
    )),

    Phase('Quality of life', (
        Patch('patch-integrity-check', 'Bypass firmware integrity checks.',
              True, 'patch_integrity_check', category='Quality of life'),
        Patch('patch-bypass-psuid', 'Bypass Power Supply check at start-up.',
              True, 'bypass_psucheck', category='Quality of life'),
        Patch('patch-unlock-languages', 'Unlock all built-in languages.',
              True, 'unlock_languages', category='Quality of life'),
        Patch('patch-language-fonts', 'Select GUI fonts for the active language.',
              True, 'patch_language_fonts', category='Quality of life'),
        Patch('patch-font-ua', 'Add Ukrainian glyphs to the standard GUI font.',
              False, 'patch_font_ua', category='Quality of life'),
        Patch('patch-therapy-screen', 'Select the therapy-screen style and graph.',
              True, 'patch_therapy_screen', category='Quality of life'),
        Patch('patch-defaults', 'Change firmware defaults.',
              True, 'patch_defaults', category='Quality of life'),
        Patch('patch-fw-backlight', 'Improve backlight adaptation to ambient light.',
              True, 'patch_backlight_adapt', category='Quality of life'),
        Patch('patch-keep-backlight', 'Toggle screen keep-awake by holding the encoder.',
              True, 'enable_keep_backlight', category='Quality of life'),
        Patch('patch-header-clock', 'Add a clock to the Home and therapy-screen headers.',
              True, 'patch_header_clock', category='Quality of life'),
        Patch('patch-target-rh',
              'Set the climate target RH to --target-rh; custom settings adds a 70-100% menu control.',
              True, 'patch_target_rh', category='Quality of life', parameters=(
                  Parameter('target-rh', 'Target RH, 0..100%. Default: 85.',
                            Value(percentage, 'PERCENT'), 85.0),
              )),
        Patch('patch-humid-start',
              'Humid Start: hold the heated tube at the target RH temperature while the humidifier warms up.',
              False, 'patch_humid_start', category='Quality of life',
              requires=('patch-font-repack',)),
        Patch('patch-custom-palette', 'Patch the custom color palette.',
              True, 'custom_palette', category='Quality of life'),
        Patch('patch-past-date', 'Allow setting past date in the menu and over UART.',
              True, 'patch_past_date', category='Quality of life'),
        Patch('patch-motor-nagscreen', 'Remove the "Motor life exceeded" nag screen.',
              True, 'motor_nagscreen', category='Quality of life'),
    )),

    Phase('Therapy modifications', (
        Patch('patch-graph-keep-screen-on',
              'Keep the screen awake during therapy while the graph is enabled.',
              False, 'patch_graph_keep_screen_on', category='Quality of life',
              requires=('patch-therapy-screen',)),
        Patch('patch-fw-squarewave', 'Add squarewave pressure shaping.',
              False, 'patch_squarewave', category='Therapy modifications'),
        Patch('patch-fall-time', 'Add adjustable stock S/ST/T/PAC/iVAPS fall time.',
              False, 'patch_fall_time', category='Therapy modifications'),
        Patch('patch-st-ibr', 'Add adaptive backup-rate control in ST.',
              False, 'patch_st_ibr', category='Therapy modifications'),
        Patch('patch-autoepap', 'Add adaptive EPAP control in iVAPS.',
              False, 'patch_autoepap', category='Therapy modifications',
              requires=('patch-font-repack', 'patch-expand-heap')),
        Patch('patch-fw-asv-wrapper', 'Add ASV backup-rate runtime control.',
              False, 'patch_asv_task_wrapper', category='Therapy modifications'),
        Patch('patch-fw-vauto-wrapper', 'Add custom VAuto pressure shaping.',
              False, 'patch_wrapper_limit_max_pdiff', category='Therapy modifications'),
    )),

    Phase('Custom settings integration', (
        Patch('patch-custom-settings', 'Add persistent controls to the clinical menu.',
              True, 'custom_patch_settings', category='Quality of life'),
    )),

    Phase('Therapy data and reporting', (
        Patch('patch-uart-stream-schema',
              'Report live-stream layouts and custom-settings metadata over UART.',
              True, 'patch_uart_stream_schema', category='Miscellaneous'),
        Patch('patch-fw-vidspoof',
              'Set VID from therapy mode, using a regional variant where known.',
              True, 'patch_vid_spoof', category='Therapy data and reporting'),
        Patch('patch-edf-merge', 'Merge the universal EDF signal superset into CCX.',
              True, 'patch_edf_merge', category='Therapy data and reporting'),
    )),

    Phase('Miscellaneous', (
        Patch('patch-expand-heap', 'Expand runtime heap by about 13.5 KiB on SX567 firmware.',
              True, 'patch_expand_heap', category='Miscellaneous'),
        Patch('patch-blx-dump', 'Add flash dump and EEPROM dump/restore over UART.',
              True, 'patch_blx_dump', category='Miscellaneous'),
        Patch('patch-fw-lcd', 'Add the universal ILI9325/ILI9328 LCD driver.',
              False, 'patch_lcd_ili9325', category='Miscellaneous'),
    )),
), run_options=(
    Flag('force-deprecated', 'Apply deprecated patches (you know what you are doing).'),
))
