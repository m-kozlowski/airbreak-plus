#!/usr/bin/env python3
"""
ResMed AirSense UART Configuration Tool

Read, write, dump, and restore device configuration variables over UART.
Variables are organized into groups matching the SETTINGS/*.tgt files.

"""

import serial
import argparse
import time
import sys
import json
import zlib
from pathlib import Path


GROUPS = {
    'AGL': ['AFC', 'STU', 'MPI', 'MPA'],
    'BGL': ['CCS', 'CCP', 'PNA', 'SRN', 'PCD', 'PCB', 'SNB', 'SNZ', 'FLZ', 'FLG',
            'PZH', 'PSH'],
    'CGL': ['STP', 'IPC'],
    'DGL': ['BRE', 'VCS', 'VTS', 'ITN', 'ITX', 'ITT', 'RRT'],
    'EGL': ['EPX', 'EPA', 'EPT', 'EPR'],
    'IGL': ['EBE', 'RST', 'RSC', 'EPS', 'EPP', 'IPP'],
    'MGL': ['QFC', 'ACC', 'HME', 'SCF', 'TLF', 'ALV', 'NMF', 'SPX', 'APX', 'LMA',
            'HLE', 'ALR', 'SST', 'RMT', 'RMA'],
    'NGL': ['ATH'],
    'PGL': ['ABF', 'HTF', 'HTS', 'HTX', 'HMS', 'HMX', 'CCO', 'TBT', 'MSK'],
    'QXH': ['EAS', 'AXS', 'EAI', 'EAX', 'ANS'],
    'QXJ': ['IVS', 'WMV', 'IBR', 'WPM', 'WPA', 'EPI', 'PHI', 'PHT'],
    'RGL': ['RPF', 'RCF', 'RXF', 'RDF', 'RPW', 'RCW', 'RXW', 'RDW', 'RPH', 'RCH',
            'RXH', 'RDH', 'RPO', 'RCM', 'RXM', 'RDM'],
    'SGL': ['IHU', 'PRD', 'TMU', 'LAN', 'LNC', 'MOP'],
    'UGL': ['TUD'],
    'VGL': ['SPT', 'STV', 'MNE', 'MXI'],
    'XGL': ['STE', 'MNS', 'MXS', 'EEP'],
}

# Build reverse lookup: var name > group
VAR_TO_GROUP = {}
for grp, vars_list in GROUPS.items():
    for v in vars_list:
        VAR_TO_GROUP[v] = grp

ALL_VARS = [v for grp in sorted(GROUPS) for v in GROUPS[grp]]

GROUP_ALIASES = {
    'all': list(GROUPS.keys()),
}

GROUP_DESC = {
    'AGL': 'AutoSet params',
    'BGL': 'Board/identity/calibration',
    'CGL': 'CPAP params',
    'DGL': 'Bilevel timing',
    'EGL': 'EPR params',
    'IGL': 'Bilevel pressure',
    'MGL': 'Machine settings',
    'NGL': 'Backlight?',
    'PGL': 'Peripherals/accessories',
    'QXH': 'ASVAuto params',
    'QXJ': 'iVAPS params',
    'RGL': 'Reminders/replacement',
    'SGL': 'System settings',
    'UGL': 'Usage data',
    'VGL': 'VAuto params',
    'XGL': 'ASV fixed params',
}

# Collected from ResScan metadata (M36 V26/V39), STR EDF col1 (g[13] PSTR), GUI descriptors (g[4]/g[6]/g[8])
VAR_DESC = {
    'ABF': 'AB Filter',
    'ACC': 'Patient Access',
    'AFC': 'AutoSet Comfort/Response',
    'ALR': 'Leak Alert',
    'ALV': 'Alarm Vol/Test',
    'ANS': 'ASVAuto Min PS',
    'APX': 'Apnea Alarm',
    'AXS': 'ASVAuto Max PS',
    'BRE': 'Backup Rate',
    'CCO': 'Climate Control',
    'EAI': 'ASVAuto Min EPAP',
    'EAS': 'ASVAuto Start EPAP',
    'EAX': 'ASVAuto Max EPAP',
    'EBE': 'Easy-Breathe',
    'EEP': 'ASV EPAP',
    'EPA': 'EPR Clinical Enable',
    'EPI': 'iVAPS EPAP',
    'EPP': 'Bilevel EPAP',
    'EPR': 'EPR Level',
    'EPS': 'Bilevel Start EPAP',
    'EPT': 'EPR Type',
    'EPX': 'EPR Patient Enable',
    'HLE': 'High Leak Alarm',
    'HME': 'Ext. Humidifier',
    'HMS': 'Humidity Level',
    'HMX': 'Humidity Enable',
    'HTF': 'Tube Temp',
    'HTS': 'Tube Temp',
    'HTX': 'Tube Temp Enable',
    'IBR': 'iVAPS Target Rate',
    'IHU': 'Height Units',
    'IPC': 'CPAP Set Pressure',
    'IPP': 'Bilevel IPAP',
    'ITN': 'Ti Min',
    'ITT': 'Ti',
    'ITX': 'Ti Max',
    'IVS': 'iVAPS Start EPAP',
    'LAN': 'Language',
    'LCA': 'LCD Text Active',
    'LCT': 'LCD Text',
    'LMA': 'Low MV Alarm',
    'LNC': 'Language Config Bitmask',
    'MFT': 'Mask Fitting Mode',
    'MNE': 'VAuto Min EPAP',
    'MNS': 'ASV Min PS',
    'MOP': 'Therapy Mode',
    'MPA': 'AutoSet Max Pressure',
    'MPI': 'AutoSet Min Pressure',
    'MSK': 'Mask Type',
    'MXI': 'VAuto Max IPAP',
    'MXS': 'ASV Max PS',
    'NMF': 'Non-Vent Mask',
    'PBR': 'Calibration Serial Parameter',
    'PHI': 'Height',
    'PHT': 'Height',
    'PRD': 'Pressure Units',
    'QFC': 'Airplane Mode',
    'RCF': 'Recurrence Filter',
    'RCH': 'Recurrence Heated Tube',
    'RCM': 'Recurrence Mask',
    'RCW': 'Recurrence Water Tub',
    'RDF': 'Reminder Due: Filter',
    'RDH': 'Reminder Due: Tube',
    'RDM': 'Reminder Due: Mask',
    'RDW': 'Reminder Due: Water Tub',
    'REM': 'Factory Reset',
    'RMA': 'Ramp Enable',
    'RMT': 'Ramp Time',
    'RRT': 'Resp. Rate',
    'RPF': 'Recurrence Enable: Filter',
    'RPH': 'Recurrence Enable: Tube',
    'RPO': 'Recurrence Enable: Mask',
    'RPW': 'Recurrence Enable: Water Tub',
    'RSC': 'Rise Time Select',
    'RST': 'Rise Time',
    'RXF': 'Reminder Date Enable: Filter',
    'RXH': 'Reminder Date Enable: Tube',
    'RXM': 'Reminder Date Enable: Mask',
    'RXW': 'Reminder Date Enable: Water Tub',
    'SCF': 'Confirm Stop',
    'SPT': 'VAuto PS',
    'SPX': 'Low SpO2 Alarm',
    'SST': 'SmartStart',
    'STE': 'ASV Start EPAP',
    'STP': 'CPAP Start Pressure',
    'STU': 'AutoSet Start Pressure',
    'STV': 'VAuto Start EPAP',
    'TBT': 'Tube Type',
    'TLF': 'Therapy LED',
    'TMU': 'Temp. Units',
    'VCS': 'Cycle Sensitivity',
    'VTS': 'Trigger Sensitivity',
    'WMV': 'iVAPS Target Va',
    'WPA': 'iVAPS Max PS',
    'WPM': 'iVAPS Min PS',

    'BID': 'Bootloader ID',
    'CID': 'Config Software ID',
    'DAC': 'Date',
    'FGT': 'FG Type',
    'PCB': 'PCB ID',
    'PCD': 'Product Code',
    'PNA': 'Product Name',
    'SID': 'Software ID',
    'SRN': 'Serial Number',
    'TIC': 'Time',

    'AET': 'Apnea Event Type',
    'BLL': 'Jump to Bootloader',
    'BLS': 'Bootloader Status',
    'CAL': 'Calibration Service Select',
    'DRX': 'Calibration Serial RX',
    'DTX': 'Calibration Serial TX',
    'ETR': 'EEPROM Transfer Request',
    'CSR': 'CSR Event Type',
    'HCM': 'Humidifier Operating Mode',
    'HOS': 'Humidifier Operating State',
    'HTB': 'Heated Tube Detected',
    'HUM': 'Humidifier Detected',
    'MST': 'Mask Status',
    'QCS': 'Cell Signal Strength',
    'QGI': 'Module Group',
    'QNC': 'Network Connection',
    'ROP': 'Run Mode Request',
    'ROT': 'Rotary Encoder Position',
    'RSS': 'Calibration Serial Request/Reply',
    'ZRM': 'Run Mode',
    'ZRP': 'Is Ramping',

    'ATO': 'Activity Timeout',
    'BLE': 'Bootloader Error',
    'MID': 'Metadata ID',
    'RID': 'Region ID',
    'VID': 'Variant ID',
    'NOC': 'Occurrence Count',
    'AER': 'App Error Origin',
    'DCR': 'Record CRC',

    'AHI': 'AHI',
    'AIS': 'AI',
    'CLI': 'Central AI',
    'CSD': 'CSR Duration',
    'HIS': 'Hypopnea Index',
    'OPI': 'Obstructive AI',
    'RIN': 'RERA Index',
    'UAI': 'Unknown AI',

    'AEP': 'Avg EPR Pressure',
    'AIP': 'Avg Bilevel Pressure',
    'ATP': 'AutoSet Pressure',
    'BP5': 'Blower Pressure P5',
    'BP9': 'Blower Pressure P95',
    'CPR': 'Calibration Pressure Setpoint',
    'HDR': 'Hose Drop',
    'MAP': 'Avg Mask Pressure',
    'MKE': 'EPR Pressure',
    'MKF': 'Filtered Mask Pressure',
    'MKI': 'Bilevel Mask Pressure',
    'MKP': 'Mask Pressure',
    'MSP': 'Median Pressure',
    'PE9': 'EPAP P95',
    'PEA': 'EPAP Max',
    'PEM': 'EPAP Median',
    'PI9': 'IPAP P95',
    'PIA': 'IPAP Max',
    'PIM': 'IPAP Median',
    'PM9': 'Pressure P95',
    'PMA': 'Pressure Max',
    'SPP': 'Set Pressure (runtime)',
    'TEP': 'Target EPAP',
    'TIP': 'Target IPAP',
    'LRP': 'Avg Low-Res Therapy Pressure',
    'LRE': 'Avg Low-Res EPR Pressure',

    'AFL': 'Avg Blower Flow',
    'BFF': 'Blower Flow Filtered',
    'BFM': 'Avg Blower Flow Median',
    'DFL': 'Differential Flow',
    'FFL': 'Fuzzy Flow Limit',
    'MV5': 'Minute Vent 5-Breath',
    'MVT': 'Mean Minute Vent',
    'RF5': 'Resp Flow P5',
    'RF9': 'Resp Flow P95',
    'RFL': 'Resp Flow',
    'VT9': 'Minute Vent P95',
    'VTA': 'Minute Vent Max',
    'VTM': 'Minute Vent Median',

    'LK7': 'Leak P70',
    'LK9': 'Leak P95',
    'LKF': 'Filtered Mask Leak',
    'LKM': 'Leak Median',
    'LKP': 'Leak (Hi-Res)',
    'LMX': 'Leak Max',
    'LYK': 'Mask Leak',

    'ATI': 'Avg Tidal Volume',
    'TDD': 'Tidal Volume 5-Breath',
    'TID': 'Tidal Volume',
    'TV9': 'Tidal Volume P95',
    'TVA': 'Tidal Volume Max',
    'TVM': 'Tidal Volume Median',

    'RR1': 'Resp Rate (realtime)',
    'RR9': 'Resp Rate P95',
    'RRA': 'Resp Rate Max',
    'RRM': 'Resp Rate Median',
    'RRR': 'Resp Rate (Hi-Res)',
    'SNI': 'Snore Index',

    'HRR': 'Heart Rate Raw',
    'HRS': 'Heart Rate Status',
    'HRT': 'Heart Rate',
    'NVS': 'Oximeter SW Version',
    'OXS': 'Oximetry Sequence',
    'SAO': 'SpO2',
    'SAR': 'SpO2 Raw',
    'SAS': 'SpO2 Status',
    'SAU': 'SpO2 Minutes Under Threshold',
    'SAV': 'Avg SpO2',
    'SO9': 'SpO2 P95',
    'SOM': 'SpO2 Median',
    'SOX': 'SpO2 Max',

    'ABH': 'Ambient Humidity',
    'ABM': 'Ambient Humidity Median',
    'HBP': 'Heated Tube PWM',
    'HHM': 'Humidifier Plate Temp Median',
    'HPM': 'Humidifier PWM Median',
    'HPT': 'Humidifier Plate Temp',
    'HTM': 'Heated Tube Temp Median',
    'HTT': 'Heated Tube Temp',
    'HUP': 'Humidifier PWM',
    'PPA': 'Plate Power Applied',
    'TPA': 'Tube Power Applied',
    'TPM': 'Heated Tube PWM Median',

    'CED': 'Compliance Erase Date',
    'FBD': 'First Breath Day',
    'FTD': 'First Therapy Day',
    'LSD': 'Current Session Date',
    'OFT': 'Mask Off Time',
    'OND': 'Mask On Duration',
    'ONT': 'Mask On Time',
    'PHM': 'Patient Hours',
    'THD': 'Therapy Duration',
    'MSE': 'Mask Events Count',

    'CET': 'CSR Event Time',
    'CSZ': 'CSR Zero Duration',
    'DUR': 'Apnea Duration',
    'ETI': 'Event Time',

    'SYC': 'Climate Control Error',
    'SYH': 'Heated Tube Error',
    'SYS': 'System Error',
    'SYT': 'System Error Two',
    'TYS': 'Transient System Error',

    'QCD': 'Cell Signal',
    'QCO': 'Module Operator',
    'QCV': 'Module Service',
    'QSI': 'Module Serial Number',
    'QTI': 'Module Type',
    'QVI': 'Module SW Version',

    'FLZ': 'Flow Zero',
    'FLG': 'Flow Gain',
    'PZH': 'Pressure Zero',
    'PSH': 'Pressure Gain',

    'AIE': 'Avg I:E Ratio [%]',
    'IER': 'I:E Ratio [%]',
    'IE9': 'I:E Ratio P95 [%]',
    'IEA': 'I:E Ratio Max [%]',
    'IEM': 'I:E Ratio Median [%]',

    'INT': 'Inspiration Time [s]',
    'EXT': 'Expiration Time [s]',
    'IN5': 'Inspiration Time 5-Breath [s]',
    'EX5': 'Expiration Time 5-Breath [s]',
    'ISM': 'Insp Time Median [s]',
    'IS9': 'Insp Time P95 [s]',
    'ISA': 'Insp Time Max [s]',
    'MIS': 'Mean Insp Time [s]',

    'TCV': 'Trigger/Cycle Event',
    'VCR': 'Spont Cycle Ratio [%]',
    'TGT': 'Target Ventilation [L/min]',
    'MTT': 'Mean Target Minute Vent [L/min]',
    'VA9': 'Target Vent P95 [L/min]',
    'VAA': 'Target Vent Max [L/min]',
    'VAM': 'Target Vent Median [L/min]',
    'BRR': 'Backup Resp Rate',
    'VSR': 'Spont Trigger Ratio',
    'ZSE': 'Saved System Error',
}

# Variable scaling metadata from ResScan protocol definition (M36)
# Format: (scale_divisor, decimal_places, unit_string)
# Raw value ÷ scale_divisor = display value.  decimal_places for formatting.
# Only includes variables with non-trivial scaling.
VAR_SCALE = {
    # Pressures: raw value / 50
    'IPC': (50, 1, 'cmH2O'), 'STP': (50, 1, 'cmH2O'), 'MPA': (50, 1, 'cmH2O'),
    'MPI': (50, 1, 'cmH2O'), 'STU': (50, 1, 'cmH2O'), 'IPP': (50, 1, 'cmH2O'),
    'EPP': (50, 1, 'cmH2O'), 'EPS': (50, 1, 'cmH2O'), 'EEP': (50, 1, 'cmH2O'),
    'MNS': (50, 1, 'cmH2O'), 'MXS': (50, 1, 'cmH2O'), 'EAI': (50, 1, 'cmH2O'),
    'EAX': (50, 1, 'cmH2O'), 'ANS': (50, 1, 'cmH2O'), 'AXS': (50, 1, 'cmH2O'),
    'EPI': (50, 1, 'cmH2O'), 'WPM': (50, 1, 'cmH2O'), 'WPA': (50, 1, 'cmH2O'),
    'MXI': (50, 1, 'cmH2O'), 'MNE': (50, 1, 'cmH2O'), 'SPT': (50, 1, 'cmH2O'),
    'EAS': (50, 1, 'cmH2O'), 'STE': (50, 1, 'cmH2O'), 'STV': (50, 1, 'cmH2O'),
    'IVS': (50, 1, 'cmH2O'),
    'MKP': (50, 1, 'cmH2O'), 'MKF': (50, 1, 'cmH2O'), 'MKI': (50, 1, 'cmH2O'),
    'MKE': (50, 1, 'cmH2O'), 'MAP': (50, 1, 'cmH2O'), 'SPP': (50, 1, 'cmH2O'),
    'TEP': (50, 1, 'cmH2O'), 'TIP': (50, 1, 'cmH2O'), 'ATP': (50, 1, 'cmH2O'),
    'AEP': (50, 1, 'cmH2O'), 'AIP': (50, 1, 'cmH2O'), 'HDR': (50, 1, 'cmH2O'),
    'MSP': (50, 1, 'cmH2O'), 'PM9': (50, 1, 'cmH2O'), 'PMA': (50, 1, 'cmH2O'),
    'BP5': (50, 1, 'cmH2O'), 'BP9': (50, 1, 'cmH2O'),
    'BPR': (50, 1, 'cmH2O'), 'CPR': (50, 1, 'cmH2O'),
    'PI9': (50, 1, 'cmH2O'), 'PIA': (50, 1, 'cmH2O'), 'PIM': (50, 1, 'cmH2O'),
    'PE9': (50, 1, 'cmH2O'), 'PEA': (50, 1, 'cmH2O'), 'PEM': (50, 1, 'cmH2O'),
    'EPR': (50, 0, 'cmH2O'),
    # Low-res pressure: raw / 5
    'LRP': (5, 1, 'cmH2O'), 'LRE': (5, 1, 'cmH2O'),
    # Tube temp: raw / 10
    'HTS': (10, 0, '°C'), 'HTF': (10, 0, '°F'),
    'HPT': (10, 0, '°C'), 'HHM': (10, 0, '°C'),
    'HTT': (10, 0, '°C'), 'HTM': (10, 0, '°C'),
    # Flow: raw / 500
    'RFL': (500, 2, 'L/s'), 'BFF': (500, 2, 'L/s'), 'DFL': (500, 2, 'L/s'),
    'RF9': (500, 2, 'L/s'), 'RF5': (500, 2, 'L/s'), 'BFL': (500, 2, 'L/s'),
    # Calibration gains
    'PSH': (4096, 4, ''), 'FLG': (4095, 4, ''),
    # Leak: raw / 50
    'LK9': (50, 2, 'L/s'), 'LKF': (50, 2, 'L/s'), 'LKM': (50, 2, 'L/s'),
    'LKP': (50, 2, 'L/s'), 'LMX': (50, 2, 'L/s'), 'LYK': (50, 2, 'L/s'),
    'LK7': (50, 2, 'L/s'),
    # Blower flow: raw / 100
    'AFL': (100, 2, 'L/min'), 'BFM': (100, 2, 'L/min'),
    # Minute ventilation: raw / 8
    'MV5': (8, 1, 'L/min'), 'MVT': (8, 1, 'L/min'),
    'VT9': (8, 1, 'L/min'), 'VTA': (8, 1, 'L/min'), 'VTM': (8, 1, 'L/min'),
    # Resp rate: raw / 5
    'RR1': (5, 1, 'bpm'), 'RR9': (5, 1, 'bpm'), 'RRA': (5, 1, 'bpm'),
    'RRM': (5, 1, 'bpm'), 'RRR': (5, 0, 'bpm'),
    # Tidal volume: raw / 50
    'ATI': (50, 2, 'L'), 'TDD': (50, 2, 'L'), 'TID': (50, 2, 'L'),
    'TV9': (50, 2, 'L'), 'TVA': (50, 2, 'L'), 'TVM': (50, 2, 'L'),
    # Snore: raw / 50
    'SNI': (50, 2, ''),
    # AHI-family: raw / 10
    'AHI': (10, 1, '/hr'), 'AIS': (10, 1, '/hr'), 'HIS': (10, 1, '/hr'),
    'CLI': (10, 1, '/hr'), 'OPI': (10, 1, '/hr'), 'UAI': (10, 1, '/hr'),
    'RIN': (10, 1, '/hr'),
    # Fuzzy flow limit: raw / 100
    'FFL': (100, 2, ''),
    # Power applied: raw / 100
    'PPA': (100, 0, '%'), 'TPA': (100, 0, '%'),
    # Insp/exp timing (bilevel): raw / 50 = seconds
    'INT': (50, 1, 's'), 'EXT': (50, 1, 's'), 'IN5': (50, 1, 's'), 'EX5': (50, 1, 's'),
    'ISM': (50, 1, 's'), 'IS9': (50, 1, 's'), 'ISA': (50, 1, 's'), 'MIS': (50, 1, 's'),
    # Spont cycle ratio: raw / 2 = %
    'VCR': (2, 1, '%'),
    # Target ventilation (ASV): raw / 8 = L/min
    'TGT': (8, 1, 'L/min'), 'MTT': (8, 1, 'L/min'),
    'VA9': (8, 1, 'L/min'), 'VAA': (8, 1, 'L/min'), 'VAM': (8, 1, 'L/min'),
}

# Enum option labels from ResScan metadata (M36 V39), plus firmware-traced
# service selectors where noted.
# Values are {int_value: 'label'}
ENUM_OPTIONS = {
    'MOP': {0: 'CPAP', 1: 'AutoSet', 2: 'APAP', 3: 'S', 4: 'ST', 5: 'T',
            6: 'VAuto', 7: 'ASV', 8: 'ASVAuto', 9: 'iVAPS', 10: 'PAC', 11: 'AutoSet Her'},
    'LAN': {0: 'English', 1: 'French', 2: 'German', 3: 'Italian', 4: 'Spanish (EU)',
            5: 'Spanish (US)', 6: 'Portuguese (EU)', 7: 'Portuguese (US)', 8: 'Dutch',
            9: 'Swedish', 10: 'Danish', 11: 'Norwegian', 12: 'Finnish', 13: 'Japanese',
            14: 'Russian', 15: 'Turkish', 16: 'Chinese (Trad)', 17: 'Chinese (Simp)',
            18: 'Polish', 19: 'Japanese (KN)', 20: 'Czech'},
    'MSK': {0: 'Pillows', 1: 'Full Face', 2: 'Nasal', 3: 'Pediatric'},
    'TBT': {0: 'SlimLine', 1: 'Standard', 2: '3m'},
    'REM': {0: 'Clinical', 1: 'Compliance', 2: 'Error Log', 3: 'All', 4: 'None'},
    'ACC': {0: 'Plus', 1: 'On'},
    'ABF': {0: 'No', 1: 'Yes'},
    'AFC': {0: 'Standard', 1: 'Soft'},
    'CCO': {0: 'Auto', 1: 'Manual'},
    'HMX': {0: 'Off', 1: 'On'},
    'HTX': {0: 'Off', 1: 'On', 2: 'Auto'},
    'TMU': {0: '°C', 1: '°F'},
    'QFC': {0: 'Off', 1: 'On'},
    'LCA': {0: 'Off', 1: 'On'},
    'EPA': {0: 'Off', 1: 'On'},
    'EPX': {0: 'Off', 1: 'On'},
    'EPT': {0: 'Ramp Only', 1: 'Full Time'},
    'MFT': {0: 'Off', 1: 'On'},
    'SST': {0: 'Off', 1: 'On'},
    'RMA': {0: 'Off', 1: 'On', 2: 'Auto'},
    'RPF': {0: 'Off', 1: 'On'}, 'RPO': {0: 'Off', 1: 'On'},
    'RPH': {0: 'Off', 1: 'On'}, 'RPW': {0: 'Off', 1: 'On'},
    'RXF': {0: 'Off', 1: 'On'}, 'RXM': {0: 'Off', 1: 'On'},
    'RXH': {0: 'Off', 1: 'On'}, 'RXW': {0: 'Off', 1: 'On'},
    'ZRM': {0: 'Reset', 1: 'Standby', 2: 'Backup', 3: 'Reset Compliance',
            4: 'Therapy', 5: 'Mask Fit', 6: 'Calibration', 7: 'System Error',
            8: 'Power Save', 9: 'Learn Target', 10: 'Upgrade', 11: 'Upgrade Prep'},
    'ROP': {0: 'Standby', 1: 'Normal', 2: 'Power Recovery', 3: 'Power Save',
            4: 'Calibration', 5: 'Upgrade'},
    # Firmware-traced CAL service selectors. Only identified values are listed.
    'CAL': {0x0001: 'Pressure Controller',
            0x0005: 'LCD/display test',
            0x0006: 'Pressure loop + unidentified KPD/KPT controls',
            0x0007: 'Pressure controller + ROT status',
            0x000A: 'SDT status bit collector',
            0x000B: 'EEPROM/SD maintenance',
            0x000C: 'RSS transport test',
            0x0010: 'SD card read/write self-test',
            0x0012: 'Serial/comm test'},
    # Firmware-traced CAL=000B command selector.
    'ETR': {0x0000: 'Idle',
            0x0001: 'Zero EEPROM logical pages',
            0x0002: 'Format eep:0 FAT filesystem',
            0x0003: 'Backup raw EEPROM to SD EEPROM.dat',
            0x0004: 'Restore raw EEPROM from SD EEPROM.dat',
            0x0005: 'Copy eep:0 tree to SD',
            0x0006: 'Copy SD EEPROM table to eep:0'},
    'BLL': {0: 'Application', 1: 'Bootloader'},
    'BLS': {0: 'In Application', 1: 'In Bootloader', 2: 'In BL (Invalid App)'},
    'AET': {0: 'None', 1: 'Hypopnea', 2: 'Central', 3: 'Obstructive', 4: 'Apnea', 5: 'Arousal'},
    'HTB': {0: 'None', 1: '15mm', 2: '19mm'},
    'HUM': {0: 'End Cap', 1: 'Internal', 2: 'External'},
    'HOS': {0: 'None', 1: 'Off', 2: 'On'},
    'HCM': {0: 'None', 1: 'Manual', 2: 'Climate'},
    'QGI': {0: 'None', 1: 'Cellular'},
    'QCS': {0: 'None', 1: '1 Bar', 2: '2 Bars', 3: '3 Bars', 4: '4 Bars', 5: '5 Bars'},
    'QNC': {0: 'No Network', 1: 'Connected'},
    'ZRP': {0: 'No', 1: 'Yes'},
    'CSR': {0: 'None', 1: 'CSR Start', 2: 'CSR End'},
    'MST': {0: 'On', 1: 'Off', 2: 'Debounce'},
    'TCV': {0: 'None', 1: 'Spont Trig', 2: 'TeMax Trig', 3: 'TeMin Trig',
            4: 'Timed Trig', 5: 'Spont Cycle', 6: 'TiMax Cycle', 7: 'TiMin Cycle',
            8: 'Timed Cycle'},
}


CALIBRATION_ROP = '0004'
CALIBRATION_ZRM = '0006'
EEPROM_CAL = '000B'

EEPROM_ACTIONS = {
    'format-eep-fat': {
        'etr': '0002',
        'label': 'format eep:0 FAT filesystem via ERE backend service',
        'paths': ['eep:0:'],
        'requires_yes': True,
        'requires_really': True,
        'confirm_message': 'formats/reinitializes the EEPROM-backed eep:0 FAT filesystem',
        'warnings': [
            'operation destroys unit specific data (serial, calbration...)',
        ],
    },
    'sd-backup-raw': {
        'etr': '0003',
        'label': 'backup raw EEPROM to SD EEPROM.dat',
        'paths': ['mmc:0:EEPROM\\EEPROM.dat'],
        'requires_yes': False,
        'requires_really': False,
        'warnings': [],
    },
    'sd-restore-raw': {
        'etr': '0004',
        'label': 'restore raw EEPROM from SD EEPROM.dat',
        'paths': ['mmc:0:EEPROM\\EEPROM.dat'],
        'requires_yes': True,
        'requires_really': False,
        'confirm_message': 'writes raw EEPROM from mmc:0:EEPROM\\EEPROM.dat',
        'warnings': [],
    },
    'sd-export-tree': {
        'etr': '0005',
        'label': 'copy eep:0 tree to SD',
        'paths': ['eep:0:', 'mmc:0:EEPROM'],
        'requires_yes': False,
        'requires_really': False,
        'warnings': [],
    },
    'sd-import-tree': {
        'etr': '0006',
        'label': 'copy fixed SD EEPROM tree paths to eep:0',
        'paths': [
            'mmc:0:EEPROM -> eep:0:',
            'mmc:0:EEPROM\\DATALOG -> eep:0:DATALOG',
            'mmc:0:EEPROM\\ERRORLOG -> eep:0:ERRORLOG',
            'mmc:0:EEPROM\\SETTINGS -> eep:0:SETTINGS',
        ],
        'requires_yes': True,
        'requires_really': False,
        'confirm_message': 'writes fixed mmc:0:EEPROM paths back to eep:0',
        'warnings': [],
    },
    'erase-logical-pages': {
        'etr': '0001',
        'label': 'zero EEPROM logical pages',
        'paths': [],
        'requires_yes': True,
        'requires_really': True,
        'confirm_message': 'zeroes EEPROM logical pages',
        'warnings': [
            'operation destroys unit specific data (serial, calbration...)',
        ],
    },
}


INFO_VARS = ['BID', 'SID', 'CID', 'PCB', 'SRN', 'PCD', 'PNA']


def format_value(name, raw_str):
    """Return a human-readable annotation for a raw hex value, or None."""
    if raw_str is None:
        return None
    raw_str = raw_str.strip()
    if name in ENUM_OPTIONS:
        try:
            val = int(raw_str, 16)
            label = ENUM_OPTIONS[name].get(val)
            if label:
                return label
        except ValueError:
            pass
    if name in VAR_SCALE:
        try:
            val = int(raw_str, 16)
            scale, decimals, unit = VAR_SCALE[name]
            if val > 0x7FFF and scale in (50, 5, 10, 500, 100, 8):
                val = val - 0x10000
            display = val / scale
            unit_str = f" {unit}" if unit else ""
            return f"{display:.{decimals}f}{unit_str}"
            #return f"{display:.{decimals}f}"
        except (ValueError, ZeroDivisionError):
            pass
    return None


def encode_value(name, user_str):
    """Convert a human-readable value to raw hex for the UART protocol.
    Returns hex string (e.g. '01F4') or None if variable has no known encoding.

    Raises ValueError if the variable has known encoding but the input is invalid.
    """
    user_str = user_str.strip()

    if name in ENUM_OPTIONS:
        lower = user_str.lower()
        for val, label in ENUM_OPTIONS[name].items():
            if label.lower() == lower:
                return f'{val:04X}'
        raw_hex = lower[2:] if lower.startswith('0x') else lower
        if raw_hex and all(c in '0123456789abcdef' for c in raw_hex):
            val = int(raw_hex, 16)
            if val in ENUM_OPTIONS[name]:
                return f'{val:04X}'
        valid = ', '.join(f'{val:04X}={label}' for val, label in ENUM_OPTIONS[name].items())
        raise ValueError(f"unknown option '{user_str}' for {name} (valid: {valid})")

    if name in VAR_SCALE:
        try:
            fval = float(user_str)
        except ValueError:
            raise ValueError(f"'{user_str}' is not a number for {name}")
        scale, decimals, unit = VAR_SCALE[name]
        raw = int(round(fval * scale))
        if raw < 0:
            raw = raw + 0x10000
        return f'{raw & 0xFFFF:04X}'

    return None


BDD_RATES = {57600: '0000', 115200: '0001', 460800: '0002'}
BDD_RATES_ORDERED = [460800, 115200, 57600]
PROBE_RATES = [57600, 115200, 460800]


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021 if crc & 0x8000 else crc << 1) & 0xFFFF
    return crc

def escape_payload(data: bytes) -> bytes:
    return data.replace(b'U', b'UU')

def build_frame(frame_type: str, payload: bytes) -> bytes:
    escaped = escape_payload(payload)
    frame_len = 1 + 1 + 3 + len(escaped) + 4
    pre_crc = b'U' + frame_type.encode() + f'{frame_len:03X}'.encode() + escaped
    crc = crc16_ccitt(pre_crc)
    return pre_crc + f'{crc:04X}'.encode()

def build_q_frame(cmd: str) -> bytes:
    return build_frame('Q', cmd.encode())

def parse_responses(data: bytes) -> list:
    responses = []
    i = 0
    while i < len(data):
        if data[i:i+1] == b'U' and i+1 < len(data) and data[i+1:i+2] != b'U':
            try:
                ft = chr(data[i+1])
                if ft in 'EFKLOPQRTf':
                    length = int(data[i+2:i+5], 16)
                    if i + length <= len(data):
                        raw_payload = data[i+5:i+length-4]
                        payload = raw_payload.replace(b'UU', b'U')
                        responses.append({'type': ft, 'payload': payload})
                        i += length
                        continue
            except (ValueError, IndexError):
                pass
        i += 1
    return responses

def read_responses(ser, timeout=1.0, multi_frame=False):
    old_timeout = ser.timeout
    if multi_frame:
        ser.timeout = 0.1
        trail_wait, trail_ext = 0.3, 0.1
    else:
        ser.timeout = 0.02
        trail_wait, trail_ext = 0.02, 0.02
    data = b''
    deadline = time.time() + timeout
    while time.time() < deadline:
        chunk = ser.read(4096)
        if chunk:
            data += chunk
            trail_deadline = time.time() + trail_wait
            while time.time() < trail_deadline:
                chunk = ser.read(4096)
                if chunk:
                    data += chunk
                    trail_deadline = time.time() + trail_ext
            break
    ser.timeout = old_timeout
    return data, parse_responses(data)

def send_cmd(ser, cmd_str, timeout=0.5, quiet=False, no_response=False, multi_frame=False):
    if getattr(ser, 'text_mode', False):
        resp_text = ser.send_text_cmd(cmd_str, timeout=timeout)
        if not quiet and resp_text:
            print(f"  [R] {resp_text}")
        # Wrap in compatible format: raw bytes + response list
        if resp_text:
            payload = resp_text.encode('ascii', errors='replace')
            return payload, [{'type': 'R', 'payload': payload}]
        return b'', []

    ser.reset_input_buffer()
    ser.write(build_q_frame(cmd_str))
    ser.flush()
    if no_response:
        return b'', []
    mf = multi_frame or cmd_str.startswith('G F &')
    raw, responses = read_responses(ser, timeout=timeout, multi_frame=mf)
    if not quiet:
        for r in responses:
            print(f"  [{r['type']}] {r['payload'].decode('ascii', errors='replace')}")
    return raw, responses

def sync_uart(ser):
    ser.reset_input_buffer()
    #ser.write(b'\x55' * 128)
    ser.flush()
    time.sleep(0.05)
    ser.reset_input_buffer()


def probe_baud(ser):
    for rate in PROBE_RATES:
        ser.baudrate = rate
        ser.reset_input_buffer()
        time.sleep(0.05)
        _, resp = send_cmd(ser, "G S #BID", timeout=0.3, quiet=True)
        if any(b'BID' in r['payload'] for r in resp):
            return rate
    return None

def switch_baud(ser, target, quiet=False):
    if target not in BDD_RATES or ser.baudrate == target:
        return ser.baudrate == target
    old = ser.baudrate
    if not quiet:
        print(f"[*] Switching baud: {old} -> {target} (BDD {BDD_RATES[target]})...")
    send_cmd(ser, f"P S #BDD {BDD_RATES[target]}", timeout=0.5, quiet=True, no_response=True)
    time.sleep(0.3)
    read_responses(ser, timeout=0.5)
    ser.baudrate = target
    sync_uart(ser)
    _, resp = send_cmd(ser, "G S #BID", timeout=0.5, quiet=True)
    if any(b'BID' in r['payload'] for r in resp):
        if not quiet:
            print(f"[+] Running at {target} baud")
        return True
    if not quiet:
        print(f"[!] No response at {target}, reverting")
    ser.baudrate = old
    sync_uart(ser)
    return False

def negotiate_best_baud(ser):
    for rate in BDD_RATES_ORDERED:
        if rate == ser.baudrate:
            return rate
        if switch_baud(ser, rate):
            return rate
    return ser.baudrate


class EcpFileDevice:
    """Settings.ecp file backend used as a writeable pseudo-device."""

    ecp_file = True

    def __init__(self, portspec):
        self.path = self._resolve_path(portspec)
        self.crc_path = self.path.with_name('Settings.crc')
        self.dirty = False

    @staticmethod
    def _resolve_path(portspec):
        raw = portspec[4:]
        if not raw:
            raise ValueError("ecp: path is empty")
        path = Path(raw)
        if path.exists() and path.is_file():
            return path
        return path / 'Settings.ecp'

    def _read_bytes(self):
        if not self.path.exists():
            return b''
        return self.path.read_bytes()

    def _read_assignments(self):
        values = {}
        text = self._read_bytes().decode('ascii', errors='replace')
        for line in text.splitlines():
            parts = line.strip().split(None, 3)
            if len(parts) != 4:
                continue
            if parts[0].upper() != 'P' or parts[1].upper() != 'S':
                continue
            if not parts[2].startswith('#'):
                continue
            values[parts[2][1:].upper()] = parts[3].strip()
        return values

    def get_var(self, name):
        value = self._read_assignments().get(name.upper())
        if value is None:
            return None, None
        return 'R', value

    def set_var(self, name, value):
        if '\r' in value or '\n' in value:
            return 'E', 'newline in value'
        line = f"P S #{name.upper()} {value}"
        try:
            encoded = line.encode('ascii')
        except UnicodeEncodeError:
            return 'E', 'non-ascii value'

        data = bytearray(self._read_bytes())
        if data and not (data.endswith(b'\n') or data.endswith(b'\r')):
            data.extend(b'\r\n')
        data.extend(encoded)
        data.extend(b'\r\n')

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(bytes(data))
        self.dirty = True
        return 'R', value

    def update_crc(self):
        if not self.path.exists():
            return
        self.crc_path.write_bytes(
            (zlib.crc32(self.path.read_bytes()) & 0xFFFFFFFF).to_bytes(4, 'little'))
        self.dirty = False

    def close(self):
        if self.dirty:
            self.update_crc()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def get_var(ser, name):
    """Read a single variable. Returns (frame_type, value_str).
    R-frame: ('R', value).  E-frame: ('E', error_code).  No response: (None, None)."""
    if getattr(ser, 'ecp_file', False):
        return ser.get_var(name)
    _, resp = send_cmd(ser, f"G S #{name}", timeout=1, quiet=True)
    for r in resp:
        payload = r['payload'].decode('ascii', errors='replace')
        if '=' in payload:
            return (r['type'], payload.split('=', 1)[1].strip())
    return (None, None)

def set_var(ser, name, value):
    """Write a single variable. Returns (frame_type, value_str).
    R-frame: ('R', echo_value).  E-frame: ('E', error_code).  No response: (None, None)."""
    if getattr(ser, 'ecp_file', False):
        return ser.set_var(name, value)
    _, resp = send_cmd(ser, f"P S #{name} {value}", timeout=0.5, quiet=True)
    for r in resp:
        payload = r['payload'].decode('ascii', errors='replace')
        if '=' in payload:
            return (r['type'], payload.split('=', 1)[1].strip())
    return (None, None)

def get_var_caps(ser, name):
    """Read variable capabilities. Returns (frame_type, value_str)."""
    if getattr(ser, 'ecp_file', False):
        return None, None
    _, resp = send_cmd(ser, f"G C #{name}", timeout=0.5, quiet=True)
    for r in resp:
        payload = r['payload'].decode('ascii', errors='replace')
        if '=' in payload:
            return (r['type'], payload.split('=', 1)[1].strip())
    return (None, None)


def require_var_result(name, frame_type, value, action):
    """Return an uppercase R-frame value or raise RuntimeError."""
    if frame_type == 'R' and value is not None:
        return value.strip().upper()
    if frame_type == 'E':
        raise RuntimeError(f"{name}: device returned error {value} while {action}")
    raise RuntimeError(f"{name}: no response while {action}")


def wait_var_value(ser, name, expected, timeout, interval=0.5):
    """Poll a variable until it reaches expected. Returns (ok, last_value)."""
    expected = expected.upper()
    deadline = time.time() + timeout
    last = None
    tty = sys.stdout.isatty()
    last_status_len = 0
    while True:
        ft, val = get_var(ser, name)
        if ft == 'R' and val is not None:
            last = val.strip().upper()
            if last == expected:
                msg = f"  {name}={expected} confirmed."
                if tty:
                    padding = ' ' * max(0, last_status_len - len(msg))
                    sys.stdout.write(f"\r{msg}{padding}\n")
                    sys.stdout.flush()
                else:
                    print(msg)
                return True, last
        elif ft == 'E':
            last = f"ERROR {val}"
        else:
            last = "no response"

        msg = f"  Waiting for {name}={expected}; current {last}..."
        if tty:
            padding = ' ' * max(0, last_status_len - len(msg))
            sys.stdout.write(f"\r{msg}{padding}")
            sys.stdout.flush()
            last_status_len = len(msg)
        else:
            print(msg)

        remaining = deadline - time.time()
        if remaining <= 0:
            if tty:
                sys.stdout.write("\n")
                sys.stdout.flush()
            return False, last
        time.sleep(min(interval, remaining))


def enter_calibration_mode(ser, timeout):
    """Request calibration run mode and wait for ZRM=0006."""
    zrm = require_var_result('ZRM', *get_var(ser, 'ZRM'), 'reading')
    if zrm == CALIBRATION_ZRM:
        print(f"[*] Already in calibration mode: ZRM={zrm}")
        return

    ann = format_value('ZRM', zrm)
    ann_str = f" ({ann})" if ann else ""
    print(f"[*] Current run mode: ZRM={zrm}{ann_str}")
    print(f"[*] Requesting calibration mode: ROP={CALIBRATION_ROP}")
    require_var_result('ROP', *set_var(ser, 'ROP', CALIBRATION_ROP),
                       f'writing {CALIBRATION_ROP}')
    ok, last = wait_var_value(ser, 'ZRM', CALIBRATION_ZRM, timeout)
    if not ok:
        raise RuntimeError(f"ZRM did not reach {CALIBRATION_ZRM}; last value was {last}")


def restore_calibration_state(ser, original_cal, original_rop):
    """Best-effort restore of selector variables saved before calibration utilities."""
    print(f"[*] Restoring CAL={original_cal}, ROP={original_rop}")
    errors = 0
    try:
        require_var_result('CAL', *set_var(ser, 'CAL', original_cal),
                           f'writing {original_cal}')
    except RuntimeError as exc:
        print(f"  [!] Failed to restore CAL: {exc}")
        errors += 1
    try:
        require_var_result('ROP', *set_var(ser, 'ROP', original_rop),
                           f'writing {original_rop}')
    except RuntimeError as exc:
        print(f"  [!] Failed to restore ROP: {exc}")
        errors += 1

    ft, zrm = get_var(ser, 'ZRM')
    if ft == 'R' and zrm is not None:
        zrm = zrm.strip().upper()
        ann = format_value('ZRM', zrm)
        ann_str = f" ({ann})" if ann else ""
        print(f"  ZRM={zrm}{ann_str}")
    return errors == 0


def check_eeprom_confirmations(action, yes=False, really=False):
    """Validate EEPROM action confirmation flags before opening or writing."""
    spec = EEPROM_ACTIONS.get(action)
    if spec is None:
        print(f"[!] Unknown EEPROM action: {action}")
        return False
    if (spec['requires_yes'] and not yes) or (spec['requires_really'] and not really):
        flag_text = '--yes --really' if spec['requires_really'] and yes else '--yes'
        print(f"[!] {action} {spec['confirm_message']}. Re-run with {flag_text} to confirm.")
        return False
    return True


def resolve_groups(group_names):
    """Resolve group names/aliases to a list of variable names."""
    var_names = []
    for name in group_names:
        upper = name.upper()
        if upper in GROUP_ALIASES:
            for grp in GROUP_ALIASES[upper]:
                var_names.extend(GROUPS[grp])
        elif upper in GROUPS:
            var_names.extend(GROUPS[upper])
        elif upper in VAR_TO_GROUP:
            var_names.append(upper)
        else:
            # Treat as raw variable name - let the device decide
            var_names.append(upper)
    return var_names

def exclude_vars(var_names, exclude_groups=None, exclude_vars_list=None):
    """Remove variables by group or individual name."""
    excluded = set()
    if exclude_groups:
        for grp in exclude_groups:
            upper = grp.upper()
            if upper in GROUPS:
                excluded.update(GROUPS[upper])
            else:
                print(f"[!] Unknown group: {grp}")
    if exclude_vars_list:
        excluded.update(v.upper() for v in exclude_vars_list)
    return [v for v in var_names if v not in excluded]


def parse_name_value_pairs(items, command):
    if len(items) % 2:
        raise ValueError(f"{command} expects VAR VALUE pairs")
    return list(zip(items[0::2], items[1::2]))


def cmd_info(ser, verbose=False):
    print("[*] Device info:")
    for var in INFO_VARS:
        ft, val = get_var(ser, var)
        desc = VAR_DESC.get(var, '')
        desc_str = f"  ({desc})" if verbose and desc else ""
        if ft == 'R':
            print(f"  {var:4s} = {val}{desc_str}")
        elif ft == 'E':
            print(f"  {var:4s} = [E] {val}{desc_str}")
        else:
            print(f"  {var:4s} = (no response){desc_str}")

def cmd_get(ser, targets, verbose=False):
    """Get one or more variables/groups."""
    var_names = resolve_groups(targets)
    if var_names is None:
        return 1
    for name in var_names:
        ft, val = get_var(ser, name)
        grp = VAR_TO_GROUP.get(name, '-')
        desc = VAR_DESC.get(name, '')
        desc_str = f"({desc})" if verbose and desc else ""
        if ft == 'R':
            ann = format_value(name, val)
            ann_str = f"[{ann}] " if ann else ""
            sep = "# " if ann or desc_str else ""
            print(f"  [{grp}] {name:4s} = {val} {sep}{ann_str}{desc_str}")
        elif ft == 'E':
            print(f"  [{grp}] {name:4s} = {val} # ERROR {desc_str}")
        else:
            print(f"  [{grp}] {name:4s} = # NO-RESPONSE {desc_str}")
    return 0

def cmd_set(ser, pairs):
    """Set one or more variables using raw protocol values."""
    errors = 0
    for var_name, value in pairs:
        name = var_name.upper()
        grp = VAR_TO_GROUP.get(name, '-')
        _, old_val = get_var(ser, name)
        print(f"  [{grp}] {name} = {old_val} -> {value}")
        ft, resp = set_var(ser, name, value)
        if ft == 'R':
            _, new_val = get_var(ser, name)
            print(f"  [{grp}] {name} = {new_val} (confirmed)")
        elif ft == 'E':
            print(f"  [!] {name} = {resp} # ERROR")
            errors += 1
        else:
            print(f"  [!] {name} = # NO-RESPONSE")
            errors += 1
    return 0 if errors == 0 else 1


def cmd_setv(ser, pairs):
    """Set one or more variables using scaled/human-readable values."""
    encoded = []
    for var_name, value in pairs:
        name = var_name.upper()
        raw = encode_value(name, value)
        if raw is None:
            print(f"  [!] {name}: no known scaling or enum; use 'set' with raw value")
            return 1
        encoded.append((name, value, raw))

    errors = 0
    for name, value, raw in encoded:
        grp = VAR_TO_GROUP.get(name, '-')
        oft, old_val = get_var(ser, name)
        old_ann = format_value(name, old_val) if oft == 'R' else None
        old_str = f"{old_val} ({old_ann})" if old_ann else str(old_val)
        print(f"  [{grp}] {name}: {value} -> {raw}")
        ft, resp = set_var(ser, name, raw)
        if ft == 'R':
            _, new_val = get_var(ser, name)
            new_ann = format_value(name, new_val)
            new_str = f"{new_val} ({new_ann})" if new_ann else str(new_val)
            print(f"  [{grp}] {name} = {old_str} -> {new_str}")
        elif ft == 'E':
            print(f"  [!] {name} = {resp} # ERROR")
            errors += 1
        else:
            print(f"  [!] {name} = # NO-RESPONSE")
            errors += 1
    return 0 if errors == 0 else 1

def cmd_dump(ser, groups=None, exclude_groups=None, exclude_vars_list=None):
    """Dump variables to dict. Returns {group: {var: value}}."""
    if groups:
        var_names = resolve_groups(groups)
    else:
        var_names = resolve_groups(['all'])
    if var_names is None:
        return None

    var_names = exclude_vars(var_names, exclude_groups, exclude_vars_list)

    result = {}
    total = len(var_names)
    for i, name in enumerate(var_names):
        grp = VAR_TO_GROUP.get(name, 'UNK')
        ft, val = get_var(ser, name)
        if grp not in result:
            result[grp] = {}
        result[grp][name] = val if ft == 'R' else None
        sys.stdout.write(f"\r  Reading: {i+1}/{total} ({name})...")
        sys.stdout.flush()
    print(f"\r  Read {total} variables.              ")
    return result

def cmd_restore(ser, data, exclude_groups=None, exclude_vars_list=None, dry_run=False):
    """Restore variables from dump dict."""
    changes = []
    for grp in sorted(data.keys()):
        for name, value in sorted(data[grp].items()):
            if value is None:
                continue
            changes.append((grp, name, value))

    # exclusions
    excluded = set()
    if exclude_groups:
        for grp in exclude_groups:
            upper = grp.upper()
            if upper in GROUPS:
                excluded.update(GROUPS[upper])
    if exclude_vars_list:
        excluded.update(v.upper() for v in exclude_vars_list)

    changes = [(g, n, v) for g, n, v in changes if n not in excluded]

    if not changes:
        print("[!] No variables to restore.")
        return 1

    print(f"[*] Restoring {len(changes)} variables...")
    errors = 0
    for i, (grp, name, value) in enumerate(changes):
        _, current = get_var(ser, name)
        if current == value:
            sys.stdout.write(f"\r  {i+1}/{len(changes)} {name}: unchanged    ")
            sys.stdout.flush()
            continue

        if dry_run:
            print(f"\r  [DRY] [{grp}] {name}: {current} -> {value}")
            continue

        ft, resp = set_var(ser, name, value)
        if ft == 'R':
            sys.stdout.write(f"\r  {i+1}/{len(changes)} {name}: {current} -> {value}    ")
            sys.stdout.flush()
        else:
            err = f": {resp}" if resp else ""
            print(f"\r  [!] [{grp}] {name}: FAILED to set {value}{err}")
            errors += 1

    print(f"\r  Restore complete. {len(changes)} variables, {errors} errors.          ")
    return 0 if errors == 0 else 1

def cmd_list(groups=None):
    """List known variables with their groups and descriptions (offline, no device query)."""
    if groups:
        group_list = []
        for g in groups:
            upper = g.upper()
            if upper in GROUPS:
                group_list.append(upper)
            else:
                print(f"[!] Unknown group: {g}")
                return 1
    else:
        group_list = sorted(GROUPS.keys())

    for grp in group_list:
        vars_list = GROUPS[grp]
        grp_desc = GROUP_DESC.get(grp, '')
        header = f"  {grp} ({len(vars_list)} vars)"
        if grp_desc:
            header += f" — {grp_desc}"
        print(f"\n{header}:")
        for name in vars_list:
            desc = VAR_DESC.get(name, '')
            if desc:
                print(f"    {name:4s}  {desc}")
            else:
                print(f"    {name:4s}")

    if not groups:
        in_groups = set(v for vl in GROUPS.values() for v in vl)
        ungrouped = sorted(v for v in VAR_DESC if v not in in_groups)
        if ungrouped:
            print(f"\n  (ungrouped) ({len(ungrouped)} vars):")
            for name in ungrouped:
                print(f"    {name:4s}  {VAR_DESC[name]}")
    return 0

def cmd_caps(ser, targets=None, verbose=False):
    """Query variable limits/capabilities from device (G S # + G C #)."""
    if targets:
        group_list = []
        for g in targets:
            upper = g.upper()
            if upper in GROUPS:
                group_list.append(upper)
            else:
                # Any 2-4 char name — treat as single variable (known or not)
                group_list.append(('_single', upper))
    else:
        group_list = sorted(GROUPS.keys())

    def _query(name):
        vft, val = get_var(ser, name)
        cft, caps = get_var_caps(ser, name)
        desc = VAR_DESC.get(name, '')
        if vft == 'R':
            ann = format_value(name, val)
            val_str = f"{val} ({ann})" if ann else val
        elif vft == 'E':
            val_str = f"[E] {val}"
        else:
            val_str = "(no response)"
        caps_str = f"  caps: {caps}" if cft == 'R' else ""
        desc_str = f"  ({desc})" if verbose and desc else ""
        return f"{val_str}{caps_str}{desc_str}"

    for item in group_list:
        if isinstance(item, tuple) and item[0] == '_single':
            name = item[1]
            grp = VAR_TO_GROUP.get(name, '-')
            print(f"  [{grp}] {name:4s} = {_query(name)}")
        else:
            grp = item
            vars_list = GROUPS[grp]
            grp_desc = GROUP_DESC.get(grp, '')
            header = f"  {grp} ({len(vars_list)} vars)"
            if grp_desc:
                header += f" — {grp_desc}"
            print(f"\n{header}:")
            for name in vars_list:
                print(f"    {name:4s} = {_query(name)}")
    return 0


def cmd_calibration_eeprom(ser, action, timeout):
    """Run stock-firmware EEPROM/SD maintenance commands via CAL=000B and ETR."""
    spec = EEPROM_ACTIONS.get(action)

    print(f"[*] EEPROM action: {action} -> ETR={spec['etr']} ({spec['label']})")
    print("[*] Using stock firmware CAL=000B service; SD paths are device-side.")
    for warning in spec['warnings']:
        print(f"[!] {warning}")
    if spec['paths']:
        print("[*] Fixed firmware paths:")
        for path in spec['paths']:
            print(f"  {path}")

    original_cal = None
    original_rop = None
    safe_to_restore = True
    success = False

    try:
        original_cal = require_var_result('CAL', *get_var(ser, 'CAL'), 'reading')
        original_rop = require_var_result('ROP', *get_var(ser, 'ROP'), 'reading')
        print(f"[*] Saved CAL={original_cal}, ROP={original_rop}")

        enter_calibration_mode(ser, timeout)

        print(f"[*] Selecting EEPROM/SD maintenance service: CAL={EEPROM_CAL}")
        require_var_result('CAL', *set_var(ser, 'CAL', EEPROM_CAL),
                           f'writing {EEPROM_CAL}')

        etr = require_var_result('ETR', *get_var(ser, 'ETR'), 'reading')
        if etr != '0000':
            raise RuntimeError(f"ETR is {etr}, not idle; refusing to start another command")

        print(f"[*] Starting EEPROM command: ETR={spec['etr']}")
        require_var_result('ETR', *set_var(ser, 'ETR', spec['etr']),
                           f"writing {spec['etr']}")
        safe_to_restore = False

        ok, last = wait_var_value(ser, 'ETR', '0000', timeout, interval=1.0)
        if not ok:
            print(f"[!] Timed out waiting for ETR=0000; last ETR state was {last}")
        else:
            safe_to_restore = True
            print(f"[+] EEPROM action complete: {action}")
            success = True

    except RuntimeError as exc:
        print(f"[!] EEPROM action failed: {exc}")

    finally:
        if original_cal is not None and original_rop is not None:
            if safe_to_restore:
                if not restore_calibration_state(ser, original_cal, original_rop):
                    success = False
            else:
                print("[!] ETR did not return to 0000; leaving CAL/ROP unchanged.")
                print("    Inspect ETR/ERE before starting another EEPROM action.")

    return 0 if success else 1


def connect(ser, baud_arg):
    """Connect and probe or set baud rate. Returns True on success."""
    if getattr(ser, 'ecp_file', False):
        # ECP backend: nothing to connect to.
        return True
    if getattr(ser, 'text_mode', False):
        # Text mode: arbiter handles baud, just verify device responds
        print("[*] Verifying device (text mode)...")
        _, resp = send_cmd(ser, "G S #BID", timeout=1.0, quiet=True)
        if not any(b'BID' in r['payload'] for r in resp):
            print("[!] Device not responding")
            return False
        print("[+] Device responding via arbiter")
        return True

    if baud_arg == 'auto':
        print("[*] Probing device...")
        baud = probe_baud(ser)
        if not baud:
            print("[!] Device not responding at any known baud rate")
            return False
        print(f"[+] Device responding at {baud} baud")
        ser.baudrate = baud
    else:
        rate = int(baud_arg)
        ser.baudrate = rate
        _, resp = send_cmd(ser, "G S #BID", timeout=0.5, quiet=True)
        if not any(b'BID' in r['payload'] for r in resp):
            print(f"[!] No response at {rate} baud")
            return False
        print(f"[+] Device responding at {rate} baud")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='ResMed AirSense UART Configuration Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  info                          Show device identity
  get <var|group|all>           Read variables
  set <var> <value> [...]       Write one or more variables
  dump                          Dump all variables to JSON
  restore                       Restore variables from JSON
  list                          List known variables and descriptions (offline)
  caps                          Query variable limits from device
  calibration eeprom            Run stock-firmware EEPROM/SD maintenance

Groups: """ + ', '.join(sorted(GROUPS.keys())) + """

Examples:
  %(prog)s -p /dev/ttyACM0 info
  %(prog)s -p /dev/ttyACM0 get MGL
  %(prog)s -p /dev/ttyACM0 get SPT
  %(prog)s -p /dev/ttyACM0 set SPT 0001
  %(prog)s -p /dev/ttyACM0 set SPT 0001 EPR 0002
  %(prog)s -p /dev/ttyACM0 setv IPC 10.0            # 10.0 cmH2O -> 01F4
  %(prog)s -p /dev/ttyACM0 setv MOP AutoSet          # enum label -> 0001
  %(prog)s -p ecp:/media/RESMED/SETTINGS set PNA AirSense_10_airbreak
  %(prog)s -p /dev/ttyACM0 dump -o config.json
  %(prog)s -p /dev/ttyACM0 dump --groups MGL EGL -o therapy.json
  %(prog)s -p /dev/ttyACM0 restore -i config.json
  %(prog)s -p /dev/ttyACM0 restore -i config.json --exclude-groups BGL
  %(prog)s list
  %(prog)s list --groups MGL DGL
  %(prog)s -p /dev/ttyACM0 caps MGL
  %(prog)s -p /dev/ttyACM0 caps IPC MOP EPR
  %(prog)s -p /dev/ttyACM0 calibration eeprom format-eep-fat --yes --really
  %(prog)s -p /dev/ttyACM0 calibration eeprom sd-backup-raw
  %(prog)s -p /dev/ttyACM0 calibration eeprom sd-restore-raw --yes
""")

    parser.add_argument('-p', '--port', help='Serial port, tcp:host[:port], or ecp:path (required for device commands)')
    parser.add_argument('--tcp-mode', choices=['raw', 'transparent', 'text'], default='text',
                        help='TCP mode: text (arbiter, default), transparent (raw Q-frames via AirBridge), raw (dumb proxy)')
    parser.add_argument('--baud', default='auto', help='Baud rate: auto, 57600, 115200, 460800')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show variable descriptions')

    sub = parser.add_subparsers(dest='command', help='Command')

    sub.add_parser('info', help='Show device identity')

    p_get = sub.add_parser('get', help='Read variables')
    p_get.add_argument('targets', nargs='+', help='Variable names, group names, or "all"')

    p_set = sub.add_parser('set', help='Write variable(s)')
    p_set.add_argument('pairs', nargs='+', metavar='VAR VALUE',
                       help='One or more VAR VALUE pairs')

    p_setv = sub.add_parser('setv', help='Write variable(s) (scaled/human value)')
    p_setv.add_argument('pairs', nargs='+', metavar='VAR VALUE',
                        help='One or more VAR VALUE pairs')

    p_dump = sub.add_parser('dump', help='Dump variables to JSON')
    p_dump.add_argument('-o', '--output', required=True, help='Output JSON file')
    p_dump.add_argument('--groups', nargs='+', help='Only dump these groups')
    p_dump.add_argument('--exclude-groups', nargs='+', help='Exclude these groups')
    p_dump.add_argument('--exclude-vars', nargs='+', help='Exclude these variables')

    p_restore = sub.add_parser('restore', help='Restore variables from JSON')
    p_restore.add_argument('-i', '--input', required=True, help='Input JSON file')
    p_restore.add_argument('--exclude-groups', nargs='+', help='Skip these groups')
    p_restore.add_argument('--exclude-vars', nargs='+', help='Skip these variables')
    p_restore.add_argument('--dry-run', action='store_true', help='Show changes without writing')

    p_raw = sub.add_parser('raw', help='Send raw command')
    p_raw.add_argument('cmd', nargs='+', help='Raw command string (e.g. "G S #BID")')

    p_list = sub.add_parser('list', help='List known variables and descriptions (offline)')
    p_list.add_argument('--groups', nargs='+', help='Only list these groups')

    p_caps = sub.add_parser('caps', help='Query variable values and limits from device')
    p_caps.add_argument('targets', nargs='*', help='Variable names, group names, or "all" (default: all)')

    p_cal = sub.add_parser('calibration', help='Calibration/service utilities')
    cal_sub = p_cal.add_subparsers(dest='calibration_command', help='Calibration command')
    cal_sub.required = True

    p_cal_eeprom = cal_sub.add_parser(
        'eeprom',
        help='Run stock-firmware EEPROM/SD maintenance via CAL=000B')
    p_cal_eeprom.add_argument('action', choices=sorted(EEPROM_ACTIONS),
                              help='EEPROM/SD maintenance action')
    p_cal_eeprom.add_argument('--yes', action='store_true',
                              help='Confirm EEPROM/device-storage writes')
    p_cal_eeprom.add_argument('--really', action='store_true',
                              help='Extra confirmation for destructive EEPROM actions')
    p_cal_eeprom.add_argument('--timeout', type=float, default=300.0,
                              help='Seconds to wait for ETR to return to 0000')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == 'list':
        return cmd_list(args.groups)

    if args.command == 'calibration' and args.calibration_command == 'eeprom':
        if not check_eeprom_confirmations(args.action, args.yes, args.really):
            return 1
        if args.timeout <= 0:
            print("[!] --timeout must be greater than zero")
            return 1

    if args.command in ('set', 'setv'):
        try:
            args.pairs = parse_name_value_pairs(args.pairs, args.command)
        except ValueError as e:
            print(f"[!] {e}")
            return 1

    # All other commands need a live device or Settings.ecp backend.
    if not args.port:
        print("[!] --port is required for this command")
        return 1

    if args.port.startswith('ecp:'):
        try:
            ser = EcpFileDevice(args.port)
        except ValueError as e:
            print(f"[!] {e}")
            return 1
    elif args.port.startswith('tcp:'):
        from tcp_serial import open_tcp
        ser = open_tcp(args.port, args.tcp_mode, timeout=1.0)
    else:
        ser = serial.Serial(args.port, 57600, timeout=1.0)

    try:
        if not connect(ser, args.baud):
            return 1

        if args.command == 'info':
            return cmd_info(ser, verbose=args.verbose)

        elif args.command == 'get':
            return cmd_get(ser, args.targets, verbose=args.verbose)

        elif args.command == 'set':
            return cmd_set(ser, args.pairs)

        elif args.command == 'setv':
            try:
                return cmd_setv(ser, args.pairs)
            except ValueError as e:
                print(f"  [!] {e}")
                return 1

        elif args.command == 'dump':
            data = cmd_dump(ser, args.groups, args.exclude_groups, args.exclude_vars)
            if data is None:
                return 1
            with open(args.output, 'w') as f:
                json.dump(data, f, indent=2, sort_keys=True)
            print(f"[+] Saved to {args.output}")
            return 0

        elif args.command == 'restore':
            with open(args.input) as f:
                data = json.load(f)
            return cmd_restore(ser, data, args.exclude_groups, args.exclude_vars, args.dry_run)

        elif args.command == 'raw':
            if getattr(ser, 'ecp_file', False):
                print("[!] raw is not supported for ecp: backend")
                return 1
            cmd_str = ' '.join(args.cmd)
            send_cmd(ser, cmd_str, timeout=1.0)
            return 0

        elif args.command == 'caps':
            return cmd_caps(ser, args.targets, verbose=args.verbose)

        elif args.command == 'calibration':
            if getattr(ser, 'ecp_file', False):
                print("[!] calibration commands require a live device")
                return 1
            if args.calibration_command == 'eeprom':
                return cmd_calibration_eeprom(
                    ser, args.action, timeout=args.timeout)

    finally:
        ser.close()

    return 0


if __name__ == '__main__':
    sys.exit(main())
