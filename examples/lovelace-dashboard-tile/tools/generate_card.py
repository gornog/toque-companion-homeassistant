"""Generate a standalone Home Assistant Picture Elements card for Toque Companion."""
from pathlib import Path
import argparse
import sys
import yaml

# Measured on www/toque/monsieur-cuisine-connect-frame.svg (1200x920)
SCREEN_RECT = {
    'left': 12.3333,
    'top': 25.8696,
    'width': 75.3333,
    'height': 57.6087,
}

I18N = {
    'en': {
        'title': 'Monsieur Cuisine Connect · Toque',
        'idle_sub': 'Standby · Ready to cook',
        'link_ready': 'Base ready',
        'link_arming': 'Arming',
        'link_lost': 'Link lost',
        'link_offline': 'Offline',
        'link_unknown': 'Unknown',
        'st_idle': 'Ready',
        'st_starting': 'Starting',
        'st_running': 'Running',
        'st_paused': 'Paused',
        'st_stopping': 'Stopping…',
        'st_finished': 'Finished',
        'st_aborted': 'Aborted',
        'st_fault': 'Fault',
        'st_unavail': 'Unavailable',
        'end_ready': 'Ready',
        'end_prefix': 'Ends ',
        'end_paused': 'Paused',
        'end_finished': 'Finished',
        'end_aborted': 'Aborted',
        'target_heat_on': 'Heating active',
        'target_hot': 'Hot ≥60°',
        'target_set': 'Target',
        'target_no_heat': 'No heating',
        'heat_on': 'Heater ON',
        'heat_off': 'Heater OFF',
        'spd_motor': 'Motor active',
        'spd_stop': 'Stopped',
        'spd_stir': 'Stir',
        'spd_chop': 'Chop',
        'spd_blend': 'Blend',
        'spd_prefix': 'Motor · ',
        'temp_hot': 'HOT ≥60°',
        'temp_meas': 'measured',
        'temp_cold': 'cold base',
        'temp_offline': 'offline',
        'scale_lbl': 'Scale',
        'scale_stable': '✓ Stable',
        'scale_unstable': '… Unstable',
        'chip_hot': 'HOT ≥60°',
        'chip_lid_open': 'Lid open',
        'chip_lid_closed': 'Lid closed',
        'lbl_dur': 'TIME',
        'lbl_temp': 'TEMPERATURE',
        'lbl_spd': 'SPEED',
        'dir_rev': '↺ Reverse',
        'dir_fwd': '↻ Forward',
        'acc_whisk': 'Whisk',
        'acc_blade': 'Blade',
        'pill_lid': 'Lid',
        'pill_lid_open': 'Open',
        'pill_lid_closed': 'Closed',
        'pill_bowl': 'Bowl',
        'pill_bowl_on': 'Present',
        'pill_bowl_off': 'Missing',
        'pill_motor': 'Motor',
        'pill_motor_on': 'Active',
        'pill_motor_off': 'Off',
        'pill_heat': 'Heater',
        'pill_heat_on': 'Active',
        'pill_heat_off': 'Off',
        'step_prefix': 'Step ',
        'recipe_lbl': 'Recipe',
        'recipe_wait': 'Waiting: ',
        'recipe_sub': 'Guided recipe in progress',
        'wait_prefix': 'Recipe ready: ',
        'wait_badge': 'Waiting',
        'wait_sub': 'Selected on robot screen',
        'last_prefix': 'Last activity: ',
        'last_badge': 'History',
        'last_sub': 'Previous session ended',
        'fault_default': 'Fault detected',
        'phase_prefix': 'Phase ',
    },
    'fr': {
        'title': 'Monsieur Cuisine Connect · Toque',
        'idle_sub': 'En veille · Prêt à cuisiner',
        'link_ready': 'Base prête',
        'link_arming': 'Initialisation',
        'link_lost': 'Lien perdu',
        'link_offline': 'Hors ligne',
        'link_unknown': 'Inconnu',
        'st_idle': 'Prêt',
        'st_starting': 'Démarrage',
        'st_running': 'En cours',
        'st_paused': 'En pause',
        'st_stopping': 'Arrêt…',
        'st_finished': 'Terminé',
        'st_aborted': 'Interrompu',
        'st_fault': 'Erreur',
        'st_unavail': 'Indisponible',
        'end_ready': 'Prêt',
        'end_prefix': 'Fin ',
        'end_paused': 'En pause',
        'end_finished': 'Terminé',
        'end_aborted': 'Interrompu',
        'target_heat_on': 'Chauffe active',
        'target_hot': 'Chaud ≥60°',
        'target_set': 'Consigne',
        'target_no_heat': 'Sans chauffe',
        'heat_on': 'Chauffe ON',
        'heat_off': 'Chauffe OFF',
        'spd_motor': 'Moteur actif',
        'spd_stop': 'Arrêt',
        'spd_stir': 'Mélanger',
        'spd_chop': 'Hacher',
        'spd_blend': 'Mixer',
        'spd_prefix': 'Moteur · ',
        'temp_hot': 'CHAUD ≥60°',
        'temp_meas': 'mesuré',
        'temp_cold': 'base froide',
        'temp_offline': 'hors ligne',
        'scale_lbl': 'Balance',
        'scale_stable': '✓ Stable',
        'scale_unstable': '… Instable',
        'chip_hot': 'CHAUD ≥60°',
        'chip_lid_open': 'Couvercle ouvert',
        'chip_lid_closed': 'Couvercle fermé',
        'lbl_dur': 'DURÉE',
        'lbl_temp': 'TEMPÉRATURE',
        'lbl_spd': 'VITESSE',
        'dir_rev': '↺ Sens inverse',
        'dir_fwd': '↻ Sens normal',
        'acc_whisk': 'Fouet',
        'acc_blade': 'Lame',
        'pill_lid': 'Couvercle',
        'pill_lid_open': 'Ouvert',
        'pill_lid_closed': 'Fermé',
        'pill_bowl': 'Bol',
        'pill_bowl_on': 'Présent',
        'pill_bowl_off': 'Absent',
        'pill_motor': 'Moteur',
        'pill_motor_on': 'Actif',
        'pill_motor_off': 'Arrêt',
        'pill_heat': 'Chauffe',
        'pill_heat_on': 'Active',
        'pill_heat_off': 'Arrêt',
        'step_prefix': 'Étape ',
        'recipe_lbl': 'Recette',
        'recipe_wait': 'En attente : ',
        'recipe_sub': 'Recette guidée en cours',
        'wait_prefix': 'Recette prête : ',
        'wait_badge': 'En attente',
        'wait_sub': 'Sélectionnée sur l’écran du robot',
        'last_prefix': 'Dernière activité : ',
        'last_badge': 'Historique',
        'last_sub': 'Session précédente terminée',
        'fault_default': 'Défaut détecté',
        'phase_prefix': 'Phase ',
    },
}

BUTTON_ICONS = {
    'pause': '<rect x="33" y="14" width="6" height="20" rx="2" fill="${fg}"/><rect x="45" y="14" width="6" height="20" rx="2" fill="${fg}"/>',
    'stop': '<rect x="32" y="14" width="20" height="20" rx="3" fill="${fg}"/>',
    'tare': '<path d="M27 25 h30 M42 14 v11 M31 25 l-3 7 h6 z M53 25 l-3 7 h6 z M35 35 h14" fill="none" stroke="${fg}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
}


def make_entities(prefix: str) -> dict[str, str]:
    return {
        'status': f'sensor.{prefix}status',
        'temperature': f'sensor.{prefix}temperature',
        'target_temperature': f'sensor.{prefix}target_temperature',
        'weight': f'sensor.{prefix}weight',
        'speed_level': f'sensor.{prefix}speed_level',
        'time_remaining': f'sensor.{prefix}time_remaining',
        'estimated_end': f'sensor.{prefix}estimated_end',
        'program': f'sensor.{prefix}program',
        'current_recipe': f'sensor.{prefix}current_recipe',
        'step': f'sensor.{prefix}step',
        'current_step': f'sensor.{prefix}current_step',
        'waiting_recipe': f'sensor.{prefix}waiting_recipe',
        'last_activity': f'sensor.{prefix}last_activity',
        'base_link': f'sensor.{prefix}base_link',
        'fault_message': f'sensor.{prefix}fault_message',
        'bowl_present': f'binary_sensor.{prefix}bowl_present',
        'fault': f'binary_sensor.{prefix}fault',
        'heater': f'binary_sensor.{prefix}heater',
        'hot_contents': f'binary_sensor.{prefix}hot_contents',
        'lid_open': f'binary_sensor.{prefix}lid_open',
        'motor': f'binary_sensor.{prefix}motor',
        'scale_stable': f'binary_sensor.{prefix}scale_stable',
        'pause': f'button.{prefix}pause',
        'stop': f'button.{prefix}stop',
        'tare': f'button.{prefix}tare_scale',
        'cooking': f'event.{prefix}cooking',
    }


def screen_box(x0: float, y0: float, x1: float, y1: float) -> tuple[str, str, str, str]:
    cx = SCREEN_RECT['left'] + ((x0 + x1) / 2.0 / 1024.0) * SCREEN_RECT['width']
    cy = SCREEN_RECT['top'] + ((y0 + y1) / 2.0 / 600.0) * SCREEN_RECT['height']
    w = ((x1 - x0) / 1024.0) * SCREEN_RECT['width']
    h = ((y1 - y0) / 600.0) * SCREEN_RECT['height']
    return f'{cx:.4f}%', f'{cy:.4f}%', f'{w:.4f}%', f'{h:.4f}%'


def build_screen_js(prefix: str, lang: str) -> str:
    import json
    t_json = json.dumps(I18N[lang], ensure_ascii=False)
    return """[[[
const P = """ + json.dumps(prefix) + """;
const T = """ + t_json + """;
const s = k => states['sensor.' + P + k];
const b = k => states['binary_sensor.' + P + k];
const e = k => states['event.' + P + k];
const validStr = v => typeof v === 'string' && v.trim() !== '' && !['unknown', 'unavailable', 'none', 'null'].includes(v.trim().toLowerCase());
const num = obj => {
  const raw = obj?.state;
  const n = Number(raw);
  return typeof raw === 'string' && raw.trim() !== '' && Number.isFinite(n) ? n : null;
};
const esc = v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const trunc = (v, n) => { const t = String(v ?? '').trim(); return t.length > n ? t.slice(0, n - 1) + '…' : t; };

const statusRaw = (s('status')?.state || 'unknown').toLowerCase();
const linkRaw = (s('base_link')?.state || 'unknown').toLowerCase();
const linkLabel = validStr(s('base_link')?.attributes?.label) ? s('base_link').attributes.label :
  ({ready: T.link_ready, arming: T.link_arming, lost: T.link_lost, offline: T.link_offline}[linkRaw] || T.link_unknown);
const linkColor = linkRaw === 'ready' ? '#3DDC97' : linkRaw === 'arming' ? '#FFC14D' : linkRaw === 'lost' || linkRaw === 'offline' ? '#FF5A5F' : '#66738A';

const statusMeta = {
  idle: [T.st_idle, '#3DDC97'],
  starting: [T.st_starting, '#FF8A3D'],
  running: [T.st_running, '#FF8A3D'],
  paused: [T.st_paused, '#FFC14D'],
  stopping: [T.st_stopping, '#FF8A3D'],
  finished: [T.st_finished, '#3DDC97'],
  aborted: [T.st_aborted, '#FFC14D'],
  fault: [T.st_fault, '#FF5A5F'],
}[statusRaw] || [T.st_unavail, '#66738A'];

const temp = num(s('temperature'));
const target = num(s('target_temperature'));
const speed = num(s('speed_level'));
const weight = num(s('weight'));
const remObj = s('time_remaining');
const remVal = num(remObj);
const remUnit = String(remObj?.attributes?.unit_of_measurement || 'min').toLowerCase();
let remSec = remVal !== null ? Math.max(0, Math.round(remUnit.startsWith('min') ? remVal * 60 : remVal)) : null;
const estRaw = s('estimated_end')?.state;
const estMs = validStr(estRaw) ? Date.parse(estRaw) : NaN;
if (remSec === null && Number.isFinite(estMs) && ['starting', 'running'].includes(statusRaw)) {
  remSec = Math.max(0, Math.round((estMs - Date.now()) / 1000));
}

const bowlOn = b('bowl_present')?.state === 'on';
const lidOpen = b('lid_open')?.state === 'on';
const motorOn = b('motor')?.state === 'on';
const heaterOn = b('heater')?.state === 'on';
const hotOn = b('hot_contents')?.state === 'on';
const scaleStable = b('scale_stable')?.state === 'on';
const faultOn = b('fault')?.state === 'on' || statusRaw === 'fault';
const faultMsgObj = s('fault_message');
const faultText = validStr(faultMsgObj?.state) ? faultMsgObj.state : validStr(b('fault')?.attributes?.message) ? b('fault').attributes.message : '';
const faultCode = faultMsgObj?.attributes?.code ?? b('fault')?.attributes?.code ?? null;

const progObj = s('program');
const progName = validStr(progObj?.state) ? progObj.state : '';
const progAttrs = progObj?.attributes || {};
const reverseOn = progAttrs.reverse === true;
const accessoryRaw = String(progAttrs.accessory || '').toLowerCase();
const isWhisk = accessoryRaw.includes('whisk') || accessoryRaw.includes('fouet');
const phaseStr = (progAttrs.phase && progAttrs.phase_count) ? `${T.phase_prefix}${progAttrs.phase}/${progAttrs.phase_count}` : '';

const recipeObj = s('current_recipe');
const recipeName = validStr(recipeObj?.state) ? recipeObj.state : '';
const stepLabel = validStr(s('step')?.state) ? s('step').state : '';
const curStepObj = s('current_step');
const curStepText = validStr(curStepObj?.attributes?.text) ? curStepObj.attributes.text : validStr(curStepObj?.state) ? curStepObj.state : '';
const waitRecipe = validStr(s('waiting_recipe')?.state) ? s('waiting_recipe').state : '';
const lastActObj = s('last_activity');
const lastAct = validStr(lastActObj?.state) ? lastActObj.state : '';
const cookEv = e('cooking')?.attributes?.event_type;

const activeRun = ['starting', 'running'].includes(statusRaw);
const activePause = statusRaw === 'paused';

let durText = '—';
if (remSec !== null && (remSec > 0 || activeRun || activePause)) {
  if (remSec >= 3600) {
    const h = Math.floor(remSec / 3600);
    const m = Math.floor((remSec % 3600) / 60);
    durText = h + 'h' + String(m).padStart(2, '0');
  } else {
    const m = Math.floor(remSec / 60);
    const sec = remSec % 60;
    durText = String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
  }
}
let endText = T.end_ready;
if (Number.isFinite(estMs)) {
  const dt = new Date(estMs);
  endText = T.end_prefix + String(dt.getHours()).padStart(2, '0') + ':' + String(dt.getMinutes()).padStart(2, '0');
} else if (activePause) {
  endText = validStr(progAttrs.pause_label) ? trunc(progAttrs.pause_label, 20) : T.end_paused;
} else if (statusRaw === 'finished') {
  endText = T.end_finished;
} else if (statusRaw === 'aborted') {
  endText = T.end_aborted;
}

const targetText = (target !== null && target > 0) ? Math.round(target) + '°' : '—';
const targetSub = heaterOn ? T.target_heat_on : hotOn ? T.target_hot : (target !== null && target > 0) ? T.target_set : T.target_no_heat;
const targetSubColor = heaterOn ? '#FF8A3D' : hotOn ? '#FF5A5F' : '#9CA8BC';

const speedNum = speed !== null ? Math.max(0, Math.min(10, Math.round(speed))) : 0;
const speedMode = speedNum === 0 ? T.spd_stop : speedNum <= 3 ? T.spd_stir : speedNum <= 6 ? T.spd_chop : T.spd_blend;
const speedDesc = motorOn ? (speedNum > 0 ? T.spd_prefix + speedMode : T.spd_motor) : speedMode;
const speedSubColor = motorOn ? '#5CC8FF' : '#9CA8BC';

const tempKnown = temp !== null && temp > 0;
const tempDisplay = tempKnown ? Math.round(temp) + '°' : (linkRaw === 'ready' ? '<37°' : '—');
const tempSub = hotOn ? T.temp_hot : tempKnown ? T.temp_meas : (linkRaw === 'ready' ? T.temp_cold : T.temp_offline);
const tempArcPct = tempKnown ? Math.max(0, Math.min(1, temp / 130)) : 0;
const ringLen = 490.088;
const ringOffset = ringLen * (1 - tempArcPct);
const ringColor = (heaterOn || hotOn || (temp !== null && temp >= 60)) ? '#FF8A3D' : '#5CC8FF';

let targetTick = '';
if (target !== null && target > 0) {
  const deg = 135 + 270 * Math.max(0, Math.min(1, target / 130));
  const rad = deg * Math.PI / 180;
  const x1 = (850 + 93 * Math.cos(rad)).toFixed(1);
  const y1 = (224 + 93 * Math.sin(rad)).toFixed(1);
  const x2 = (850 + 115 * Math.cos(rad)).toFixed(1);
  const y2 = (224 + 115 * Math.sin(rad)).toFixed(1);
  targetTick = `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#F3F5F9" stroke-width="3.5" stroke-linecap="round"/>`;
}

let rpmBars = '';
for (let i = 1; i <= 10; i++) {
  const bx = 774 + (i - 1) * 15.5;
  const bh = 10 + i * 1.8;
  const by = 342 - bh;
  const lit = i <= speedNum && (motorOn || activeRun || activePause);
  const fill = lit ? (heaterOn ? '#FF8A3D' : '#5CC8FF') : '#223048';
  rpmBars += `<rect x="${bx.toFixed(1)}" y="${by.toFixed(1)}" width="11" height="${bh.toFixed(1)}" rx="3" fill="${fill}"/>`;
}

const weightText = weight !== null ? Math.round(weight) + ' g' : '—';
const scaleTag = scaleStable ? T.scale_stable : T.scale_unstable;
const scaleColor = scaleStable ? '#3DDC97' : '#FFC14D';

const durStroke = activeRun ? '#FF8A3D' : activePause ? '#FFC14D' : '#2A3A55';
const durStrokeW = (activeRun || activePause) ? 2.5 : 1.5;
const tempStroke = heaterOn ? '#FF8A3D' : '#2A3A55';
const tempStrokeW = heaterOn ? 2.5 : 1.5;
const spdStroke = motorOn ? '#5CC8FF' : '#2A3A55';
const spdStrokeW = motorOn ? 2.5 : 1.5;

let ctxLine1 = T.title;
let ctxLine2 = T.idle_sub;
let ctxBadge = '';
if (recipeName) {
  ctxLine1 = trunc(recipeName, 44);
  ctxBadge = stepLabel ? T.step_prefix + trunc(stepLabel, 10) : T.recipe_lbl;
  ctxLine2 = curStepText ? trunc(curStepText, 64) : validStr(curStepObj?.attributes?.weigh_label) ? trunc(curStepObj.attributes.weigh_label, 64) : validStr(recipeObj?.attributes?.waiting_for) ? T.recipe_wait + trunc(recipeObj.attributes.waiting_for, 46) : T.recipe_sub;
} else if (progName) {
  ctxLine1 = trunc(progName, 44);
  ctxBadge = validStr(progAttrs.kind_label) ? trunc(progAttrs.kind_label, 14) : '';
  ctxLine2 = validStr(progAttrs.pause_label) ? trunc(progAttrs.pause_label, 62) : validStr(progAttrs.end_reason) ? trunc(progAttrs.end_reason, 62) : (phaseStr || statusMeta[0]);
} else if (waitRecipe) {
  ctxLine1 = T.wait_prefix + trunc(waitRecipe, 36);
  ctxBadge = T.wait_badge;
  ctxLine2 = T.wait_sub;
} else if (lastAct) {
  ctxLine1 = T.last_prefix + trunc(lastAct, 34);
  ctxBadge = validStr(lastActObj?.attributes?.outcome) ? trunc(lastActObj.attributes.outcome, 14) : T.last_badge;
  ctxLine2 = validStr(lastActObj?.attributes?.summary) ? trunc(lastActObj.attributes.summary, 64) : T.last_sub;
} else if (validStr(cookEv)) {
  ctxBadge = trunc(cookEv, 16);
}

const faultBanner = (faultOn || faultText) ? `<g>
  <rect x="24" y="64" width="658" height="28" rx="8" fill="#3B151D" stroke="#FF5A5F" stroke-width="1.5"/>
  <text x="40" y="83" fill="#FFD6D8" font-size="13.5" font-weight="600" font-family="sans-serif">⚠ ${esc(trunc(faultText || T.fault_default, 60))}${faultCode !== null ? ' (' + esc(faultCode) + ')' : ''}</text>
</g>` : '';
const cardY = (faultOn || faultText) ? 100 : 78;
const cardH = (faultOn || faultText) ? 310 : 332;

const chipTempFill = hotOn ? '#3D151B' : '#1A2639';
const chipTempStroke = hotOn ? '#FF5A5F' : '#2A3A55';
const chipTempText = hotOn ? T.chip_hot : (tempKnown ? Math.round(temp) + ' °C' : '<37 °C');
const chipTempCol = hotOn ? '#FF8084' : '#F3F5F9';

const chipLidFill = lidOpen ? '#3B2D12' : '#1A2639';
const chipLidStroke = lidOpen ? '#FFC14D' : '#2A3A55';
const chipLidText = lidOpen ? T.chip_lid_open : T.chip_lid_closed;
const chipLidCol = lidOpen ? '#FFC14D' : '#9CA8BC';

const pills = [
  [T.pill_lid, lidOpen ? T.pill_lid_open : T.pill_lid_closed, lidOpen ? '#FFC14D' : '#3DDC97', 24],
  [T.pill_bowl, bowlOn ? T.pill_bowl_on : T.pill_bowl_off, bowlOn ? '#3DDC97' : '#FF5A5F', 192],
  [T.pill_motor, motorOn ? T.pill_motor_on : T.pill_motor_off, motorOn ? '#5CC8FF' : '#66738A', 360],
  [T.pill_heat, heaterOn ? T.pill_heat_on : T.pill_heat_off, heaterOn ? '#FF8A3D' : '#66738A', 528],
];
const pillsSvg = pills.map(([lbl, val, col, px]) => `
  <rect x="${px}" y="524" width="154" height="52" rx="14" fill="#131D2E" stroke="#2A3A55" stroke-width="1.5"/>
  <circle cx="${px + 18}" cy="544" r="5" fill="${col}"/>
  <text x="${px + 30}" y="546" fill="#9CA8BC" font-size="13" font-weight="600" font-family="sans-serif">${esc(lbl)}</text>
  <text x="${px + 30}" y="566" fill="#F3F5F9" font-size="16" font-weight="600" font-family="sans-serif">${esc(val)}</text>
`).join('');

return `<svg viewBox="0 0 1024 600" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Toque interface ${esc(statusMeta[0])}">
<defs>
  <linearGradient id="tqBg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#16294A"/>
    <stop offset="52%" stop-color="#0D1A31"/>
    <stop offset="100%" stop-color="#070E1B"/>
  </linearGradient>
</defs>
<rect width="1024" height="600" fill="url(#tqBg)"/>

<circle cx="38" cy="36" r="7" fill="${statusMeta[1]}"/>
<text x="54" y="43" fill="#F3F5F9" font-size="24" font-weight="600" font-family="sans-serif">Toque</text>
<rect x="132" y="19" width="136" height="34" rx="17" fill="#1A2639" stroke="#2A3A55" stroke-width="1.5"/>
<text x="200" y="41" text-anchor="middle" fill="${statusMeta[1]}" font-size="15" font-weight="600" font-family="sans-serif">${esc(statusMeta[0])}</text>

<rect x="434" y="18" width="140" height="36" rx="18" fill="${chipTempFill}" stroke="${chipTempStroke}" stroke-width="1.5"/>
<text x="504" y="41" text-anchor="middle" fill="${chipTempCol}" font-size="15" font-weight="600" font-family="sans-serif">${esc(chipTempText)}</text>

<rect x="584" y="18" width="172" height="36" rx="18" fill="${chipLidFill}" stroke="${chipLidStroke}" stroke-width="1.5"/>
<text x="670" y="41" text-anchor="middle" fill="${chipLidCol}" font-size="15" font-weight="600" font-family="sans-serif">${esc(chipLidText)}</text>

<rect x="766" y="18" width="234" height="36" rx="18" fill="#1A2639" stroke="#2A3A55" stroke-width="1.5"/>
<circle cx="786" cy="36" r="5.5" fill="${linkColor}"/>
<text x="800" y="41" fill="#F3F5F9" font-size="15" font-weight="600" font-family="sans-serif">${esc(trunc(linkLabel, 19))}</text>

${faultBanner}

<rect x="24" y="${cardY}" width="210" height="${cardH}" rx="20" fill="#131D2E" stroke="${durStroke}" stroke-width="${durStrokeW}"/>
<circle cx="48" cy="${cardY + 33}" r="8.5" fill="none" stroke="#FF8A3D" stroke-width="2"/>
<path d="M48 ${cardY + 28} v5 l3.5 2" fill="none" stroke="#FF8A3D" stroke-width="2" stroke-linecap="round"/>
<text x="66" y="${cardY + 39}" fill="#9CA8BC" font-size="16" font-weight="700" letter-spacing="0.8" font-family="sans-serif">${esc(T.lbl_dur)}</text>
<text x="42" y="${cardY + 128}" fill="#F3F5F9" font-size="56" font-weight="300" font-family="sans-serif">${esc(durText)}</text>
<text x="42" y="${cardY + 168}" fill="#9CA8BC" font-size="18" font-family="sans-serif">${esc(endText)}</text>
${phaseStr ? `<rect x="42" y="${cardY + 194}" width="132" height="30" rx="15" fill="#1A2639" stroke="#2A3A55"/><text x="108" y="${cardY + 214}" text-anchor="middle" fill="#5CC8FF" font-size="14" font-weight="600" font-family="sans-serif">${esc(phaseStr)}</text>` : ''}

<rect x="248" y="${cardY}" width="210" height="${cardH}" rx="20" fill="#131D2E" stroke="${tempStroke}" stroke-width="${tempStrokeW}"/>
<text x="270" y="${cardY + 39}" fill="#9CA8BC" font-size="16" font-weight="700" letter-spacing="0.6" font-family="sans-serif">${esc(T.lbl_temp)}</text>
<text x="266" y="${cardY + 128}" fill="#F3F5F9" font-size="58" font-weight="300" font-family="sans-serif">${esc(targetText)}</text>
<text x="266" y="${cardY + 168}" fill="${targetSubColor}" font-size="18" font-weight="${heaterOn || hotOn ? '600' : '400'}" font-family="sans-serif">${esc(targetSub)}</text>
<rect x="266" y="${cardY + 252}" width="174" height="38" rx="14" fill="${heaterOn ? 'rgba(255,138,61,0.18)' : '#1A2639'}" stroke="${heaterOn ? '#FF8A3D' : '#2A3A55'}"/>
<text x="353" y="${cardY + 277}" text-anchor="middle" fill="${heaterOn ? '#FF8A3D' : '#9CA8BC'}" font-size="16" font-weight="600" font-family="sans-serif">${esc(heaterOn ? T.heat_on : T.heat_off)}</text>

<rect x="472" y="${cardY}" width="210" height="${cardH}" rx="20" fill="#131D2E" stroke="${spdStroke}" stroke-width="${spdStrokeW}"/>
<text x="494" y="${cardY + 39}" fill="#9CA8BC" font-size="16" font-weight="700" letter-spacing="0.8" font-family="sans-serif">${esc(T.lbl_spd)}</text>
<text x="490" y="${cardY + 128}" fill="#F3F5F9" font-size="58" font-weight="300" font-family="sans-serif">${speedNum}</text>
<text x="490" y="${cardY + 168}" fill="${speedSubColor}" font-size="18" font-weight="${motorOn ? '600' : '400'}" font-family="sans-serif">${esc(speedDesc)}</text>

<rect x="490" y="${cardY + 206}" width="174" height="36" rx="18" fill="${reverseOn ? '#FF8A3D' : '#1A2639'}" stroke="${reverseOn ? '#FF8A3D' : '#2A3A55'}"/>
<text x="577" y="${cardY + 230}" text-anchor="middle" fill="${reverseOn ? '#070E1B' : '#F3F5F9'}" font-size="15.5" font-weight="600" font-family="sans-serif">${esc(reverseOn ? T.dir_rev : T.dir_fwd)}</text>

<rect x="490" y="${cardY + 252}" width="174" height="36" rx="18" fill="#1A2639" stroke="#2A3A55"/>
<text x="577" y="${cardY + 276}" text-anchor="middle" fill="#9CA8BC" font-size="15.5" font-weight="600" font-family="sans-serif">${esc(isWhisk ? T.acc_whisk : T.acc_blade)}</text>

<rect x="700" y="78" width="300" height="498" rx="22" fill="#131D2E" stroke="#2A3A55" stroke-width="1.5"/>
<path d="M 776.46 297.54 A 104 104 0 1 1 923.54 297.54" fill="none" stroke="#223048" stroke-width="14" stroke-linecap="round"/>
<path d="M 776.46 297.54 A 104 104 0 1 1 923.54 297.54" fill="none" stroke="${ringColor}" stroke-width="14" stroke-linecap="round" stroke-dasharray="${ringLen.toFixed(3)} 653.451" stroke-dashoffset="${ringOffset.toFixed(3)}"/>
${targetTick}
<text x="850" y="226" text-anchor="middle" fill="#F3F5F9" font-size="${tempKnown ? '56' : '44'}" font-weight="300" font-family="sans-serif">${esc(tempDisplay)}</text>
<text x="850" y="258" text-anchor="middle" fill="${hotOn ? '#FF5A5F' : '#9CA8BC'}" font-size="17" font-weight="${hotOn ? '700' : '400'}" font-family="sans-serif">${esc(tempSub)}</text>
${rpmBars}

<line x1="726" y1="382" x2="974" y2="382" stroke="#223048" stroke-width="1.5"/>
<text x="850" y="422" text-anchor="middle" fill="#F3F5F9" font-size="22" font-weight="400" font-family="sans-serif">${esc(T.scale_lbl)} : ${esc(weightText)}</text>
<text x="850" y="452" text-anchor="middle" fill="${scaleColor}" font-size="15" font-weight="600" font-family="sans-serif">${esc(scaleTag)}</text>

<rect x="24" y="424" width="658" height="84" rx="16" fill="#131D2E" stroke="#2A3A55" stroke-width="1.5"/>
<text x="42" y="456" fill="#F3F5F9" font-size="18" font-weight="600" font-family="sans-serif">${esc(ctxLine1)}</text>
${ctxBadge ? `<rect x="524" y="436" width="142" height="28" rx="14" fill="rgba(255,138,61,0.18)" stroke="#FF8A3D" stroke-width="1"/><text x="595" y="455" text-anchor="middle" fill="#FF8A3D" font-size="13.5" font-weight="600" font-family="sans-serif">${esc(ctxBadge)}</text>` : ''}
<text x="42" y="489" fill="#9CA8BC" font-size="15.5" font-family="sans-serif">${esc(ctxLine2)}</text>

${pillsSvg}
</svg>`;
]]]"""


def toque_button(entities: dict[str, str], key: str, label: str,
                 x0: float, y0: float, x1: float, y1: float,
                 active_bg: str, active_fg: str, active_border: str) -> dict:
    entity = entities[key]
    left, top, width, height = screen_box(x0, y0, x1, y1)
    icon_svg = BUTTON_ICONS[key]
    btn_js = f"""[[[
const off = entity?.state === 'unavailable';
const bg = off ? '#223048' : '{active_bg}';
const bd = off ? '#2A3A55' : '{active_border}';
const fg = off ? '#66738A' : '{active_fg}';
const op = off ? '0.45' : '1';
return `<svg viewBox="0 0 84 68" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}" style="opacity:${{op}}">
<rect x="2" y="2" width="80" height="64" rx="18" fill="${{bg}}" stroke="${{bd}}" stroke-width="2"/>
{icon_svg}
<text x="42" y="56" text-anchor="middle" fill="${{fg}}" font-size="18" font-weight="700" font-family="sans-serif">{label}</text>
</svg>`;
]]]"""
    return {
        'type': 'custom:button-card',
        'entity': entity,
        'name': label,
        'show_name': False,
        'show_icon': False,
        'triggers_update': [entity, entities['status'], entities['base_link']],
        'tap_action': {
            'action': 'perform-action',
            'perform_action': 'button.press',
            'target': {'entity_id': entity},
        },
        'hold_action': {'action': 'more-info', 'entity': entity},
        'style': {'left': left, 'top': top, 'width': width, 'height': height, 'z-index': 25},
        'styles': {
            'card': [
                {'height': '100%'},
                {'padding': '0'},
                {'border': '0'},
                {'background': 'transparent'},
                {'box-shadow': 'none'},
                {'cursor': "[[[ return entity?.state === 'unavailable' ? 'default' : 'pointer'; ]]]"},
            ],
            'grid': [{'display': 'block'}, {'height': '100%'}],
            'custom_fields': {'btn': [{'width': '100%'}, {'height': '100%'}]},
        },
        'custom_fields': {'btn': btn_js},
    }


def screen_hit(entities: dict[str, str], asset_base: str, key: str, title: str,
               x0: float, y0: float, x1: float, y1: float) -> dict:
    left, top, width, height = screen_box(x0, y0, x1, y1)
    entity = entities[key]
    return {
        'type': 'image',
        'image': f'{asset_base}/touch-target.svg',
        'filter': 'none',
        'title': title,
        'tap_action': {'action': 'more-info', 'entity': entity},
        'hold_action': {'action': 'more-info', 'entity': entity},
        'style': {'left': left, 'top': top, 'width': width, 'height': height, 'z-index': 24, 'cursor': 'pointer'},
    }


def build_card(prefix: str = 'monsieur_cuisine_connect_', lang: str = 'en', asset_base: str = '/local/toque') -> dict:
    asset_base = asset_base.rstrip('/')
    entities = make_entities(prefix)
    all_entities = list(entities.values())
    elements = [
        {
            'type': 'custom:button-card',
            'entity': entities['status'],
            'name': 'Monsieur Cuisine Connect Toque screen',
            'show_name': False,
            'show_icon': False,
            'triggers_update': all_entities,
            'update_timer': '30s',
            'tap_action': {'action': 'none'},
            'hold_action': {'action': 'none'},
            'style': {
                'left': f"{SCREEN_RECT['left']:.4f}%",
                'top': f"{SCREEN_RECT['top']:.4f}%",
                'width': f"{SCREEN_RECT['width']:.4f}%",
                'height': f"{SCREEN_RECT['height']:.4f}%",
                'transform-origin': '0 0',
                'transform': 'none',
                'z-index': 14,
                'pointer-events': 'none',
            },
            'styles': {
                'card': [
                    {'background': '#070E1B'},
                    {'border': '0'},
                    {'border-radius': '4px'},
                    {'box-shadow': 'none'},
                    {'padding': '0'},
                    {'height': '100%'},
                    {'overflow': 'hidden'},
                ],
                'grid': [{'display': 'block'}, {'height': '100%'}],
                'custom_fields': {'screen': [{'width': '100%'}, {'height': '100%'}]},
            },
            'custom_fields': {'screen': build_screen_js(prefix, lang)},
        },
        toque_button(entities, 'pause', 'Pause', 716, 488, 800, 558, '#FF8A3D', '#070E1B', '#FF8A3D'),
        toque_button(entities, 'stop', 'Stop', 808, 488, 892, 558, '#FF5A5F', '#FFFFFF', '#FF5A5F'),
        toque_button(entities, 'tare', 'Tare', 900, 488, 984, 558, '#223048', '#5CC8FF', '#5CC8FF'),
        screen_hit(entities, asset_base, 'status', 'Toque status', 18, 12, 270, 62),
        screen_hit(entities, asset_base, 'hot_contents', 'Bowl temperature alert', 434, 14, 574, 58),
        screen_hit(entities, asset_base, 'lid_open', 'Lid state', 584, 14, 756, 58),
        screen_hit(entities, asset_base, 'base_link', 'Base link', 766, 14, 1004, 58),
        screen_hit(entities, asset_base, 'time_remaining', 'Remaining time', 24, 78, 234, 410),
        screen_hit(entities, asset_base, 'target_temperature', 'Target temperature', 248, 78, 458, 410),
        screen_hit(entities, asset_base, 'speed_level', 'Speed level', 472, 78, 682, 410),
        screen_hit(entities, asset_base, 'temperature', 'Measured bowl temperature', 706, 84, 994, 376),
        screen_hit(entities, asset_base, 'weight', 'Scale weight', 706, 386, 994, 476),
        screen_hit(entities, asset_base, 'program', 'Program / active recipe', 24, 424, 682, 508),
        screen_hit(entities, asset_base, 'lid_open', 'Lid status pill', 24, 524, 178, 576),
        screen_hit(entities, asset_base, 'bowl_present', 'Bowl status pill', 192, 524, 346, 576),
        screen_hit(entities, asset_base, 'motor', 'Motor status pill', 360, 524, 514, 576),
        screen_hit(entities, asset_base, 'heater', 'Heater status pill', 528, 524, 682, 576),
    ]
    return {
        'type': 'picture-elements',
        'image': f'{asset_base}/monsieur-cuisine-connect-frame.svg',
        'elements': elements,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Generate standalone Toque Companion Lovelace card YAML.')
    parser.add_argument('--prefix', default='monsieur_cuisine_connect_', help='Entity ID prefix after domain (default: monsieur_cuisine_connect_)')
    parser.add_argument('--lang', choices=('en', 'fr'), default='en', help='UI language (default: en)')
    parser.add_argument('--asset-base', default='/local/toque', help='Home Assistant /local asset base URL (default: /local/toque)')
    parser.add_argument('--out', help='Output YAML file path (prints to stdout if omitted)')
    args = parser.parse_args()

    card = build_card(prefix=args.prefix, lang=args.lang, asset_base=args.asset_base)
    header = (
        f"# Toque Companion — Monsieur Cuisine Connect interactive tile ({args.lang})\n"
        f"# Entity prefix: {args.prefix} | Assets: {args.asset_base.rstrip('/')}/\n"
        f"# Requires: custom:button-card (HACS) and SVG files under /config/www/toque/\n"
    )
    rendered = header + yaml.safe_dump(card, sort_keys=False, allow_unicode=True, width=120)
    if args.out:
        Path(args.out).write_text(rendered, encoding='utf8')
    else:
        sys.stdout.write(rendered)


if __name__ == '__main__':
    main()
