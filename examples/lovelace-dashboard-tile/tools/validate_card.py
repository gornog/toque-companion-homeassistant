"""Offline validator for standalone Toque Companion dashboard cards and SVG assets."""
from pathlib import Path
import argparse
import json
import re
import subprocess
import xml.etree.ElementTree as ET
import yaml

PKG_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SUFFIXES = [
    'sensor.{p}status',
    'sensor.{p}temperature',
    'sensor.{p}target_temperature',
    'sensor.{p}weight',
    'sensor.{p}speed_level',
    'sensor.{p}time_remaining',
    'sensor.{p}estimated_end',
    'sensor.{p}program',
    'sensor.{p}current_recipe',
    'sensor.{p}step',
    'sensor.{p}current_step',
    'sensor.{p}waiting_recipe',
    'sensor.{p}last_activity',
    'sensor.{p}base_link',
    'sensor.{p}fault_message',
    'binary_sensor.{p}bowl_present',
    'binary_sensor.{p}fault',
    'binary_sensor.{p}heater',
    'binary_sensor.{p}hot_contents',
    'binary_sensor.{p}lid_open',
    'binary_sensor.{p}motor',
    'binary_sensor.{p}scale_stable',
    'button.{p}pause',
    'button.{p}stop',
    'button.{p}tare_scale',
    'event.{p}cooking',
]


def walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def validate_card(card_path: Path) -> dict:
    card = yaml.safe_load(card_path.read_text(encoding='utf8'))
    assert card.get('type') == 'picture-elements', f'{card_path}: expected picture-elements'
    assert str(card.get('image', '')).endswith('/monsieur-cuisine-connect-frame.svg')

    screen = next(e for e in card['elements'] if e.get('name') == 'Monsieur Cuisine Connect Toque screen')
    m = re.search(r'''const P = (["'])([^"']+)\1;''', screen['custom_fields']['screen'])
    assert m, 'Could not find entity prefix P in screen JS'
    prefix = m.group(2)

    expected = {tmpl.format(p=prefix) for tmpl in EXPECTED_SUFFIXES}
    found = set()
    for node in walk(card):
        for k in ('entity', 'entity_id'):
            val = node.get(k)
            if isinstance(val, str):
                found.add(val)
        for t in node.get('triggers_update', []) or []:
            if isinstance(t, str):
                found.add(t)
    missing = expected - found
    assert not missing, f'{card_path}: missing entities {sorted(missing)}'

    btns = [e for e in card['elements'] if e.get('entity') in {f'button.{prefix}pause', f'button.{prefix}stop', f'button.{prefix}tare_scale'}]
    assert len(btns) == 3
    for b in btns:
        assert b['tap_action']['action'] == 'perform-action'
        assert b['tap_action']['perform_action'] == 'button.press'

    payload = {
        'prefix': prefix,
        'screen': screen['custom_fields']['screen'][3:-3],
        'buttons': [{'entity': b['entity'], 'label': b['name'], 'svg': b['custom_fields']['btn'][3:-3]} for b in btns],
    }
    js = r"""
const fs = require('fs');
const t = JSON.parse(fs.readFileSync(0, 'utf8'));
const P = t.prefix;
const screenFn = new Function('states', t.screen);
function baseStates(overrides = {}) {
  const d = {
    ['sensor.' + P + 'status']: { state: 'idle' },
    ['sensor.' + P + 'temperature']: { state: 'unknown' },
    ['sensor.' + P + 'target_temperature']: { state: '0' },
    ['sensor.' + P + 'weight']: { state: '0' },
    ['sensor.' + P + 'speed_level']: { state: '0' },
    ['sensor.' + P + 'time_remaining']: { state: 'unknown', attributes: { unit_of_measurement: 'min' } },
    ['sensor.' + P + 'estimated_end']: { state: 'unknown' },
    ['sensor.' + P + 'program']: { state: 'unknown', attributes: {} },
    ['sensor.' + P + 'current_recipe']: { state: 'unknown', attributes: {} },
    ['sensor.' + P + 'step']: { state: 'unknown' },
    ['sensor.' + P + 'current_step']: { state: 'unknown', attributes: {} },
    ['sensor.' + P + 'waiting_recipe']: { state: 'unknown' },
    ['sensor.' + P + 'last_activity']: { state: 'unknown', attributes: {} },
    ['sensor.' + P + 'base_link']: { state: 'ready' },
    ['sensor.' + P + 'fault_message']: { state: 'unknown', attributes: {} },
    ['binary_sensor.' + P + 'bowl_present']: { state: 'on' },
    ['binary_sensor.' + P + 'fault']: { state: 'off', attributes: {} },
    ['binary_sensor.' + P + 'heater']: { state: 'off' },
    ['binary_sensor.' + P + 'hot_contents']: { state: 'off' },
    ['binary_sensor.' + P + 'lid_open']: { state: 'off' },
    ['binary_sensor.' + P + 'motor']: { state: 'off' },
    ['binary_sensor.' + P + 'scale_stable']: { state: 'on' },
    ['button.' + P + 'pause']: { state: 'unavailable' },
    ['button.' + P + 'stop']: { state: 'unavailable' },
    ['button.' + P + 'tare_scale']: { state: 'unknown' },
    ['event.' + P + 'cooking']: { state: 'unknown', attributes: {} },
  };
  return Object.assign(d, overrides);
}
const cases = [
  baseStates(),
  baseStates({
    ['sensor.' + P + 'status']: { state: 'running' },
    ['sensor.' + P + 'temperature']: { state: '95' },
    ['sensor.' + P + 'target_temperature']: { state: '100' },
    ['sensor.' + P + 'weight']: { state: '425' },
    ['sensor.' + P + 'speed_level']: { state: '4' },
    ['sensor.' + P + 'time_remaining']: { state: '12', attributes: { unit_of_measurement: 'min' } },
    ['sensor.' + P + 'estimated_end']: { state: new Date(Date.now() + 720000).toISOString() },
    ['sensor.' + P + 'program']: { state: 'Manual cook', attributes: { kind_label: 'Manual', reverse: true, accessory: 'whisk', phase: 1, phase_count: 2 } },
    ['binary_sensor.' + P + 'heater']: { state: 'on' },
    ['binary_sensor.' + P + 'hot_contents']: { state: 'on' },
    ['binary_sensor.' + P + 'motor']: { state: 'on' },
    ['binary_sensor.' + P + 'scale_stable']: { state: 'off' },
  }),
  baseStates({
    ['sensor.' + P + 'status']: { state: 'running' },
    ['sensor.' + P + 'time_remaining']: { state: '45', attributes: { unit_of_measurement: 's' } },
  }),
  baseStates({
    ['sensor.' + P + 'status']: { state: 'paused' },
    ['binary_sensor.' + P + 'lid_open']: { state: 'on' },
  }),
  baseStates({
    ['sensor.' + P + 'status']: { state: 'running' },
    ['sensor.' + P + 'current_recipe']: { state: "Soup & Stew's <test>" },
    ['sensor.' + P + 'step']: { state: '3/12' },
    ['sensor.' + P + 'current_step']: { state: "Add water < 500 ml & blend" },
  }),
  baseStates({ ['sensor.' + P + 'waiting_recipe']: { state: 'Courgette velouté' } }),
  baseStates({ ['sensor.' + P + 'last_activity']: { state: 'Kneading', attributes: { outcome: 'Done', summary: 'Dough 2m30' } } }),
  baseStates({ ['sensor.' + P + 'status']: { state: 'fault' }, ['binary_sensor.' + P + 'fault']: { state: 'on', attributes: { code: 'E12' } }, ['sensor.' + P + 'fault_message']: { state: 'Overheat <E12>' } }),
];
const svgs = [];
for (const c of cases) {
  const s = screenFn(c);
  if (/NaN|undefined/.test(s)) throw Error('Leaked NaN/undefined in screen SVG');
  svgs.push(s);
}
for (const b of t.buttons) {
  const fn = new Function('entity', b.svg);
  for (const st of ['unavailable', 'unknown', '2026-11-25T13:43:48Z']) {
    const s = fn({ state: st });
    if (/NaN|undefined/.test(s) || !s.includes('>' + b.label + '</text>')) throw Error('Invalid button SVG');
    svgs.push(s);
  }
}
console.log(JSON.stringify({ cases: cases.length + t.buttons.length * 3, svgs }));
"""
    res = subprocess.run(['node', '-e', js], input=json.dumps(payload), text=True, capture_output=True, check=True)
    parsed = json.loads(res.stdout)
    for svg in parsed['svgs']:
        ET.fromstring(svg)
    return {'card': card_path.name, 'prefix': prefix, 'entities': len(expected), 'cases_and_xml_passed': parsed['cases']}


def main() -> None:
    parser = argparse.ArgumentParser(description='Validate standalone Toque Companion card YAML and SVG assets.')
    parser.add_argument('cards', nargs='*', help='YAML card files to validate (defaults to toque-card.yaml and toque-card-fr.yaml)')
    args = parser.parse_args()

    for rel in ('www/toque/monsieur-cuisine-connect-frame.svg', 'www/toque/touch-target.svg'):
        p = PKG_ROOT / rel
        assert p.is_file(), f'Missing asset: {p}'
        ET.fromstring(p.read_text(encoding='utf8'))

    targets = [Path(c) for c in args.cards] if args.cards else [PKG_ROOT / 'toque-card.yaml', PKG_ROOT / 'toque-card-fr.yaml']
    results = [validate_card(t) for t in targets]
    print(json.dumps({'svg_assets_valid': 2, 'cards': results}, indent=2))


if __name__ == '__main__':
    main()
