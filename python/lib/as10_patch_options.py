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
        Patch('patch-font-repack', 'Reclaim flash space by compacting font bitmaps',
              True, 'patch_font_repack', category='Miscellaneous'),
        Patch('patch-expand-heap', 'Give patches about 13.5 KiB more working memory (SX567)',
              True, 'patch_expand_heap', category='Miscellaneous'),
    )),

    Phase('Therapy unlocks', (
        Patch('patch-extra-modes', 'Unlock all therapy modes',
              True, 'extra_modes', category='Therapy unlocks'),
        Patch('patch-gui-config', 'Enable the clinical settings of the unlocked modes',
              True, 'gui_config', category='Therapy unlocks'),
        Patch('patch-unlock-options', 'Unlock hidden setting choices',
              True, 'unlock_option_masks', category='Therapy unlocks'),
        Patch('patch-unlock-uilimits', 'Allow pressure settings from 1 to 30 cmH2O',
              True, 'unlock_ui_limits', category='Therapy unlocks'),
        Patch('patch-asv-ps-range', 'Unlock ASV/ASVAuto PS constraints',
              True, 'asv_unlock_ps_range', category='Therapy unlocks'),
        Patch('patch-adjustable-mcp', 'Allow lowering the ASV pressure cap',
              False, 'patch_adjustable_mcp', category='Therapy unlocks'),
        Patch('patch-ivaps-settings', 'Restore iVAPS clinical settings',
              True, 'enable_ivaps_settings', category='Therapy unlocks',
              requires=('patch-custom-settings',)),
        Patch('patch-ivaps-ps-range', 'Unlock iVAPS PS constraints',
              True, 'ivaps_unlock_ps_range', category='Therapy unlocks'),
    )),

    Phase('Quality of life', (
        Patch('patch-defaults', 'Change factory defaults',
              True, 'patch_defaults', category='Quality of life'),
        Patch('patch-unlock-languages', 'Unlock all built-in languages',
              True, 'unlock_languages', category='Quality of life'),
        Patch('patch-language-fonts', 'Use the right font for each language',
              True, 'patch_language_fonts', category='Quality of life'),
        Patch('patch-font-ua', 'Add Ukrainian glyphs to the standard GUI font',
              False, 'patch_font_ua', category='Quality of life'),
        Patch('patch-therapy-screen',
              'Add a choice of therapy screen styles, with optional flow and pressure graph',
              True, 'patch_therapy_screen', category='Quality of life'),
        Patch('patch-graph-keep-screen-on',
              'Keep the screen on during therapy while the graph is shown',
              False, 'patch_graph_keep_screen_on', category='Quality of life',
              requires=('patch-therapy-screen',)),
        Patch('patch-header-clock', 'Show the time in the Home and therapy screen titles',
              True, 'patch_header_clock', category='Quality of life'),
        Patch('patch-fw-backlight', 'Improve backlight adaptation to ambient light',
              True, 'patch_backlight_adapt', category='Quality of life'),
        Patch('patch-keep-backlight', 'Toggle screen keep-awake by holding the encoder',
              True, 'enable_keep_backlight', category='Quality of life'),
        Patch('patch-custom-palette', 'Patch the custom color palette',
              True, 'custom_palette', category='Quality of life'),
        Patch('patch-target-rh',
              'Set the Climate Control target humidity; custom-settings adds menu control',
              True, 'patch_target_rh', category='Quality of life', parameters=(
                  Parameter('target-rh', 'Target RH, 0..100%. Default: 85.',
                            Value(percentage, 'PERCENT'), 85.0),
              )),
        Patch('patch-past-date', 'Allow setting past date in the menu and over UART',
              True, 'patch_past_date', category='Quality of life'),
        Patch('patch-motor-nagscreen', 'Remove the "Motor life exceeded" nag screen',
              True, 'motor_nagscreen', category='Quality of life'),
    )),

    Phase('Therapy modifications', (
        Patch('patch-fw-squarewave', 'Add Square Wave pressure in S, ST, T and PAC',
              False, 'patch_squarewave', category='Therapy modifications'),
        Patch('patch-fall-time', 'Add Fall Time setting in S, ST, T, PAC, iVAPS',
              False, 'patch_fall_time', category='Therapy modifications'),
        Patch('patch-st-ibr', 'Add adaptive backup-rate control in ST',
              False, 'patch_st_ibr', category='Therapy modifications'),
        Patch('patch-learn-targets', 'Add iVAPS Learn Targets on SX567',
              True, 'enable_learn_targets', category='Therapy modifications',
              requires=('patch-custom-settings',)),
        Patch('patch-autoepap', 'Add AutoEPAP control in iVAPS',
              False, 'patch_autoepap', category='Therapy modifications',
              requires=('patch-font-repack', 'patch-expand-heap')),
        Patch('patch-fw-asv-wrapper', 'Add backup-rate switch in ASV, ASVAuto',
              False, 'patch_asv_task_wrapper', category='Therapy modifications'),
        Patch('patch-fw-vauto-wrapper',
              'Add Custom VAuto: adjustable pressure support and trigger/cycle assist in VAuto',
              False, 'patch_wrapper_limit_max_pdiff', category='Therapy modifications'),
    )),

    Phase('Custom settings integration', (
        Patch('patch-custom-settings', 'Add menu settings for the patches that need them',
              True, 'custom_patch_settings', category='Quality of life'),
    )),

    Phase('Therapy data and reporting', (
        Patch('patch-edf-merge', 'Record all available signals to the SD card in every therapy mode',
              True, 'patch_edf_merge', category='Therapy data and reporting'),
        Patch('patch-fw-vidspoof',
              'Report a device variant that matches the therapy mode, so myAir accepts the data',
              True, 'patch_vid_spoof', category='Therapy data and reporting'),
    )),

    Phase('Miscellaneous', (
        Patch('patch-integrity-check', 'Bypass firmware integrity checks',
              True, 'patch_integrity_check', category='Miscellaneous'),
        Patch('patch-bypass-psuid', 'Bypass Power Supply check at start-up',
              True, 'bypass_psucheck', category='Miscellaneous'),
        Patch('patch-uart-stream-schema',
              'Report live-stream layouts and custom-settings metadata over UART',
              True, 'patch_uart_stream_schema', category='Miscellaneous'),
        Patch('patch-blx-dump', 'Add firmware dump and EEPROM dump and restore over UART to the bootloader',
              True, 'patch_blx_dump', category='Miscellaneous'),
        Patch('patch-fw-lcd', 'Support ILI9325 and ILI9328 replacement displays (detected at startup)',
              False, 'patch_lcd_ili9325', category='Miscellaneous'),
    )),
), run_options=(
    Flag('force-deprecated', 'Apply deprecated patches (you know what you are doing).'),
))
