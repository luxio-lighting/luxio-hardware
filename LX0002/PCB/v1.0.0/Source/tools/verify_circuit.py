"""Check LX0002 schematic netlist against the USB-only circuit requirements.

Run after kicad-cli sch export netlist --format kicadxml. This does not certify
PCB geometry, thermal performance, assembly orientation, or RF matching.
"""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
src = root / 'Source'
export = root / 'Export'
parts = json.loads((src / 'parts.json').read_text())
by_ref = {part['ref']: part for part in parts}
netlist_path = export / 'netlist.xml'
netlist = ET.parse(netlist_path).getroot()
nets = {net.get('name'): {(node.get('ref'), node.get('pin')) for node in net.findall('node')}
        for net in netlist.findall('nets/net')}
component_refs = {component.get('ref') for component in netlist.findall('components/comp')}
assert component_refs == set(by_ref), 'Schematic and parts list have different references'
assert all(part['side'] == 'Top' for part in parts if part['lcsc'] and not part.get('dnp', False)), 'Populated components must remain top-only'
checks = []

assert {('J1', 'A4'), ('J1', 'A9'), ('J1', 'B4'), ('J1', 'B9'), ('J4', '1')} <= nets['USB_5V']
assert ('J3', '2') in nets['GND']
assert not any(ref in by_ref for ref in ['J2', 'D1', 'D2', 'D3', 'Q1', 'Q2', 'Q3', 'F1', 'U3', 'U4', 'U5', 'U7'])
assert not any(net in nets for net in ['VSYS', 'DC_IN', 'DC_FUSED', '+5V_DATA', 'USB_ENABLE', 'BOOST_SW', 'BOOST_FB'])
checks.append('USB VBUS is directly on LED VCC; no DC input, power-path diodes, source switches or boost converter')

assert nets['CC1'] == {('J1', 'A5'), ('R1', '1')}
assert nets['CC2'] == {('J1', 'B5'), ('R2', '1')}
assert by_ref['R1']['value'] == by_ref['R2']['value'] == '5.1k'
assert {('R1', '2'), ('R2', '2')} <= nets['GND']
checks.append('Independent 5.1k CC1 and CC2 pull-downs')

for gpio, mcu_pin, buffer, resistor, connector, connector_pin in [
    ('GPIO16', '22', 'U8', 'R16', 'J3', '1'),
    ('GPIO17', '23', 'U9', 'R27', 'J4', '2'),
]:
    assert {('U1', mcu_pin), (buffer, '2')} <= nets[gpio]
    assert {(buffer, '1'), (buffer, '3')} <= nets['GND']
    assert (buffer, '5') in nets['USB_5V']
    assert by_ref[buffer]['value'] == 'SN74AHCT1G125DBVR'
    signal = 'DATA' + gpio[4:]
    assert nets[signal + '_5V'] == {(buffer, '4'), (resistor, '1')}
    assert {(resistor, '2'), (connector, connector_pin)} <= nets[signal + '_OUT']
    assert by_ref[resistor]['value'] == '100'
checks.append('GPIO16 and GPIO17 use permanently enabled 5V AHCT buffers and separate 100-ohm output resistors')

assert by_ref['D4']['value'] == 'BAT54C'
assert nets['BOOT'] == {('U1', '5'), ('R101', '2'), ('D4', '1')}
assert {('U1', '24'), ('R30', '2'), ('D4', '2')} <= nets['GPIO18_BUTTON']
assert nets['BUTTON_COMMON'] == {('D4', '3'), ('SW1', '1')}
assert ('SW1', '2') in nets['GND']
assert {('R101', '1'), ('R30', '1')} <= nets['+3V3']
assert by_ref['R101']['value'] == by_ref['R30']['value'] == '10k'
checks.append('BOOT and GPIO18 have separate 10k pull-ups and Schottky isolation to the shared button')

assert by_ref['U6']['value'] == 'LMR51410YFDBVR'
assert {('U6', '4'), ('U6', '5')} <= nets['USB_5V']
assert nets['BUCK_SW'] == {('U6', '6'), ('C9', '2'), ('L1', '1')}
assert nets['BUCK_BST'] == {('U6', '1'), ('C9', '1')}
assert nets['BUCK_FB'] == {('U6', '3'), ('R22', '2'), ('R23', '1')}
assert nets['BUCK_FB_LOW'] == {('R23', '2'), ('R24', '1')}
assert by_ref['R22']['value'] == '100k' and by_ref['R23']['value'] == '22k' and by_ref['R24']['value'] == '10k'
nominal_vout = 0.8 * (1 + 100 / (22 + 10))
assert abs(nominal_vout - 3.3) < 1e-9
checks.append('Original synchronous buck topology and nominal 3.3V feedback ratio retained')

assert by_ref['R106']['value'] == '0' and by_ref['R106']['lcsc'] == 'C17477'
assert by_ref['R106']['footprint'] == 'Resistor_SMD:R_0805_2012Metric'
assert nets['+3V3_ANALOG'] == {('R106', '2'), ('U1', '55'), ('U1', '56'), ('C105', '1')}
assert {('R106', '1'), ('C106', '1')} <= nets['+3V3']
checks.append('0805 zero-ohm R106 bridges VDDA55/56 and C105 from 3V3 while C106 retains the main supply')

assert by_ref['U1']['value'] == by_ref['U1']['mpn'] == 'ESP32-S3FH4R2'
assert by_ref['U1']['lcsc'] == 'C3013940'
assert by_ref['U1']['memory']['flash_bytes'] == 4 * 1024 * 1024
assert by_ref['U1']['memory']['flash_location'] == 'in-package'
assert by_ref['U1']['memory']['flash_bus'] == 'Quad SPI'
assert by_ref['U1']['memory']['psram_bytes'] == 2 * 1024 * 1024
assert by_ref['U1']['memory']['psram_bus'] == 'Quad SPI'
assert by_ref['U1']['memory']['psram_location'] == 'in-package'
assert by_ref['U1']['footprint'] == 'Core:ESP32_S3FH4R2_QFN56_7x7_EP5p7'
assert not {'U10', 'R105', 'R110', 'C110', 'R102'} & set(by_ref)
assert not {'FLASH_IO0', 'FLASH_IO1', 'FLASH_IO2', 'FLASH_IO3', 'FLASH_CS', 'FLASH_CLK', 'SPICLK', 'STRAP45'} & set(nets)
for pin in [28, 30, 31, 32, 33, 34, 35, 51]:
    assert str(pin) not in by_ref['U1']['pins'], 'Reserved memory/unused GPIO45 pad must remain NC'
    matches = [net for net in netlist.findall('nets/net') if any(node.get('ref') == 'U1' and node.get('pin') == str(pin) for node in net.findall('node'))]
    assert len(matches) == 1 and matches[0].get('name').startswith('unconnected-')
    assert len(matches[0].findall('node')) == 1 and 'no_connect' in matches[0].find('node').get('pintype', '')
assert nets['VDD_SPI'] == {('U1', '29'), ('C108', '1'), ('C109', '1')}
assert by_ref['C108']['value'] == '100nF 16V' and by_ref['C109']['value'] == '1uF 25V'
assert {('C108', '2'), ('C109', '2')} <= nets['GND']
assert by_ref['ANT1']['value'] == 'RFECA3216060A1T'
assert not any(part['libname'].split(':', 1)[0] in {'Memory_Flash', 'Memory_RAM'} for part in parts), 'No off-package flash or PSRAM components'
assert {('U1', '25'), ('R3', '2')} <= nets['USB_DM']
assert {('U1', '26'), ('R4', '2')} <= nets['USB_DP']
assert by_ref['U2']['value'] == 'USBLC6-2SC6'
assert {('J1', 'A7'), ('J1', 'B7'), ('U2', '1'), ('U2', '6'), ('R3', '1')} <= nets['USB_DM_CONN']
assert {('J1', 'A6'), ('J1', 'B6'), ('U2', '3'), ('U2', '4'), ('R4', '1')} <= nets['USB_DP_CONN']
checks.append('ESP32-S3FH4R2 has 4MB in-package Quad-SPI flash and 2MB Quad-SPI PSRAM; seven memory pads reserved/NC and VDD_SPI bypassing retained')
assert by_ref['R103']['value'] == '10k'
assert nets['STRAP46'] == {('U1', '52'), ('R103', '1')}
assert ('R103', '2') in nets['GND']
checks.append('FH4R2 fixed 3.3V VDD_SPI needs no GPIO45 pulldown; GPIO46 boot pulldown retained')
checks.append('Ceramic antenna and native USB ESD/data connections retained')
assert 'TP11' not in by_ref and 'TP12' not in by_ref
assert '49' not in by_ref['U1']['pins'] and '50' not in by_ref['U1']['pins']
assert not any(net in nets for net in ['UART_TX', 'UART_RX'])
checks.append('Optional UART testpads omitted; UART GPIO43/44 left unconnected, native USB retained')

baseline = root.parents[2] / 'LX0001/PCB/v1.0.0/Source/core_parts.json'
if baseline.exists():
    original_core = json.loads(baseline.read_text())
    for previous in original_core:
        if previous['ref'] in {'U10', 'R105', 'R110', 'C110', 'R102'}:
            continue
        part = by_ref[previous['ref']]
        expected_pins = dict(previous['pins'])
        if previous['ref'] == 'U1':
            expected_pins.pop('49')
            expected_pins.pop('50')
            for pin in [28, 30, 31, 32, 33, 34, 35, 51]:
                expected_pins.pop(str(pin), None)
            expected_pins['55'] = expected_pins['56'] = '+3V3_ANALOG'
            assert part['pins'] == expected_pins
        else:
            if previous['ref'] == 'C105':
                expected_pins['1'] = '+3V3_ANALOG'
            assert part['value'] == previous['value'] and part['pins'] == expected_pins
            if previous['ref'] == 'L102':
                assert part['lcsc'] == 'C7216765' and part['mpn'] == 'LQP03HQ2N7B02D'
                assert part['footprint'] == previous['footprint']
            else:
                assert part['lcsc'] == previous['lcsc']
    checks.append('LX0001 core pinout, supply, crystal and RF values preserved except FH4R2 memory migration, VDDA jumper bridge, equivalent 2.7nH 0201 L102 sourcing substitution and omitted UART debug nets')

report = {
    'result': 'PASS',
    'scope': 'Schematic electrical topology only; PCB layout and physical validation are separate',
    'netlist_sha256': hashlib.sha256(netlist_path.read_bytes()).hexdigest(),
    'footprint_count': len(parts),
    'populated_bom_count': sum(bool(part['lcsc']) and not part.get('dnp', False) for part in parts),
    'checks': checks,
    'nominal_buck_output_v': nominal_vout,
    'usb_power': 'Direct nominal 5V, no PD and no onboard input current limiter. Total current includes controller and strip.',
}
(export / 'circuit-validation.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
