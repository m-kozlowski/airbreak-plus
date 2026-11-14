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
PLATFORM = Platform('air10', phases=(
    Phase('Firmware preparation', (
        Patch('patch-font-repack', 'Reclaim flash space by compacting font bitmaps.',
              True, 'patch_font_repack'),
    )),

    Phase('Therapy unlocks', (
        Patch('patch-extra-modes', 'Add all modes.',
              True, 'extra_modes'),
        Patch('patch-unlock-uilimits', 'Unlock higher UI limits.',
              True, 'unlock_ui_limits'),
        Patch('patch-unlock-options', 'Unlock additional enum option masks.',
              True, 'unlock_option_masks'),
        Patch('patch-gui-config', 'Enable all editable options in the settings menu.',
              True, 'gui_config'),
        Patch('patch-ivaps-settings', 'Restore iVAPS clinical settings.',
              True, 'enable_ivaps_settings', requires=('patch-custom-settings',)),
        Patch('patch-asv-ps-range', 'Unlock ASV/ASVAuto pressure constraints.',
              True, 'asv_unlock_ps_range'),
        Patch('patch-adjustable-mcp', 'Make the ASV pressure limit adjustable.',
              False, 'patch_adjustable_mcp'),
        Patch('patch-ivaps-ps-range', 'Unlock iVAPS AutoEPAP pressure support constraints.',
              True, 'ivaps_unlock_ps_range'),
    )),

    Phase('Quality of life', (
        Patch('patch-integrity-check', 'Bypass firmware integrity checks.',
              True, 'patch_integrity_check'),
        Patch('patch-bypass-psuid', 'Bypass Power Supply check at start-up.',
              True, 'bypass_psucheck'),
        Patch('patch-unlock-languages', 'Unlock all built-in languages.',
              True, 'unlock_languages'),
        Patch('patch-language-fonts', 'Select GUI fonts for the active language.',
              True, 'patch_language_fonts'),
        Patch('patch-font-ua', 'Add Ukrainian glyphs to the standard GUI font.',
              False, 'patch_font_ua'),
        Patch('patch-therapy-screen', 'Select the therapy-screen style and graph.',
              True, 'patch_therapy_screen'),
        Patch('patch-defaults', 'Change firmware defaults.',
              True, 'patch_defaults'),
        Patch('patch-fw-backlight', 'Improve backlight adaptation to ambient light.',
              True, 'patch_backlight_adapt'),
        Patch('patch-keep-backlight', 'Toggle screen keep-awake by holding the encoder.',
              True, 'enable_keep_backlight'),
        Patch('patch-header-clock', 'Add a clock to the Home and therapy-screen headers.',
              True, 'patch_header_clock'),
        Patch('patch-target-rh',
              'Set the climate target RH to --target-rh; custom settings adds a 70-100% menu control.',
              True, 'patch_target_rh', parameters=(
                  Parameter('target-rh', 'Target RH, 0..100%. Default: 85.',
                            Value(percentage, 'PERCENT'), 85.0),
              )),
        Patch('patch-custom-palette', 'Patch the custom color palette.',
              True, 'custom_palette'),
        Patch('patch-past-date', 'Allow setting past date in the menu and over UART.',
              True, 'patch_past_date'),
        Patch('patch-motor-nagscreen', 'Remove the "Motor life exceeded" nag screen.',
              True, 'motor_nagscreen'),
    )),

    Phase('Therapy modifications', (
        Patch('patch-graph-keep-screen-on',
              'Keep the screen awake during therapy while the graph is enabled.',
              False, 'patch_graph_keep_screen_on', requires=('patch-therapy-screen',)),
        Patch('patch-fw-squarewave', 'Add squarewave pressure shaping.',
              False, 'patch_squarewave'),
        Patch('patch-fall-time', 'Add adjustable stock S/ST/T/PAC/iVAPS fall time.',
              False, 'patch_fall_time'),
        Patch('patch-st-ibr', 'Add adaptive backup-rate control in ST.',
              False, 'patch_st_ibr'),
        Patch('patch-autoepap', 'Add adaptive EPAP control in iVAPS.',
              False, 'patch_autoepap', requires=('patch-font-repack', 'patch-expand-heap')),
        Patch('patch-fw-asv-wrapper', 'Add ASV backup-rate runtime control.',
              False, 'patch_asv_task_wrapper'),
        Patch('patch-fw-vauto-wrapper', 'Add custom VAuto pressure shaping.',
              False, 'patch_wrapper_limit_max_pdiff'),
    )),

    Phase('Custom settings integration', (
        Patch('patch-custom-settings', 'Add persistent controls to the clinical menu.',
              True, 'custom_patch_settings'),
    )),

    Phase('Therapy data and reporting', (
        Patch('patch-uart-stream-schema',
              'Report live-stream layouts and custom-settings metadata over UART.',
              True, 'patch_uart_stream_schema'),
        Patch('patch-fw-vidspoof',
              'Set VID from therapy mode, using a regional variant where known.',
              True, 'patch_vid_spoof'),
        Patch('patch-edf-merge', 'Merge the universal EDF signal superset into CCX.',
              True, 'patch_edf_merge'),
    )),

    Phase('Miscellaneous', (
        Patch('patch-expand-heap', 'Expand runtime heap by about 13.5 KiB on SX567 firmware.',
              True, 'patch_expand_heap'),
        Patch('patch-blx-dump', 'Add bootloader support for firmware dumps over UART.',
              True, 'patch_blx_dump'),
        Patch('patch-fw-lcd', 'Add the universal ILI9325/ILI9328 LCD driver.',
              False, 'patch_lcd_ili9325'),
    )),
), run_options=(
    Flag('force-deprecated', 'Apply deprecated patches (you know what you are doing).'),
))
