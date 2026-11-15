"""Verified stock clinical-menu append sites and UART bindings.

SX567 constructor arguments: enum r0, numeric/date/time r1, combined model
r1/r3. SX584 additionally has one WMV/ZMV/ZTV/ZVK composite row. Names come
from each image's globals[23] table, not decompiler labels. An anchor is the
whole appended widget, even when it contains several variables.

Verify the construction path before adding anchors for other widgets or
conditionally constructed rows.
"""


class StockMenu:
    def __init__(self, asf):
        self.asf = asf
        version = asf.cdx_ver
        self.binding_overrides = {}
        if version in ('SX567-0302', 'SX567-0305', 'SX567-0306',
                       'SX567-0401', 'SX567-0402'):
            self.rows = SX567_ROWS
            self.delta = -0x720 if version == 'SX567-0302' else 0
            self.ends = (0x62414, 0x62672, 0x626fe, 0x62750, 0x628d2)
            self.append = 0x08064768 if self.delta else 0x08064e8c
            if version in ('SX567-0302', 'SX567-0305'):
                self.binding_overrides['PRD'] = 0x028b
        elif version in ('SX584-0204', 'SX584-0205'):
            self.rows = SX584_ROWS
            self.delta = 0
            self.ends = (0x39026, 0x392d8, 0x394c2, 0x39538, 0x396e6)
            self.append = 0x0803c6a4
        else:
            raise ValueError('custom menu: unsupported stock layout %s' % version)

    def resolve(self, container, name):
        if not 0 <= container < len(self.ends):
            raise ValueError('custom menu: unknown stock section %s' % container)
        if name is None:
            return self.ends[container] + self.delta
        matches = [(site, bindings) for section, site, bindings in self.rows
                   if section == container and any(n == name for n, _ in bindings)]
        if len(matches) != 1:
            reason = 'ambiguous' if matches else 'missing or unverified'
            raise ValueError('custom menu: %s stock anchor %s in section %d (%s)' %
                             (reason, name, container, self.asf.cdx_ver))
        site, bindings = matches[0]
        for uart, expected in bindings:
            expected = self.binding_overrides.get(uart, expected)
            actual = self.asf.resolve_var_id(uart)
            if actual != expected:
                raise ValueError('custom menu: stock row at 0x%X binds %s to '
                                 '0x%04X, UART table resolves 0x%04X' %
                                 (site + self.delta, uart, expected, actual))
        return site + self.delta


# section, append-call file offset, (UART name, constructor var_id) bindings.

SX567_ROWS = (
    (0, 0x62060, (('MOP', 0x020d),)),
    (0, 0x6207e, (('PHT', 0x002f),)),
    (0, 0x6209e, (('IBR', 0x01ec),)),
    (0, 0x620be, (('WMV', 0x01ed),)),
    (0, 0x620dc, (('IPC', 0x0024),)),
    (0, 0x620fa, (('MPA', 0x0025),)),
    (0, 0x6211a, (('MPI', 0x01d3),)),
    (0, 0x6213a, (('MXI', 0x01d6),)),
    (0, 0x6215a, (('MNE', 0x01d5),)),
    (0, 0x6217a, (('SPT', 0x01d7),)),
    (0, 0x62198, (('IPP', 0x0026),)),
    (0, 0x621b8, (('EPP', 0x01d9),)),
    (0, 0x621d8, (('EEP', 0x01e0),)),
    (0, 0x621f8, (('MNS', 0x01e1),)),
    (0, 0x62218, (('MXS', 0x01e2),)),
    (0, 0x62238, (('EAI', 0x01e5),)),
    (0, 0x62258, (('EAX', 0x01e4),)),
    (0, 0x62278, (('ANS', 0x01e6),)),
    (0, 0x62298, (('AXS', 0x01e7),)),
    (0, 0x622b8, (('EPI', 0x01e9),)),
    (0, 0x622d8, (('WPM', 0x01ea),)),
    (0, 0x622f8, (('WPA', 0x01eb),)),
    (0, 0x62318, (('RRT', 0x01de),)),
    (0, 0x6232a, (('BRE', 0x021b),)),
    (0, 0x6233c, (('EBE', 0x0217),)),
    (0, 0x6235c, (('ITT', 0x01df),)),
    (0, 0x6237c, (('ITX', 0x01dd),)),
    (0, 0x6239c, (('ITN', 0x01dc),)),
    (0, 0x623de, (('RSC', 0x0218), ('RST', 0x01db),)),
    (0, 0x623f0, (('VTS', 0x0246),)),
    (0, 0x62402, (('VCS', 0x0245),)),
    (0, 0x62414, (('MSK', 0x0213),)),
    (1, 0x62442, (('AFC', 0x0221),)),
    (1, 0x62484, (('RMA', 0x0240), ('RMT', 0x01ef),)),
    (1, 0x624a4, (('STP', 0x01d2),)),
    (1, 0x624c4, (('STU', 0x01d4),)),
    (1, 0x624e4, (('EPS', 0x01da),)),
    (1, 0x62504, (('STV', 0x01d8),)),
    (1, 0x62524, (('STE', 0x01e3),)),
    (1, 0x62544, (('EAS', 0x01e8),)),
    (1, 0x62564, (('IVS', 0x01ee),)),
    (1, 0x62576, (('EPA', 0x0232),)),
    (1, 0x62588, (('EPT', 0x0234),)),
    (1, 0x625a6, (('EPR', 0x0070),)),
    (1, 0x625b8, (('CCO', 0x0223),)),
    (1, 0x625f6, (('HTX', 0x0226), ('HTS', 0x005a),)),
    (1, 0x62634, (('HTX', 0x0226), ('HTF', 0x005b),)),
    (1, 0x62672, (('HMX', 0x0224), ('HMS', 0x0059),)),
    (2, 0x626a0, (('TBT', 0x0214),)),
    (2, 0x626b2, (('ABF', 0x021c),)),
    (2, 0x626c4, (('HME', 0x022b),)),
    (3, 0x6272c, (('ACC', 0x0216),)),
    (3, 0x6273e, (('ALR', 0x0222),)),
    (3, 0x62750, (('SST', 0x0243),)),
    (4, 0x627ba, (('LAN', 0x0212),)),
    (4, 0x627d8, (('UDT', 0x01f6),)),
    (4, 0x627f6, (('UTI', 0x01fa),)),
    (4, 0x62808, (('PRD', 0x028c),)),
    (4, 0x6281a, (('TMU', 0x022a),)),
)

SX584_ROWS = (
    (0, 0x38b00, (('MOP', 0x022b),)),
    (0, 0x38b1e, (('PHT', 0x0032),)),
    (0, 0x38b3c, (('PHI', 0x0033),)),
    (0, 0x38b5c, (('IBR', 0x0208),)),
    (0, 0x38bd2, (('WMV', 0x0209), ('ZMV', 0x015f), ('ZTV', 0x0160), ('ZVK', 0x0161),)),
    (0, 0x38be4, (('IEU', 0x023a),)),
    (0, 0x38c04, (('EPI', 0x0203),)),
    (0, 0x38c24, (('IMN', 0x0204),)),
    (0, 0x38c44, (('IMX', 0x0205),)),
    (0, 0x38c64, (('WPM', 0x0206),)),
    (0, 0x38c84, (('WPA', 0x0207),)),
    (0, 0x38ca2, (('IPC', 0x0025),)),
    (0, 0x38cc0, (('MPA', 0x0026),)),
    (0, 0x38ce0, (('MPI', 0x01eb),)),
    (0, 0x38d00, (('MXI', 0x01ee),)),
    (0, 0x38d20, (('MNE', 0x01ed),)),
    (0, 0x38d40, (('SPT', 0x01ef),)),
    (0, 0x38d5e, (('IPP', 0x0027),)),
    (0, 0x38d7e, (('EPP', 0x01f1),)),
    (0, 0x38d9e, (('EEP', 0x01fa),)),
    (0, 0x38dbe, (('MNS', 0x01fb),)),
    (0, 0x38dde, (('MXS', 0x01fc),)),
    (0, 0x38dfe, (('EAI', 0x01ff),)),
    (0, 0x38e1e, (('EAX', 0x01fe),)),
    (0, 0x38e3e, (('ANS', 0x0200),)),
    (0, 0x38e5e, (('AXS', 0x0201),)),
    (0, 0x38e70, (('VBE', 0x0237),)),
    (0, 0x38e90, (('RRT', 0x01f6),)),
    (0, 0x38eb0, (('RRC', 0x01f7),)),
    (0, 0x38ed0, (('TBR', 0x01f9),)),
    (0, 0x38ee2, (('BRE', 0x023b),)),
    (0, 0x38ef4, (('EBE', 0x0235),)),
    (0, 0x38f14, (('ITT', 0x01f8),)),
    (0, 0x38f34, (('ITX', 0x01f5),)),
    (0, 0x38fae, (('RSC', 0x0236), ('RST', 0x01f3),)),
    (0, 0x38fc0, (('VTS', 0x0270),)),
    (0, 0x38fd2, (('VCS', 0x026f),)),
    (0, 0x38fe4, (('MSK', 0x0231),)),
    (1, 0x39054, (('AFC', 0x0245),)),
    (1, 0x39096, (('RNM', 0x0266), ('RTM', 0x020c),)),
    (1, 0x390d8, (('RMA', 0x0265), ('RMT', 0x020b),)),
    (1, 0x390ea, (('RDA', 0x0269),)),
    (1, 0x3910a, (('STP', 0x01ea),)),
    (1, 0x3912a, (('STU', 0x01ec),)),
    (1, 0x3914a, (('EPS', 0x01f2),)),
    (1, 0x3916a, (('STV', 0x01f0),)),
    (1, 0x3918a, (('STE', 0x01fd),)),
    (1, 0x391aa, (('EAS', 0x0202),)),
    (1, 0x391ca, (('IVS', 0x020a),)),
    (1, 0x391dc, (('EPA', 0x0256),)),
    (1, 0x391ee, (('EPT', 0x0258),)),
    (1, 0x3920c, (('EPR', 0x0075),)),
    (1, 0x3921e, (('CCO', 0x0247),)),
    (1, 0x3925c, (('HTX', 0x024a), ('HTS', 0x005f),)),
    (1, 0x3929a, (('HTX', 0x024a), ('HTF', 0x0060),)),
    (1, 0x392d8, (('HMX', 0x0248), ('HMS', 0x005e),)),
    (2, 0x39306, (('TBT', 0x0232),)),
    (2, 0x39318, (('ABF', 0x023c),)),
    (2, 0x3932a, (('HME', 0x024f),)),
    (2, 0x393ce, (('LMO', 0x0240), ('LMA', 0x0037),)),
    (2, 0x3945a, (('SPO', 0x0242), ('SPX', 0x0039),)),
    (2, 0x394a2, (('APO', 0x0241), ('APX', 0x0038),)),
    (2, 0x394c2, (('ALV', 0x023d),)),
    (3, 0x394f0, (('ACC', 0x0234),)),
    (3, 0x39502, (('ALR', 0x0246),)),
    (3, 0x39514, (('SCF', 0x026c),)),
    (3, 0x39526, (('SST', 0x026d),)),
    (3, 0x39538, (('TLF', 0x025a),)),
    (4, 0x395a2, (('LAN', 0x0230),)),
    (4, 0x395c0, (('UDT', 0x0214),)),
    (4, 0x395de, (('UTI', 0x0218),)),
    (4, 0x395f0, (('ODT', 0x0259),)),
    (4, 0x39602, (('PRD', 0x02bf),)),
    (4, 0x39614, (('TMU', 0x024e),)),
    (4, 0x39626, (('IHU', 0x0238),)),
)
