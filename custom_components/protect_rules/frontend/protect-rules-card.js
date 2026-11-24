/**
 * protect-rules-card — UniFi Protect's Alarm Manager as a table.
 *
 * One row per rule: on/off, what triggers it, what it does, hits in the last
 * 24 h, when it last fired, my push / email notifications, the repeat
 * cooldown and which devices it covers. Search, category filters, sortable
 * columns. A row opens a detail dialog (Trigger / Scope / Action).
 *
 * Here you can: turn a rule on/off, set push and email, set the repeat
 * cooldown, and add, edit or delete rules. The rule form mirrors Protect's:
 * trigger tabs (ID, Objects, Activity, Webhook, Sensors, System) with several
 * triggers per rule, include / exclude device scope, and one or more actions
 * (Notify, Webhook, Light, PTZ: preset, patrol or auto-tracking). To act in Home
 * Assistant when a rule fires, trigger an HA automation from the rule's
 * "fired" event entity.
 *
 * A device in scope can be narrowed to its zones, lines or loiter zones.
 *
 * Still set up in Protect: drawing zones, schedules, plate/face matching by
 * name, doorbell-button rules, and sound, unlock and Slack actions. Editing here keeps
 * whatever of those a rule already has.
 *
 * Needs custom_components/protect_rules (websocket commands
 * protect_rules/subscribe, /update, /create and /delete). Admin users only.
 *
 *   type: custom:protect-rules-card
 *
 * Comes with the integration, which serves it and has Home Assistant load
 * it (custom_components/protect_rules/cards.py): no dashboard resource to add.
 */

const OPTS_KEY = "protect-rules-card:opts:v1";
const DEFAULT_OPTS = { cat: "all", sort: "hits", dir: -1, triggered: false, notifying: false };

const CATS = [
  ["all", "All", "mdi:shield-alert-outline"],
  ["detect", "Detections", "mdi:account-eye"],
  ["sound", "Sounds", "mdi:waveform"],
  ["safety", "Safety", "mdi:fire-alert"],
  ["sensor", "Sensors", "mdi:leak"],
  ["system", "System", "mdi:cog-outline"],
  ["other", "Other", "mdi:webhook"],
];

// trigger source -> [label, icon]
const TRIGGERS = {
  person: ["Person", "mdi:walk"],
  vehicle: ["Vehicle", "mdi:car"],
  animal: ["Animal", "mdi:paw"],
  package: ["Package", "mdi:package-variant-closed"],
  motion: ["Motion", "mdi:motion-sensor"],
  ring: ["Doorbell ring", "mdi:doorbell"],
  face_of_interest: ["Person of interest", "mdi:face-recognition"],
  license_plate_of_interest: ["Vehicle of interest", "mdi:card-text-outline"],
  audio_alarm_smoke: ["Smoke alarm sound", "mdi:smoke-detector-variant"],
  audio_alarm_co: ["CO alarm sound", "mdi:molecule-co"],
  audio_alarm_bark: ["Barking", "mdi:dog"],
  audio_alarm_car_horn: ["Car horn", "mdi:bullhorn"],
  audio_alarm_glass_break: ["Glass breaking", "mdi:glass-fragile"],
  audio_alarm_speak: ["Speaking", "mdi:account-voice"],
  audio_alarm_baby_cry: ["Baby crying", "mdi:baby-face-outline"],
  audio_alarm_siren: ["Siren", "mdi:alarm-light"],
  audio_alarm_burglar: ["Burglar alarm sound", "mdi:alarm-bell"],
  sensor_battery_low: ["Sensor battery low", "mdi:battery-alert"],
  sensor_alarm: ["Sensor alarm", "mdi:alarm-light-outline"],
  sensor_door_opened: ["Opened", "mdi:door-open"],
  sensor_door_closed: ["Closed", "mdi:door-closed"],
  sensor_water_leak: ["Water leak", "mdi:water-alert"],
  sensor_extreme_value: ["Extreme reading", "mdi:thermometer-alert"],
  webhook: ["Webhook", "mdi:webhook"],
  face_unknown: ["Unknown faces", "mdi:face-man-outline"],
  face_known: ["Known faces", "mdi:face-man"],
  face: ["Any face", "mdi:face-recognition"],
  license_plate_unknown: ["Unknown plates", "mdi:card-outline"],
  license_plate_known: ["Known plates", "mdi:card-text"],
  license_plate: ["Any license plate", "mdi:card-text-outline"],
  line_crossed: ["Line crossing", "mdi:vector-line"],
  object_idle_time: ["Object idle time", "mdi:timer-sand"],
  audio_alarm: ["Any sound", "mdi:waveform"],
  sensor_motion: ["Sensor motion", "mdi:motion-sensor"],
  sensor_alarm_smoke: ["Sensor smoke alarm", "mdi:smoke-detector-variant"],
  sensor_tamper: ["Sensor tampered", "mdi:alert-outline"],
  smart_loiter_detection: ["Loitering", "mdi:account-clock-outline"],
  person_idle_time: ["Person idle", "mdi:human-handsdown"],
  vehicle_idle_time: ["Vehicle idle", "mdi:car-clock"],
  smart_tamper_detection: ["Camera tampering", "mdi:cctv-off"],
  light_motion: ["Floodlight motion", "mdi:light-flood-down"],
  speed_mph: ["Speed over (mph)", "mdi:speedometer"],
  speed_kmph: ["Speed over (km/h)", "mdi:speedometer"],
  nfc_registered: ["Known NFC card", "mdi:nfc-variant"],
  nfc_unknown: ["Unknown NFC card", "mdi:nfc-variant-off"],
  fingerprint_registered: ["Known fingerprint", "mdi:fingerprint"],
  fingerprint_unknown: ["Unknown fingerprint", "mdi:fingerprint-off"],
  sensor_alarm_co: ["Sensor CO alarm", "mdi:molecule-co"],
  sensor_alarm_glassbreak: ["Sensor glass break", "mdi:glass-fragile"],
  sensor_button_pressed: ["Sensor button pressed", "mdi:gesture-tap-button"],
  admin_home: ["Admin arrives", "mdi:home-import-outline"],
  admin_away: ["Admin leaves", "mdi:home-export-outline"],
  admin_geolocation: ["Admin arrives or leaves", "mdi:map-marker-radius-outline"],
};
// where an admin's phone is: system-level triggers shown under ID > Geofence
const GEOFENCE = ["admin_home", "admin_away", "admin_geolocation"];
// triggers that belong to the console, not to a device
const SYSTEM_TRIGGERS = {
  admin_access: "Admin access",
  admin_settings_change: "Admin changed settings",
  admin_geolocation: "Admin arrives or leaves",
  admin_home: "Admin arrives",
  admin_away: "Admin leaves",
  admin_recording_clips_manipulations: "Recording or clip changed",
  device_issue: "Device issue",
  device_update_status_change: "Device update status",
  device_discovery: "Device discovered",
  device_adoption_state_changed: "Device adopted or removed",
  camera_utilization_limit: "Device limit reached",
  application_issue: "Application issue",
  device_disconnected: "Device disconnected",
  device_connected: "Device connected",
  device_reconnected: "Device reconnected",
  schedule: "Schedule",
};
// the trigger tabs of the rule form, like Protect's: [key, label, icon, [[heading, [trigger…]]…]]
const TABS = [
  ["id", "ID", "mdi:card-account-details-outline", [
    ["Person ID", ["face_unknown", "face_known", "face_of_interest"]],
    ["Vehicle ID", ["license_plate_unknown", "license_plate_known", "license_plate_of_interest"]],
    ["Geofence", GEOFENCE],
  ]],
  ["objects", "Objects", "mdi:walk", [[null, ["person", "vehicle", "package", "animal"]]]],
  ["activity", "Activity", "mdi:motion-sensor", [
    [null, ["motion", "line_crossed", "smart_loiter_detection", "person_idle_time", "vehicle_idle_time", "speed_mph", "smart_tamper_detection", "ring", "light_motion"]],
    ["Access", ["nfc_registered", "nfc_unknown", "fingerprint_registered", "fingerprint_unknown"]],
    ["Sound", ["audio_alarm", "audio_alarm_speak", "audio_alarm_bark", "audio_alarm_baby_cry", "audio_alarm_car_horn", "audio_alarm_glass_break", "audio_alarm_siren", "audio_alarm_burglar", "audio_alarm_smoke", "audio_alarm_co"]],
  ]],
  ["webhook", "Webhook", "mdi:webhook", [[null, ["webhook"]]]],
  ["sensors", "Sensors", "mdi:leak", [[null, ["sensor_motion", "sensor_door_opened", "sensor_door_closed", "sensor_alarm", "sensor_alarm_smoke", "sensor_water_leak", "sensor_alarm_co", "sensor_alarm_glassbreak", "sensor_extreme_value", "sensor_battery_low", "sensor_tamper", "sensor_button_pressed"]]]],
  ["system", "System", "mdi:cog-outline", [[null, Object.keys(SYSTEM_TRIGGERS).filter((k) => !GEOFENCE.includes(k))]]],
];
// ---- schedules: Protect stores one entry per day and time range
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
// entries -> [{ days: [0-6…], start: [h, m], end: [h, m] }], days sharing a time
// range merged; null when it holds something this form can't show
function schedBlocks(list) {
  const by = new Map();
  for (const item of list || []) {
    const sc = item && item.schedule;
    if (!sc || sc.unit !== "day_of_week" || !sc.and || sc.and.unit !== "time_range" || item.isDisabled) return null;
    const [a, b] = sc.and.values || [];
    if (!Array.isArray(a) || !Array.isArray(b)) return null;
    const key = JSON.stringify([a, b]);
    if (!by.has(key)) by.set(key, { days: new Set(), start: a, end: b });
    for (const d of sc.values || []) by.get(key).days.add(d);
  }
  return [...by.values()]
    .map((b) => ({ days: [...b.days].sort((x, y) => x - y), start: b.start, end: b.end }))
    .sort((x, y) => x.start[0] * 60 + x.start[1] - (y.start[0] * 60 + y.start[1]));
}
function clock([h, m]) {
  return new Date(2000, 0, 1, h, m).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
function daysLabel(days) {
  const k = days.join("");
  if (k === "0123456") return "Every day";
  if (k === "12345") return "Weekdays";
  if (k === "06") return "Weekends";
  return days.map((d) => DAYS[d]).join(", ");
}
function blocksText(blocks) {
  return blocks.map((b) => `${daysLabel(b.days)} ${clock(b.start)} – ${clock(b.end)}`).join(" · ");
}
// which named schedule (if any) a rule's schedule is a copy of
function schedMatch(list, named) {
  const key = JSON.stringify(schedBlocks(list));
  return key === "null" ? null : (named || []).find((s) => JSON.stringify(schedBlocks(s.schedules)) === key) || null;
}
const pad = (x) => String(x).padStart(2, "0");

// ---- narrowing a trigger to specific faces / vehicles / people.
// picks: { <trigger>: Set(ids) }, plus "geo": Set(user ids) for whichever
// geofence trigger is on. Protect stores one condition per id.
const PICK_LISTS = { face_known: "faces", license_plate_known: "vehicles" };
function picksFrom(conds) {
  const picks = {};
  for (const c of conds || []) {
    if (!c || c.value == null || /^speed_/.test(c.source || "") || c.source === "webhook") continue;
    const key = GEOFENCE.includes(c.source) ? "geo" : c.source;
    (picks[key] = picks[key] || new Set()).add(String(c.value));
  }
  return picks;
}
function picked(st, k) {
  const set = st.picks[GEOFENCE.includes(k) ? "geo" : k];
  return set && set.size ? [...set] : null;
}
function picksKey(st) {
  return Object.keys(st.picks).sort().map((k) => [k, [...st.picks[k]].sort()]).filter(([, v]) => v.length);
}

// device, system and webhook triggers can't share a rule
function trigGroup(k) {
  return k === "webhook" ? "webhook" : k in SYSTEM_TRIGGERS ? "system" : "device";
}
// turning it back afterwards: [button label, wording on the rule page]
const ACTIONS = {
  SEND_NOTIFICATION: ["Notify", "mdi:bell-outline"],
  SET_LIGHT: ["Light", "mdi:lightbulb-on-outline"],
  HTTP_REQUEST: ["Webhook", "mdi:webhook"],
  PLAY_SOUND: ["Sound", "mdi:volume-high"],
  PLAY_SPEAKER: ["Sound", "mdi:volume-high"],
  UNLOCK: ["Unlock", "mdi:lock-open-variant-outline"],
  PTZ: ["PTZ", "mdi:rotate-3d-variant"],
};
const COOLDOWNS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 360, 720, 1440];

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const title = (s) => String(s || "").replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());

function sources(rule) {
  // unique: a rule narrowed to several faces has one condition per face
  return [...new Set((rule.conditions || []).map((c) => (c.condition || {}).source || (c.condition || {}).type).filter(Boolean))];
}
function category(rule) {
  const s = sources(rule)[0] || "";
  if (s === "audio_alarm_smoke" || s === "audio_alarm_co") return "safety";
  if (s.startsWith("audio_")) return "sound";
  if (s.startsWith("sensor_")) return "sensor";
  if (/^(admin|device|application|camera_utilization|schedule)/.test(s)) return "system";
  if (s === "webhook") return "other";
  return "detect";
}
function trigLabel(s) {
  return (TRIGGERS[s] || [SYSTEM_TRIGGERS[s] || title(s)])[0];
}
function trigIcon(rule) {
  const s = sources(rule)[0];
  if (TRIGGERS[s]) return TRIGGERS[s][1];
  return { system: "mdi:cog-outline", sensor: "mdi:leak", sound: "mdi:waveform" }[category(rule)] || "mdi:shield-alert-outline";
}
function receiver(rule) {
  for (const a of rule.actions || []) {
    if (a.type !== "SEND_NOTIFICATION") continue;
    const recs = (a.metadata || {}).receivers || [];
    return recs.find((r) => r.user === rule.userId) || recs[0] || null;
  }
  return null;
}
function minutes(m) {
  if (m < 1) return `${Math.round(m * 60)} sec`;
  if (m < 60) return `${m} min`;
  return m % 60 === 0 ? `${m / 60} h` : `${(m / 60).toFixed(1)} h`;
}
function ago(ms) {
  if (!ms) return "—";
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

const STYLE = `
  :host { display: block; padding: 16px; box-sizing: border-box; color: var(--primary-text-color);
    font-family: var(--ha-font-family-body, Roboto, sans-serif); }
  .wrap { max-width: 1500px; margin: 0 auto; }
  .bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 12px; }
  .stats { display: flex; flex-wrap: wrap; gap: 8px; margin-right: auto; }
  .stat { padding: 8px 14px; border-radius: 14px; border: 1px solid var(--divider-color, #2a2a2a);
    background: var(--card-background-color, #111); font-size: 12px; color: var(--secondary-text-color); }
  .stat b { display: block; font-size: 18px; font-weight: 600; color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
  input.search { font: inherit; font-size: 14px; color: inherit; background: var(--card-background-color, #111);
    border: 1px solid var(--divider-color, #333); border-radius: 999px; padding: 9px 14px; width: 220px; max-width: 100%; }
  input.search:focus { outline: none; border-color: var(--primary-color); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
  .chips .sep { width: 1px; background: var(--divider-color, #333); margin: 2px 4px; }
  button.chip { font: inherit; font-size: 13px; cursor: pointer; border-radius: 999px; padding: 6px 12px;
    border: 1px solid var(--divider-color, #333); background: var(--card-background-color, #111);
    color: var(--secondary-text-color); display: inline-flex; gap: 6px; align-items: center; }
  button.chip.on { color: var(--primary-text-color); border-color: var(--primary-color);
    background: color-mix(in srgb, var(--primary-color) 30%, transparent); }
  button.chip ha-icon { --mdc-icon-size: 16px; }
  button.chip .c { opacity: .7; font-variant-numeric: tabular-nums; }
  .panel { border: 1px solid var(--divider-color, #2a2a2a); border-radius: var(--ha-card-border-radius, 18px);
    background: var(--card-background-color, #111); overflow: hidden; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; font-size: 12px; font-weight: 500; color: var(--secondary-text-color); padding: 12px 12px;
    border-bottom: 1px solid var(--divider-color, #2a2a2a); white-space: nowrap; user-select: none; }
  th.s { cursor: pointer; }
  th.s:hover { color: var(--primary-text-color); }
  th .arrow { opacity: .9; margin-left: 2px; color: var(--primary-color); }
  td { padding: 9px 12px; border-bottom: 1px solid color-mix(in srgb, var(--divider-color, #2a2a2a) 60%, transparent); vertical-align: middle; }
  tr:last-child td { border-bottom: 0; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: color-mix(in srgb, var(--primary-color) 8%, transparent); }
  tr.off .name, tr.off .dim { opacity: .45; }
  .name { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .name ha-icon { --mdc-icon-size: 20px; color: var(--primary-color); flex: none; }
  .name .n { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .name .t { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .num { font-variant-numeric: tabular-nums; white-space: nowrap; }
  .hits { display: flex; align-items: center; gap: 8px; }
  .hits .v { min-width: 44px; text-align: right; font-variant-numeric: tabular-nums; }
  .hits .v.zero { color: var(--secondary-text-color); opacity: .6; }
  .hits .meter { flex: 1; min-width: 40px; max-width: 110px; height: 4px; border-radius: 2px; background: color-mix(in srgb, var(--divider-color, #333) 70%, transparent); }
  .hits .meter i { display: block; height: 100%; border-radius: 2px; background: var(--primary-color); }
  .dim { color: var(--secondary-text-color); white-space: nowrap; }
  .act { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
  .act ha-icon { --mdc-icon-size: 16px; }
  .sw { position: relative; width: 36px; height: 20px; border-radius: 10px; border: 0; cursor: pointer; padding: 0; flex: none;
    background: color-mix(in srgb, var(--secondary-text-color) 35%, transparent); transition: background .15s; vertical-align: middle; }
  .sw::after { content: ""; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: transform .15s; }
  .sw.on { background: var(--primary-color); }
  .sw.on::after { transform: translateX(16px); }
  .sw[disabled] { opacity: .4; cursor: default; }
  .ch { display: inline-grid; place-items: center; width: 32px; height: 32px; border-radius: 50%; border: 0; cursor: pointer;
    background: none; color: var(--secondary-text-color); opacity: .45; }
  .ch ha-icon { --mdc-icon-size: 18px; }
  .ch:hover { background: color-mix(in srgb, var(--primary-color) 15%, transparent); opacity: .9; }
  .ch.on { color: var(--primary-color); opacity: 1; background: color-mix(in srgb, var(--primary-color) 18%, transparent); }
  .busy { opacity: .5; pointer-events: none; }
  .empty { padding: 32px; text-align: center; color: var(--secondary-text-color); }
  .err { margin-bottom: 12px; padding: 10px 14px; border-radius: 12px; color: var(--error-color, #f87171);
    border: 1px solid color-mix(in srgb, var(--error-color, #f87171) 50%, transparent); }
  .err[hidden] { display: none; }
  @media (max-width: 1100px) { .c-scope, .c-cool { display: none; } }
  @media (max-width: 800px) { .c-act, .hits .meter { display: none; } :host { padding: 8px; } td, th { padding: 8px 8px; } input.search { width: 100%; } }
  @media (max-width: 560px) { .c-last { display: none; } .name .t { display: none; } }
`;

// the detail dialog uses the same frame as the History lightbox
const DLG_STYLE = `
  .backdrop { position: absolute; inset: 0; background: rgba(0,0,0,.55); }
  .lb { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
    width: min(max(60vw, 980px), calc(100vw - 24px)); max-height: calc(100vh - 24px);
    background: #0a0a0a; border: 1px solid #262626; border-radius: 18px; overflow: hidden;
    box-shadow: 0 24px 64px rgba(0,0,0,.7); color: #f3f4f6; display: flex; flex-direction: column;
    font-family: var(--ha-font-family-body, Roboto, sans-serif); }
  .head { display: flex; gap: 12px; align-items: center; padding: 14px 18px; border-bottom: 1px solid #222; }
  .head ha-icon { color: var(--primary-color, #e0102a); }
  .title { font-size: 18px; font-weight: 600; }
  .sub { font-size: 12px; color: #9ca3af; }
  .spacer { flex: 1; }
  button.icon { cursor: pointer; border: 0; background: #1f1f1f; color: #fff; width: 40px; height: 40px;
    border-radius: 50%; display: grid; place-items: center; flex: none; }
  button.icon:hover { background: #2d2d2d; }
  .body { padding: 16px 18px; overflow: auto; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
  .box { border: 1px solid #262626; border-radius: 14px; padding: 14px; min-width: 0; }
  .box h3 { margin: 0 0 12px; font-size: 13px; font-weight: 600; color: #9ca3af; display: flex; align-items: center; gap: 8px; }
  .box h3 ha-icon { --mdc-icon-size: 18px; }
  .item { display: flex; align-items: center; gap: 10px; padding: 6px 0; font-size: 14px; min-width: 0; }
  .item ha-icon { --mdc-icon-size: 18px; color: #9ca3af; flex: none; }
  .item .k { color: #9ca3af; font-size: 12px; }
  .item .grow { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .pill { display: inline-block; padding: 3px 10px; border-radius: 999px; background: #1f1f1f; font-size: 13px; margin: 2px 4px 2px 0; }
  .box.wide { grid-column: 1 / -1; }
  .hist { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 6px 18px; }
  .hrow { display: flex; align-items: center; gap: 10px; padding: 5px 0; min-width: 0; font-size: 13px; }
  .hrow img, .hrow .noimg { width: 64px; height: 36px; border-radius: 6px; background: #1a1a1a; object-fit: cover; flex: none;
    display: grid; place-items: center; color: #6b7280; }
  .hrow img.none { visibility: hidden; }
  .hrow .noimg ha-icon { --mdc-icon-size: 18px; }
  .hrow .grow { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hrow .when { text-align: right; flex: none; }
  .hrow.bad b { color: #fca5a5; }
  .hrow.play { cursor: pointer; border-radius: 8px; }
  .hrow.play:hover { background: #1a1a1a; }
  .more-hist { margin-top: 10px; }
  .note { grid-column: 1 / -1; font-size: 12px; color: #9ca3af; }
  .sw { position: relative; width: 36px; height: 20px; border-radius: 10px; border: 0; cursor: pointer; padding: 0; flex: none; background: #3f3f46; transition: background .15s; }
  .sw::after { content: ""; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: transform .15s; }
  .sw.on { background: var(--primary-color, #e0102a); }
  .sw.on::after { transform: translateX(16px); }
  select { font: inherit; font-size: 13px; color: #f3f4f6; background: #111; border: 1px solid #333; border-radius: 999px; padding: 5px 10px; color-scheme: dark; }
  .busy { opacity: .5; pointer-events: none; }
  .foot { display: flex; gap: 10px; align-items: center; padding: 12px 18px; border-top: 1px solid #222; }
  .foot .msg { flex: 1; font-size: 13px; color: #fca5a5; }
  button.btn { font: inherit; font-size: 14px; font-weight: 500; cursor: pointer; border-radius: 999px; padding: 8px 18px;
    border: 1px solid #333; background: #111; color: #f3f4f6; display: inline-flex; gap: 6px; align-items: center; }
  button.btn ha-icon { --mdc-icon-size: 18px; }
  button.btn.primary { background: var(--primary-color, #e0102a); border-color: transparent; color: #fff; }
  button.btn.danger { color: #fca5a5; }
  button.btn.danger.sure { background: #7f1d1d; color: #fff; border-color: transparent; }
  label.f { display: block; font-size: 12px; color: #9ca3af; margin: 10px 0 4px; }
  label.f:first-child { margin-top: 0; }
  input.txt, select.wide { font: inherit; font-size: 14px; color: #f3f4f6; background: #111; border: 1px solid #333;
    border-radius: 10px; padding: 8px 10px; width: 100%; box-sizing: border-box; color-scheme: dark; }
  .pick { display: flex; flex-wrap: wrap; gap: 6px; }
  .pick button { font: inherit; font-size: 13px; cursor: pointer; border-radius: 999px; padding: 5px 12px; border: 1px solid #333; background: #111; color: #9ca3af;
    display: inline-flex; gap: 6px; align-items: center; }
  .pick button ha-icon { --mdc-icon-size: 16px; }
  .pick button[disabled], .tab[disabled] { opacity: .3; cursor: not-allowed; }
  .pick button.gone { border-style: dashed; color: #fca5a5; }
  .k.warn, .body .k.warn { color: #fca5a5; }
  .pick button.on { color: #fff; border-color: var(--primary-color, #e0102a); background: color-mix(in srgb, var(--primary-color, #e0102a) 30%, transparent); }
  [hidden] { display: none !important; }
  .mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; overflow-wrap: anywhere; user-select: all; margin-bottom: 6px; }
  button.btn.small { font-size: 12px; padding: 4px 10px; }
  button.btn.small ha-icon { --mdc-icon-size: 14px; }
  .tabs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-bottom: 10px; }
  .tab { font: inherit; font-size: 12px; cursor: pointer; border-radius: 10px; padding: 8px 4px; border: 1px solid #333; background: #111; color: #9ca3af;
    display: flex; flex-direction: column; align-items: center; gap: 4px; position: relative; }
  .tab ha-icon { --mdc-icon-size: 18px; }
  .tab.on { color: #fff; border-color: var(--primary-color, #e0102a); }
  .tab .cnt { position: absolute; top: 4px; right: 6px; min-width: 16px; height: 16px; border-radius: 8px; font-size: 10px; line-height: 16px;
    background: var(--primary-color, #e0102a); color: #fff; }
  .abox { border: 1px solid #262626; border-radius: 12px; padding: 10px; margin-bottom: 8px; }
  .ahead { display: flex; gap: 6px; align-items: flex-start; margin-bottom: 6px; }
  .ahead .pick { flex: 1; }
  .ahead .x { border: 0; background: none; color: #9ca3af; cursor: pointer; padding: 4px; border-radius: 50%; }
  .ahead .x:hover { color: #fff; background: #1f1f1f; }
  .ahead .x ha-icon { --mdc-icon-size: 16px; }
  .schedbox { margin-top: 12px; border-top: 1px solid #222; padding-top: 4px; }
  .srow { border: 1px solid #262626; border-radius: 12px; padding: 8px; margin-top: 8px; }
  .sdays button { min-width: 38px; justify-content: center; padding-left: 0; padding-right: 0; }
  .stimes { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
  .stimes input { width: 130px; color-scheme: dark; }
  .stimes .x { border: 0; background: none; color: #9ca3af; cursor: pointer; padding: 4px; border-radius: 50%; margin-left: auto; }
  .stimes .x ha-icon { --mdc-icon-size: 16px; }
  .andbox { border: 1px solid #262626; border-radius: 12px; padding: 10px; margin: 10px 0 4px; }
  .andbox .ahead { align-items: center; }
  .andbox .grow { flex: 1; }
  .andtag { font-size: 11px; font-weight: 700; letter-spacing: .04em; padding: 2px 8px; border-radius: 999px; color: #fff;
    background: color-mix(in srgb, var(--primary-color, #e0102a) 35%, transparent); border: 1px solid var(--primary-color, #e0102a); }
  .andline { display: flex; align-items: center; gap: 8px; margin: 10px 0 6px; }
  .zbox { border: 1px solid #262626; border-radius: 12px; padding: 10px; margin-top: 10px; }
  .zname { font-size: 13px; font-weight: 500; margin-bottom: 4px; }
  .dot { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
  button.link { font: inherit; font-size: 13px; border: 0; background: none; color: var(--primary-color, #e0102a); cursor: pointer; padding: 4px 0; }
  .body .k { font-size: 12px; color: #9ca3af; }
  @media (max-width: 800px) { .body { grid-template-columns: 1fr; } }
`;

class ProtectRulesCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    try {
      this._opts = { ...DEFAULT_OPTS, ...JSON.parse(localStorage.getItem(OPTS_KEY) || "{}") };
    } catch (e) {
      this._opts = { ...DEFAULT_OPTS };
    }
    this._query = "";
    this._rules = null;
    this._devices = {};
    this._busy = new Set();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._build();
      this._subscribe();
    }
  }

  getCardSize() {
    return 12;
  }

  connectedCallback() {
    if (this._dlg && !this._dlg.isConnected) document.body.appendChild(this._dlg);
    if (this._hass && !this._unsub) this._subscribe();
    this._tick = setInterval(() => this._rules && this._render(), 60000); // keep "5 min ago" fresh
  }

  disconnectedCallback() {
    clearInterval(this._tick);
    this._closeDetail();
    this._dlg?.remove();
    this._unsub?.then((u) => u()).catch(() => {});
    this._unsub = null;
  }

  // A device's name. One that was removed from Protect but is still named by
  // a rule is "<its name> (removed)", never blank or an id.
  _dev(mac) {
    return this._devices[mac] || (this._labels || {})[mac] || (this._gone(mac) ? "Removed device" : mac);
  }

  _gone(mac) {
    return !!this._removed && mac in this._removed;
  }

  // for pickers: an offline device is still in Protect and can be picked
  _pickName(mac) {
    return `${this._dev(mac)}${this._offline && this._offline.has(mac) ? " (offline)" : ""}`;
  }

  _save() {
    try {
      localStorage.setItem(OPTS_KEY, JSON.stringify(this._opts));
    } catch (e) {}
  }

  _subscribe() {
    this._unsub = this._hass.connection.subscribeMessage(
      (data) => {
        if (data.loaded === false) {
          // the integration is being reloaded (or isn't set up): the rules
          // come again on this same subscription once it is back
          this._unloaded = true;
          this._error("Protect Rules isn't loaded right now. The rules will come back by themselves when it is.", true);
          return;
        }
        this._unloaded = false;
        this._rules = data.rules || [];
        this._revs = data.revs || {}; // rule id -> what it looked like, sent back with an edit
        this._devices = data.devices || {}; // the devices Protect has now: { mac: name }
        this._labels = data.labels || {}; // a name for every device a rule names, also a removed one
        this._removed = data.removed || {}; // devices rules name that Protect no longer has
        this._offline = new Set(data.offline || []); // in Protect, but not connected
        this._zones = data.zones || {};
        this._ptz = data.ptz || {}; // PTZ cameras: { mac: { presets, patrols } }
        this._people = { faces: [], vehicles: [], users: [], ...(data.people || {}) }; // named faces / vehicles, geofence users
        this._schedules = data.schedules || []; // Protect's named schedules
        this._caps = data.caps || null; // device -> triggers it can produce (null: unknown, allow all)
        this._protectHost = data.protect_host || null;
        this._error(null);
        this._render();
        // rules fire all the time: only redraw the open dialog when its own
        // rule changed
        if (this._detailId) {
          const sig = JSON.stringify(this._rules.find((r) => r.id === this._detailId));
          if (sig !== this._detailSig) {
            this._detailSig = sig;
            this._renderDetail();
          }
        }
      },
      { type: "protect_rules/subscribe" }
    );
    this._unsub.catch((err) => {
      this._unsub = null;
      this._error(err?.code === "unauthorized" ? "Only admin users can see the alarm rules." : `Couldn't load the rules: ${err?.message || err}`);
    });
  }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `<style>${STYLE}</style>
      <div class="wrap">
        <div class="err" hidden></div>
        <div class="bar"><div class="stats"></div><input class="search" type="search" placeholder="Search rules"><button class="chip on add"><ha-icon icon="mdi:plus"></ha-icon>New rule</button></div>
        <div class="chips"></div>
        <div class="panel"><table>
          <thead><tr>
            <th></th>
            <th class="s" data-sort="name">Rule</th>
            <th class="s c-act" data-sort="action">Action</th>
            <th class="s" data-sort="hits">Hits (24 h)</th>
            <th class="s c-last" data-sort="last">Last triggered</th>
            <th>Notify me</th>
            <th class="s c-cool" data-sort="cool">Repeat</th>
            <th class="c-scope">Scope</th>
          </tr></thead>
          <tbody></tbody>
        </table><div class="empty" hidden></div></div>
      </div>`;
    root.querySelector(".search").oninput = (ev) => {
      this._query = ev.target.value.trim().toLowerCase();
      this._render();
    };
    root.querySelector(".add").onclick = () => this._openNew();
    for (const th of root.querySelectorAll("th.s")) {
      th.onclick = () => {
        const key = th.dataset.sort;
        if (this._opts.sort === key) this._opts.dir = -this._opts.dir;
        else {
          this._opts.sort = key;
          this._opts.dir = key === "name" || key === "action" ? 1 : -1;
        }
        this._save();
        this._render();
      };
    }
  }

  _error(text, stay) {
    const el = this.shadowRoot?.querySelector(".err");
    if (!el) return;
    el.hidden = !text;
    el.textContent = text || "";
    if (text && !stay) setTimeout(() => el.textContent === text && (el.hidden = !!this._rules), 8000);
  }

  // ---------------------------------------------------------------- table

  _info(rule) {
    const rec = receiver(rule);
    const ch = rec ? rec.channels || [] : [];
    const cd = rule.cooldown || {};
    const st = rule.status || {};
    const srcs = rule.sources || [];
    return {
      cat: category(rule),
      trig: sources(rule).map(trigLabel).join(" or "),
      action: (rule.actions || []).map((a) => (ACTIONS[a.type] || [title(a.type)])[0]).join(", ") || "—",
      actionIcon: (ACTIONS[(rule.actions || [])[0]?.type] || [null, "mdi:flash-outline"])[1],
      hits: st.total || 0,
      last: st.lastExecutedAt || 0,
      canNotify: !!rec,
      push: ch.includes("push"),
      email: ch.includes("email"),
      cool: cd.enable ? (cd.timeout || 0) / 60000 : 0,
      scope: srcs.length ? `${srcs[0].type === "exclude" ? "All except " : ""}${srcs.map((s) => this._dev(s.device)).join(", ")}` : category(rule) === "system" || category(rule) === "other" ? "System" : "All devices",
    };
  }

  _render() {
    const root = this.shadowRoot;
    if (!root || !this._rules) return;
    const o = this._opts;
    const all = this._rules.map((r) => ({ r, i: this._info(r) }));

    root.querySelector(".stats").innerHTML = [
      [all.length, "rules"],
      [all.filter((x) => x.r.enable).length, "on"],
      [all.filter((x) => x.i.hits > 0).length, "triggered in 24 h"],
      [all.filter((x) => x.r.enable && (x.i.push || x.i.email)).length, "notify me"],
    ].map(([n, l]) => `<div class="stat"><b>${n}</b>${l}</div>`).join("");

    const chips = root.querySelector(".chips");
    chips.innerHTML = "";
    for (const [key, name, icon] of CATS) {
      const n = key === "all" ? all.length : all.filter((x) => x.i.cat === key).length;
      if (!n) continue;
      const b = document.createElement("button");
      b.className = `chip${o.cat === key ? " on" : ""}`;
      b.innerHTML = `<ha-icon icon="${icon}"></ha-icon>${name}<span class="c">${n}</span>`;
      b.onclick = () => {
        o.cat = key;
        this._save();
        this._render();
      };
      chips.appendChild(b);
    }
    chips.insertAdjacentHTML("beforeend", '<span class="sep"></span>');
    for (const [key, name, icon] of [["triggered", "Triggered", "mdi:flash"], ["notifying", "Notifying", "mdi:bell-ring-outline"]]) {
      const b = document.createElement("button");
      b.className = `chip${o[key] ? " on" : ""}`;
      b.innerHTML = `<ha-icon icon="${icon}"></ha-icon>${name}`;
      b.onclick = () => {
        o[key] = !o[key];
        this._save();
        this._render();
      };
      chips.appendChild(b);
    }

    let rows = all.filter(
      (x) =>
        (o.cat === "all" || x.i.cat === o.cat) &&
        (!o.triggered || x.i.hits > 0) &&
        (!o.notifying || x.i.push || x.i.email) &&
        (!this._query || `${x.r.name} ${x.i.trig} ${x.i.action} ${x.i.scope}`.toLowerCase().includes(this._query))
    );
    const val = { name: (x) => x.r.name.toLowerCase(), action: (x) => x.i.action, hits: (x) => x.i.hits, last: (x) => x.i.last, cool: (x) => x.i.cool }[o.sort] || ((x) => x.i.hits);
    rows.sort((a, b) => {
      const [va, vb] = [val(a), val(b)];
      return (va < vb ? -1 : va > vb ? 1 : 0) * o.dir || a.r.name.localeCompare(b.r.name);
    });

    for (const th of root.querySelectorAll("th.s")) {
      th.querySelector(".arrow")?.remove();
      if (th.dataset.sort === o.sort) th.insertAdjacentHTML("beforeend", `<span class="arrow">${o.dir > 0 ? "▲" : "▼"}</span>`);
    }

    const max = Math.max(1, ...all.map((x) => x.i.hits));
    const body = root.querySelector("tbody");
    body.innerHTML = "";
    for (const { r, i } of rows) {
      const tr = document.createElement("tr");
      tr.className = `${r.enable ? "" : "off"}${this._busy.has(r.id) ? " busy" : ""}`;
      // a log-ish bar so a rule with 13 hits is still visible next to one with 4000
      const pct = i.hits ? Math.max(4, Math.round((Math.log10(i.hits + 1) / Math.log10(max + 1)) * 100)) : 0;
      tr.innerHTML = `
        <td><button class="sw${r.enable ? " on" : ""}" role="switch" aria-checked="${!!r.enable}" title="${r.enable ? "Rule is on" : "Rule is off"}"></button></td>
        <td><div class="name"><ha-icon icon="${trigIcon(r)}"></ha-icon><div style="min-width:0"><div class="n">${esc(r.name)}</div>${i.trig.toLowerCase() === r.name.toLowerCase() ? "" : `<div class="t">${esc(i.trig)}</div>`}</div></div></td>
        <td class="c-act dim"><span class="act"><ha-icon icon="${i.actionIcon}"></ha-icon>${esc(i.action)}</span></td>
        <td><div class="hits"><span class="v${i.hits ? "" : " zero"}">${i.hits.toLocaleString()}</span><span class="meter"><i style="width:${pct}%"></i></span></div></td>
        <td class="c-last dim" title="${i.last ? new Date(i.last).toLocaleString() : ""}">${ago(i.last)}</td>
        <td>${i.canNotify ? `<button class="ch push${i.push ? " on" : ""}" title="Push notification: ${i.push ? "on" : "off"}"><ha-icon icon="${i.push ? "mdi:bell-ring" : "mdi:bell-outline"}"></ha-icon></button><button class="ch email${i.email ? " on" : ""}" title="Email: ${i.email ? "on" : "off"}"><ha-icon icon="${i.email ? "mdi:email" : "mdi:email-outline"}"></ha-icon></button>` : '<span class="dim">—</span>'}</td>
        <td class="c-cool dim" title="${i.cool ? "Stays quiet this long after firing" : "Fires every time"}">${i.cool ? minutes(i.cool) : "—"}</td>
        <td class="c-scope dim">${esc(i.scope)}</td>`;
      tr.onclick = () => this._openDetail(r.id);
      tr.querySelector(".sw").onclick = (ev) => {
        ev.stopPropagation();
        this._update(r.id, { enable: !r.enable });
      };
      const push = tr.querySelector(".push");
      if (push) {
        push.onclick = (ev) => {
          ev.stopPropagation();
          this._update(r.id, { push: !i.push });
        };
        tr.querySelector(".email").onclick = (ev) => {
          ev.stopPropagation();
          this._update(r.id, { email: !i.email });
        };
      }
      body.appendChild(tr);
    }
    const empty = root.querySelector(".empty");
    empty.hidden = rows.length > 0;
    empty.textContent = rows.length ? "" : "No rules match.";
  }

  async _update(ruleId, changes) {
    if (this._busy.has(ruleId)) return;
    this._busy.add(ruleId);
    this._render();
    try {
      await this._hass.callWS({ type: "protect_rules/update", rule_id: ruleId, ...changes });
    } catch (err) {
      this._error(`Protect didn't accept the change: ${err?.message || err}`);
    } finally {
      this._busy.delete(ruleId);
      this._render();
      if (this._detailId) this._renderDetail();
    }
  }

  // --------------------------------------------------------------- detail

  _openDetail(id) {
    if (!this._dlg) {
      const host = document.createElement("div");
      host.style.cssText = "position:fixed;inset:0;z-index:9999;display:none";
      const root = host.attachShadow({ mode: "open" });
      root.innerHTML = `<style>${DLG_STYLE}</style><div class="backdrop"></div><div class="lb">
        <div class="head"><ha-icon class="ico"></ha-icon><div><div class="title"></div><div class="sub"></div></div><span class="spacer"></span>
          <button class="sw enable" role="switch" title="Rule on / off"></button>
          <button class="icon close" title="Close (Esc)"><ha-icon icon="mdi:close"></ha-icon></button></div>
        <div class="body"></div><div class="foot"><span class="msg"></span></div></div>`;
      root.querySelector(".close").onclick = () => this._askClose();
      root.querySelector(".backdrop").onclick = () => this._askClose();
      // a redraw that was held back while a dropdown was in use (see _renderDetail)
      root.addEventListener("focusout", () => setTimeout(() => this._detailLater && this._renderDetail()));
      window.addEventListener("keydown", (ev) => {
        if (this._player && this._player._isOpen()) return; // Esc closes the player first
        if ((this._detailId || this._new) && ev.key === "Escape") this._askClose();
      });
      document.body.appendChild(host);
      this._dlg = host;
    }
    this._detailId = id;
    this._detailShown = null; // opening always draws afresh
    this._new = null;
    this._dlg.style.display = "block";
    if (id) {
      if (!this._hist || this._hist.id !== id) this._hist = { id, rows: null, limit: 8 };
      this._renderDetail();
      this._loadHistory();
    }
  }

  // the last times this rule fired (Protect keeps them per rule)
  async _loadHistory() {
    const h = this._hist;
    if (!h || h.loading) return;
    h.loading = true;
    try {
      const res = await this._hass.callWS({ type: "protect_rules/history", rule_id: h.id, limit: h.limit + 1 });
      h.more = res.history.length > h.limit;
      h.rows = res.history.slice(0, h.limit);
      h.error = null;
    } catch (err) {
      h.error = (err && err.message) || "Couldn't load";
    }
    h.loading = false;
    h.last = ((this._rules || []).find((r) => r.id === h.id)?.status || {}).lastExecutedAt;
    if (this._hist === h && this._detailId === h.id) this._renderDetail();
  }

  _historyHtml(rule) {
    const h = this._hist;
    if (!h || h.id !== rule.id) return "";
    // fired again while the dialog is open: refresh the list
    if (h.rows && !h.loading && (rule.status || {}).lastExecutedAt !== h.last) this._loadHistory();
    let body;
    if (h.error) body = `<div class="k">${esc(h.error)}</div>`;
    else if (!h.rows) body = `<div class="k">Loading…</div>`;
    else if (!h.rows.length) body = `<div class="k">This rule hasn't fired recently.</div>`;
    else {
      body = `<div class="hist">${h.rows
        .map((e) => {
          const t = TRIGGERS[e.trigger] || [trigLabel(e.trigger || ""), "mdi:shield-alert-outline"];
          const where = [e.device, ...(e.zones || []), e.event_type === "smartDetectLoiterZone" ? "Loitering" : ""].filter(Boolean).join(" · ");
          const d = new Date(e.at);
          const time = d.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit", second: "2-digit" });
          return `<div class="hrow${e.status && e.status !== "ok" ? " bad" : ""}${e.event_id ? " play" : ""}"${e.event_id ? ` data-event="${esc(e.event_id)}" title="Play the recording"` : ""}>
            ${e.event_id ? `<img data-thumb="${esc(e.event_id)}" alt="">` : `<span class="noimg"><ha-icon icon="${t[1]}"></ha-icon></span>`}
            <span class="grow"><b>${esc(t[0])}</b>${e.score ? ` <span class="k">${e.score}%</span>` : ""}<div class="k">${esc(where || "System")}</div></span>
            <span class="when" title="${esc(d.toLocaleString())}">${esc(ago(e.at))}<div class="k">${esc(time)}</div></span>
            ${e.status && e.status !== "ok" ? `<span class="pill">${esc(e.status)}</span>` : ""}</div>`;
        })
        .join("")}</div>${h.more ? `<button class="btn small more-hist">Show more</button>` : ""}`;
    }
    return `<div class="box wide"><h3><ha-icon icon="mdi:history"></ha-icon>Recent triggers</h3>${body}</div>`;
  }

  // the History player from the detections card, used here as a player only
  async _playTrigger(ids, index) {
    if (!this._player) {
      if (!customElements.get("protect-detection-card")) {
        const msg = this._dlg.shadowRoot.querySelector(".foot .msg");
        if (msg) msg.textContent = "The detections card isn't loaded, so recordings can't be played here.";
        return;
      }
      const el = document.createElement("protect-detection-card");
      el.setConfig({ player_only: true });
      el.hass = this._hass;
      el.style.display = "none";
      this.shadowRoot.appendChild(el);
      this._player = el;
    }
    this._player.hass = this._hass;
    const rule = (this._rules || []).find((r) => r.id === this._detailId);
    this._player.playEvents(ids, index, rule ? rule.name : "Detection");
  }

  _historyWire(root) {
    const more = root.querySelector(".more-hist");
    if (more)
      more.onclick = () => {
        this._hist.limit += 20;
        more.textContent = "Loading…";
        this._loadHistory();
      };
    // a trigger that came from a detection plays its recording; ‹ › then
    // step through the rule's other triggers
    const playable = [...root.querySelectorAll(".hrow.play")];
    const ids = playable.map((el) => el.dataset.event);
    playable.forEach((el, i) => (el.onclick = () => this._playTrigger(ids, i)));
    this._thumbs = this._thumbs || new Map();
    for (const img of root.querySelectorAll("img[data-thumb]")) {
      const url = `/api/protect_detections/thumb/event/${img.dataset.thumb}`;
      let src = this._thumbs.get(url);
      if (!src) {
        src = this._hass
          .fetchWithAuth(url)
          .then((r) => (r.ok ? r.blob() : Promise.reject(r.status)))
          .then((b) => URL.createObjectURL(b));
        this._thumbs.set(url, src);
      }
      src.then((u) => (img.src = u)).catch(() => img.classList.add("none"));
    }
  }

  _closeDetail() {
    this._discardAt = 0;
    this._detailShown = null; // the next open draws afresh
    this._detailLater = false;
    this._detailSig = null;
    this._detailId = null;
    this._new = null;
    if (this._dlg) this._dlg.style.display = "none";
  }

  _renderDetail() {
    if (!this._detailId) return;
    const rule = (this._rules || []).find((r) => r.id === this._detailId);
    if (!rule) return this._closeDetail();
    const i = this._info(rule);
    const root = this._dlg.shadowRoot;
    root.querySelector(".lb").classList.toggle("busy", this._busy.has(rule.id));
    root.querySelector(".ico").setAttribute("icon", trigIcon(rule));
    root.querySelector(".title").textContent = rule.name;
    root.querySelector(".sub").textContent = `${i.hits.toLocaleString()} hits in 24 h · last triggered ${ago(i.last)}`;
    const en = root.querySelector(".enable");
    en.hidden = false;
    en.classList.toggle("on", !!rule.enable);
    en.onclick = () => this._update(rule.id, { enable: !rule.enable });

    // Redrawing the body would close an open dropdown and reset an armed
    // "Delete from Protect?": hold it back until that control is done with.
    if (this._detailShown === rule.id && (root.activeElement?.matches?.("select") || root.querySelector(".del.sure"))) {
      this._detailLater = true;
      return;
    }
    this._detailLater = false;
    this._detailShown = rule.id;

    const dev = (mac) => esc(this._dev(mac));
    // the name, for a condition narrowed to one face / vehicle / person
    const who = (c) => {
      if (c.value == null || /^speed_/.test(c.source || "") || c.source === "webhook") return "";
      const list = GEOFENCE.includes(c.source) ? this._people.users : this._people[PICK_LISTS[c.source]] || [];
      return `<div class="k">Only ${esc((list.find((x) => x.id === String(c.value)) || {}).name || c.value)}</div>`;
    };
    const spec = (c) => (c.value != null && { face_known: "Specific face", license_plate_known: "Specific vehicle" }[c.source]) || "";
    const trig = (rule.conditions || [])
      .map((c) => {
        const s = (c.condition || {}).source || (c.condition || {}).type;
        const t = TRIGGERS[s] || [trigLabel(s), "mdi:shield-alert-outline"];
        const link = s === "webhook" && c.condition.value && this._protectHost ? `https://${this._protectHost}/proxy/protect/integration/v1/alarm-manager/webhook/${c.condition.value}` : null;
        return `<div class="item"><ha-icon icon="${t[1]}"></ha-icon><span class="grow">${esc(spec(c.condition || {}) || t[0])}${who(c.condition || {})}${/^speed_/.test(s) && c.condition.value ? `<div class="k">Faster than ${esc(c.condition.value)} ${s === "speed_kmph" ? "km/h" : "mph"}</div>` : ""}${s === "webhook" && c.condition.value ? `<div class="k">Trigger ID</div><div class="mono">${esc(c.condition.value)}</div>` : ""}${link ? `<div class="k">Trigger link (POST, with a Protect API key)</div><div class="mono">${esc(link)}</div><button class="btn small copy" data-copy="${esc(link)}"><ha-icon icon="mdi:content-copy"></ha-icon>Copy link</button>` : ""}</span></div>`;
      })
      .join('<div class="k" style="padding-left:28px">or</div>') +
      (rule.historyConditions || [])
        .map((step) => `<div class="andline"><span class="andtag">AND</span><span class="k">within ${Math.round((step.period || 0) / 1000)} sec</span></div>` +
          (step.conditions || [])
            .map((c) => {
              const t = TRIGGERS[c.source] || [trigLabel(c.source || ""), "mdi:shield-alert-outline"];
              return `<div class="item"><ha-icon icon="${t[1]}"></ha-icon><span class="grow">${esc(spec(c) || t[0])}${who(c)}${/^speed_/.test(c.source || "") && c.value ? `<div class="k">Faster than ${esc(c.value)} ${c.source === "speed_kmph" ? "km/h" : "mph"}</div>` : ""}</span></div>`;
            })
            .join('<div class="k" style="padding-left:28px">or</div>'))
        .join("");
    const blocks = schedBlocks(rule.schedules);
    const named = schedMatch(rule.schedules, this._schedules);
    const sched = !(rule.schedules || []).length ? "Always"
      : named ? `${esc(named.name)}<div class="k">${esc(blocksText(blocks))}</div>`
      : blocks ? esc(blocksText(blocks)) : "Custom schedule (set in Protect)";

    const scope = (rule.sources || []).length
      ? rule.sources
          .map((s) => {
            const z = s.zones || {};
            const named = (k, id) => ((this._zones[s.device] || {})[k] || []).find((x) => x.id === id);
            const parts = [["zone", "Zone"], ["line", "Line"], ["loiter", "Loiter zone"], ["package", "Package zone"]]
              .filter(([k]) => (z[k] || []).length)
              .map(([k, l]) => `${l}${z[k].length > 1 ? "s" : ""}: ${z[k].map((id) => esc(named(k, id)?.name || `#${id}`)).join(", ")}`);
            const state = this._gone(s.device) ? '<div class="k warn">No longer in Protect. Edit the rule to take it out.</div>' : this._offline.has(s.device) ? '<div class="k">Offline</div>' : "";
            return `<div class="item"><ha-icon icon="${this._gone(s.device) ? "mdi:alert-outline" : s.type === "exclude" ? "mdi:cctv-off" : "mdi:cctv"}"></ha-icon><span class="grow">${dev(s.device)}<div class="k">${s.type === "exclude" ? "Excluded" : parts.join(" · ") || "Whole view"}</div>${state}</span></div>`;
          })
          .join("")
      : `<div class="item"><ha-icon icon="mdi:check-all"></ha-icon><span class="grow">${i.scope === "System" ? "Works at the system level, not tied to a device" : "All devices"}</span></div>`;

    const acts = (rule.actions || [])
      .map((a) => {
        const [label, icon] = ACTIONS[a.type] || [title(a.type), "mdi:flash-outline"];
        const m = a.metadata || {};
        let extra = "";
        if (a.type === "SEND_NOTIFICATION") {
          extra = `
            <div class="item"><ha-icon icon="mdi:bell-ring-outline"></ha-icon><span class="grow">Push to my phone</span><button class="sw push${i.push ? " on" : ""}" role="switch"></button></div>
            <div class="item"><ha-icon icon="mdi:email-outline"></ha-icon><span class="grow">Email me</span><button class="sw email${i.email ? " on" : ""}" role="switch"></button></div>`;
        } else if (a.type === "PTZ") {
          const lists = this._ptz[m.target] || { presets: [], patrols: [] };
          const what = m.mode === "preset" ? `Go to preset ${esc(lists.presets.find((x) => x.id === m.presetId)?.name || "")}, back home after ${Math.round((m.returnHome || 0) / 1000)} seconds`
            : m.mode === "patrol" ? `Run patrol ${esc(lists.patrols.find((x) => x.id === m.patrolId)?.name || "")}${m.repeat > 1 ? `, ${m.repeat} times` : ""}`
            : `Turn auto-tracking ${m.enable === false ? "off" : "on"}`;
          extra = `<div class="item"><span class="grow"><div class="k">${dev(m.target)}</div>${what}</span></div>`;
        } else if (a.type === "HTTP_REQUEST") {
          extra = `<div class="item"><span class="grow"><div class="k">${esc(m.method || "POST")} request to</div><div class="mono">${esc(m.url || "")}</div></span></div>`;
        } else {
          const targets = (m.sources || []).map((s) => `<span class="pill">${dev(s.device)}</span>`).join("");
          const bits = [];
          if (targets) bits.push(`<div class="item"><span class="grow"><div class="k">${m.enable === false ? "Turn off" : "Turn on"}</div>${targets}</span></div>`);
          if (m.duration) bits.push(`<div class="item"><span class="grow"><div class="k">Duration</div>${Math.round(m.duration / 1000)} seconds</span></div>`);
          extra = bits.join("");
        }
        return `<div class="item"><ha-icon icon="${icon}"></ha-icon><span class="grow"><b>${esc(label)}</b></span></div>${extra}`;
      })
      .join("");
    const cd = rule.cooldown || {};
    const cur = (cd.timeout || 600000) / 60000;
    const options = [...new Set([...COOLDOWNS, cur])].sort((a, b) => a - b);

    root.querySelector(".body").innerHTML = `
      <div class="box"><h3><ha-icon icon="mdi:flash-outline"></ha-icon>Trigger</h3>${trig}
        <div class="item"><ha-icon icon="mdi:calendar-clock"></ha-icon><span class="grow"><div class="k">Schedule</div>${sched}</span></div></div>
      <div class="box"><h3><ha-icon icon="mdi:cctv"></ha-icon>Scope</h3>${scope}</div>
      <div class="box"><h3><ha-icon icon="mdi:play-circle-outline"></ha-icon>Action</h3>${acts}
        <div class="item" style="margin-top:8px;border-top:1px solid #222;padding-top:12px"><span class="grow">Ignore repeated actions<div class="k">Stay quiet for a while after firing</div></span><button class="sw cool${cd.enable ? " on" : ""}" role="switch"></button></div>
        <div class="item"><span class="grow k">Quiet for</span><select class="mins">${options.map((m) => `<option value="${m}"${m === cur ? " selected" : ""}>${minutes(m)}</option>`).join("")}</select></div></div>
      ${this._historyHtml(rule)}
      <div class="note">Use Edit to change the name, triggers, schedule, scope or actions. Zones are drawn in UniFi Protect.</div>`;
    this._historyWire(root);
    for (const el of root.querySelectorAll(".copy")) {
      el.onclick = async () => {
        try {
          await navigator.clipboard.writeText(el.dataset.copy);
          el.lastChild.textContent = "Copied";
        } catch (e) {
          el.lastChild.textContent = "Select and copy the link above";
        }
      };
    }
    const foot = root.querySelector(".foot");
    foot.innerHTML = `<button class="btn danger del"><ha-icon icon="mdi:delete-outline"></ha-icon>Delete rule</button><span class="msg"></span><button class="btn edit"><ha-icon icon="mdi:pencil-outline"></ha-icon>Edit</button>`;
    foot.querySelector(".edit").onclick = () => this._openEdit(rule);
    const del = foot.querySelector(".del");
    del.onclick = async () => {
      if (!del.classList.contains("sure")) {
        // ask once more: deleting removes the rule from Protect itself
        del.classList.add("sure");
        del.lastChild.textContent = "Delete from Protect?";
        setTimeout(() => {
          if (!del.isConnected) return;
          del.classList.remove("sure");
          del.lastChild.textContent = "Delete rule";
          if (this._detailLater) this._renderDetail();
        }, 5000);
        return;
      }
      root.querySelector(".lb").classList.add("busy");
      try {
        await this._hass.callWS({ type: "protect_rules/delete", rule_id: rule.id });
        this._closeDetail();
      } catch (err) {
        foot.querySelector(".msg").textContent = err?.message || String(err);
      } finally {
        root.querySelector(".lb").classList.remove("busy");
      }
    };
    const b = root.querySelector(".body");
    b.querySelector(".push")?.addEventListener("click", () => this._update(rule.id, { push: !i.push }));
    b.querySelector(".email")?.addEventListener("click", () => this._update(rule.id, { email: !i.email }));
    b.querySelector(".cool").onclick = () => this._update(rule.id, { cooldown_enabled: !cd.enable });
    b.querySelector(".mins").onchange = (ev) => this._update(rule.id, { cooldown_minutes: Number(ev.target.value) });
  }

  // ----------------------------------------------------- new / edit rule

  _openNew() {
    this._openDetail(null);
    this._new = {
      name: "",
      tab: "objects",
      triggers: new Set(["person"]),
      speed: "20",
      picks: {},
      also: [], // "AND" steps: { tab, triggers, speed, picks, seconds }
      sched: { mode: "always", id: (this._schedules[0] || {}).id || "", blocks: [{ days: new Set([0, 1, 2, 3, 4, 5, 6]), start: "19:00", end: "06:00" }] },
      scope: "include",
      devices: new Set(),
      zones: {},
      actions: [{ kind: "notify", push: true, email: false }],
      cool: true,
      mins: 2,
    };
    this._new.orig = this._formKey(this._new);
    this._renderNew();
  }

  _openEdit(rule) {
    const cd = rule.cooldown || {};
    const trigs = sources(rule);
    const actions = (rule.actions || []).map((a, index) => {
      const m = a.metadata || {};
      if (a.type === "SEND_NOTIFICATION") {
        const ch = (receiver(rule) || {}).channels || [];
        return { kind: "notify", push: ch.includes("push"), email: ch.includes("email") };
      }
      if (a.type === "SET_LIGHT") return { kind: "light", device: (m.sources || [])[0]?.device || "", seconds: Math.round((m.duration || 30000) / 1000) };
      if (a.type === "HTTP_REQUEST") return { kind: "webhook", url: m.url || "", method: m.method === "GET" ? "GET" : "POST" };
      if (a.type === "PTZ" && ["preset", "patrol", "autotrack"].includes(m.mode)) {
        return { kind: "ptz", device: m.target || "", mode: m.mode, preset_id: m.presetId || "", return_home: Math.round((m.returnHome || 10000) / 1000), patrol_id: m.patrolId || "", repeat: m.repeat || 1, enable: m.enable !== false };
      }
      return { kind: "keep", index, label: (ACTIONS[a.type] || [title(a.type)])[0] }; // a type this form can't edit: kept as is
    });
    const sBlocks = schedBlocks(rule.schedules);
    const sNamed = schedMatch(rule.schedules, this._schedules);
    const sched = {
      // "keep": a schedule this form can't show stays as it is unless another mode is picked
      mode: !(rule.schedules || []).length ? "always" : sNamed ? "predefined" : sBlocks ? "custom" : "keep",
      id: (sNamed || this._schedules[0] || {}).id || "",
      blocks: sBlocks && sBlocks.length && !sNamed
        ? sBlocks.map((b) => ({ days: new Set(b.days), start: `${pad(b.start[0])}:${pad(b.start[1])}`, end: `${pad(b.end[0])}:${pad(b.end[1])}` }))
        : [{ days: new Set([0, 1, 2, 3, 4, 5, 6]), start: "19:00", end: "06:00" }],
    };
    this._detailId = null;
    this._new = {
      id: rule.id,
      base: (this._revs || {})[rule.id], // the rule as it was when the form opened
      sched,
      name: rule.name,
      tab: (TABS.find((t) => t[3].some(([, keys]) => keys.includes(trigs[0]))) || TABS[1])[0],
      // km/h is the same chip as mph with the other unit
      triggers: new Set(trigs),
      picks: picksFrom((rule.conditions || []).map((c) => c.condition)),
      speed: String((rule.conditions || []).map((c) => c.condition || {}).find((c) => /^speed_/.test(c.source || ""))?.value || "20"),
      also: (rule.historyConditions || []).map((step) => {
        const keys = (step.conditions || []).map((c) => c.source).filter(Boolean);
        return {
          tab: (TABS.find((t) => t[3].some(([, ks]) => ks.includes(keys[0] === "speed_kmph" ? "speed_mph" : keys[0]))) || TABS[1])[0],
          triggers: new Set(keys),
          picks: picksFrom(step.conditions),
          speed: String((step.conditions || []).find((c) => /^speed_/.test(c.source || ""))?.value || "20"),
          seconds: Math.min(60, Math.max(1, Math.round((step.period || 1000) / 1000))),
        };
      }),
      scope: (rule.sources || [])[0]?.type === "exclude" ? "exclude" : "include",
      devices: new Set((rule.sources || []).map((s) => s.device)),
      // device -> { zone: [ids], line: [ids], loiter: [ids] } the rule is limited to
      zones: Object.fromEntries((rule.sources || []).map((s) => [s.device, { zone: [...((s.zones || {}).zone || [])], line: [...((s.zones || {}).line || [])], loiter: [...((s.zones || {}).loiter || [])] }])),
      actions,
      cool: !!cd.enable,
      mins: (cd.timeout || 600000) / 60000,
    };
    this._new.was = this._snapshot(this._new);
    this._new.orig = this._formKey(this._new);
    this._renderNew();
  }

  // Can any device (or, with a mac, that device) produce this trigger?
  // System, geofence and webhook triggers don't depend on a device.
  _can(trigger, mac) {
    if (!this._caps || trigGroup(trigger) !== "device") return true;
    const t = trigger === "speed_kmph" ? "speed_mph" : trigger;
    if (mac) return (this._caps[mac] || []).includes(t);
    return Object.values(this._caps).some((list) => list.includes(t));
  }

  _newPtz(mac, mode) {
    const lists = this._ptz[mac] || { presets: [], patrols: [] };
    return { kind: "ptz", device: mac, mode, preset_id: lists.presets[0]?.id || "", return_home: 10, patrol_id: lists.patrols[0]?.id || "", repeat: 1, enable: true };
  }

  // everything in the form, to tell whether closing it would lose anything
  _formKey(n) {
    return JSON.stringify([this._snapshot(n), (n.name || "").trim(), n.cool, n.mins]);
  }

  // Close button, backdrop, Esc: with unsaved edits in the form, ask first
  // (a second try within a few seconds discards them).
  _askClose() {
    const n = this._new;
    const armed = this._discardAt && Date.now() - this._discardAt < 6000;
    if (!n || !n.orig || this._formKey(n) === n.orig || armed) return this._closeDetail();
    this._discardAt = Date.now();
    const msg = this._dlg.shadowRoot.querySelector(".foot .msg");
    if (msg) msg.textContent = `You have unsaved changes. Close again to discard them, or ${n.id ? "Save" : "Create rule"} to keep them.`;
  }

  // what the form would send, to tell which parts changed
  _snapshot(n) {
    return {
      triggers: JSON.stringify([[...n.triggers].sort(), n.triggers.has("speed_mph") || n.triggers.has("speed_kmph") ? n.speed : null, picksKey(n)]),
      sched: JSON.stringify([n.sched.mode, n.sched.mode === "predefined" ? n.sched.id : null, n.sched.mode === "custom" ? n.sched.blocks.map((b) => [[...b.days].sort(), b.start, b.end]) : null]),
      also: JSON.stringify(n.also.map((a) => [[...a.triggers].sort(), a.triggers.has("speed_mph") || a.triggers.has("speed_kmph") ? a.speed : null, a.seconds, picksKey(a)])),
      scope: JSON.stringify([n.scope, [...n.devices].sort().map((mac) => [mac, n.zones[mac] || {}])]),
      actions: JSON.stringify(n.actions),
    };
  }

  _renderNew() {
    const n = this._new;
    this._discardAt = 0; // the form was used again: closing asks afresh
    const root = this._dlg.shadowRoot;
    root.querySelector(".lb").classList.remove("busy");
    root.querySelector(".ico").setAttribute("icon", n.id ? "mdi:shield-edit-outline" : "mdi:shield-plus-outline");
    root.querySelector(".title").textContent = n.id ? "Edit rule" : "New rule";
    root.querySelector(".sub").textContent = n.id ? "Saved to UniFi Protect's Alarm Manager" : "Created in UniFi Protect's Alarm Manager";
    root.querySelector(".enable").hidden = true;

    const devs = Object.keys(this._devices).map((mac) => [mac, this._pickName(mac)]);
    // devices the rule still names that Protect no longer has: shown so they can be taken out
    const goneDevs = [...n.devices].filter((mac) => !(mac in this._devices));
    const group = [...n.triggers].map(trigGroup)[0] || "device";
    const noScope = group !== "device";
    const known = new Set([...TABS.flatMap((t) => t[3].flatMap(([, keys]) => keys)), "speed_kmph"]);
    const chip = (cls, v, label, on, icon) => `<button class="${cls}${on ? " on" : ""}" data-v="${esc(v)}">${icon ? `<ha-icon icon="${icon}"></ha-icon>` : ""}${esc(label)}</button>`;

    // The trigger picker (tabs + chips), for the main triggers (p = "m") and
    // for each AND step (p = its index); st is that part's { tab, triggers, speed }.
    const picker = (st, p) => {
      const tabOk = (t) => t[3].some(([, keys]) => keys.some((k) => this._can(k) || st.triggers.has(k)));
      if (!tabOk(TABS.find((t) => t[0] === st.tab) || TABS[1])) st.tab = (TABS.find(tabOk) || TABS[3])[0];
      const tab = TABS.find((t) => t[0] === st.tab) || TABS[1];
      const unit = st.triggers.has("speed_kmph") ? "speed_kmph" : "speed_mph";
      const hasSpeed = st.triggers.has("speed_mph") || st.triggers.has("speed_kmph");
      const tabs = TABS.map(([key, label, icon, groups]) => {
        const count = groups.flatMap(([, keys]) => keys).filter((k) => st.triggers.has(k) || (k === "speed_mph" && st.triggers.has("speed_kmph"))).length;
        const ok = tabOk([key, label, icon, groups]);
        return `<button class="tab${key === st.tab ? " on" : ""}" data-v="${key}"${ok ? "" : ' disabled title="None of your devices can trigger these"'}><ha-icon icon="${icon}"></ha-icon>${label}${count ? `<span class="cnt">${count}</span>` : ""}</button>`;
      }).join("");
      const trigList = tab[3]
        .map(([heading, keys]) => {
          // a group none of whose triggers can happen is left out; single ones are greyed
          if (!keys.some((k) => this._can(k) || st.triggers.has(k))) return "";
          const one = (k) => {
            // "Known faces" means any known face; with specific ones picked it is off
            const on = k === "speed_mph" ? hasSpeed : st.triggers.has(k) && !(PICK_LISTS[k] && picked(st, k));
            const html = k === "speed_mph" ? chip("", unit, "Speed over…", on, "mdi:speedometer") : chip("", k, trigLabel(k), on, (TRIGGERS[k] || [])[1]);
            return this._can(k) || on ? html : html.replace("<button ", '<button disabled title="None of your devices can trigger this" ');
          };
          return `${heading ? `<label class="f">${heading}</label>` : ""}<div class="pick trigs">${keys.map(one).join("")}</div>`;
        })
        .join("") + (hasSpeed && tab[0] === "activity" ? `<div class="item"><span class="grow k">Faster than</span><input class="txt speed" type="number" min="1" max="500" style="width:90px" value="${esc(st.speed)}">
          <div class="pick units">${chip("", "speed_mph", "mph", unit === "speed_mph")}${chip("", "speed_kmph", "km/h", unit === "speed_kmph")}</div></div><div class="k">Needs a camera with a radar add-on.</div>` : "");
      const plist = (src, label, rows) => rows.length
        ? `<label class="f">${label}</label><div class="pick plist" data-src="${src}">${rows.map((x) => `<button data-v="${esc(x.id)}" class="${(st.picks[src] || new Set()).has(x.id) ? "on" : ""}">${esc(x.name)}</button>`).join("")}</div>`
        : "";
      const lists = tab[0] !== "id" ? ""
        : plist("face_known", "Specific faces", this._people.faces)
          + plist("license_plate_known", "Specific vehicles", this._people.vehicles)
          + (GEOFENCE.some((k) => st.triggers.has(k)) ? plist("geo", "Geofence: for these people (none picked = everyone)", this._people.users) : "");
      const other = [...st.triggers].filter((k) => !known.has(k));
      return `<div class="picker" data-p="${p}"><div class="tabs">${tabs}</div>${trigList}${lists}
        ${other.length ? `<label class="f">Also set in Protect</label><div class="pick trigs">${other.map((k) => chip("", k, trigLabel(k), true)).join("")}</div>` : ""}</div>`;
    };
    const schedBox = () => {
      const sc = n.sched;
      const named = this._schedules.find((x) => x.id === sc.id);
      const modes = [["always", "Always"], ...(this._schedules.length ? [["predefined", "Predefined"]] : []), ["custom", "Custom"], ...(sc.mode === "keep" ? [["keep", "Set in Protect"]] : [])];
      let body = "";
      if (sc.mode === "predefined") {
        const nb = named && schedBlocks(named.schedules);
        body = `<select class="wide spre">${this._schedules.map((x) => `<option value="${esc(x.id)}"${x.id === sc.id ? " selected" : ""}>${esc(x.name)}</option>`).join("")}</select>
          <div class="k" style="margin-top:6px">${nb ? esc(blocksText(nb)) : ""}</div>`;
      } else if (sc.mode === "custom") {
        body = sc.blocks.map((bl, i) => `<div class="srow">
            <div class="pick sdays" data-i="${i}">${DAYS.map((d, di) => `<button data-d="${di}" class="${bl.days.has(di) ? "on" : ""}" title="${d}">${d.slice(0, 2)}</button>`).join("")}</div>
            <div class="stimes"><input type="time" class="txt sstart" data-i="${i}" value="${esc(bl.start)}"><span class="k">to</span><input type="time" class="txt send" data-i="${i}" value="${esc(bl.end)}">
              ${sc.blocks.length > 1 ? `<button class="x sx" data-i="${i}" title="Remove this time range"><ha-icon icon="mdi:close"></ha-icon></button>` : ""}</div></div>`).join("")
          + `${sc.blocks.length < 6 ? '<button class="link addblock">Add time range</button>' : ""}<div class="k">An end time earlier than the start runs past midnight into the next day.</div>`;
      } else if (sc.mode === "keep") {
        body = '<div class="k">This schedule was set up in Protect in a way this form can\'t show. It stays as it is unless you pick another option.</div>';
      }
      return `<div class="schedbox"><label class="f">Schedule</label><div class="pick smode">${modes.map(([k, l]) => chip("", k, l, sc.mode === k)).join("")}</div>${body}</div>`;
    };
    const secs = (cur) => [...new Set([1, 2, 3, 5, 10, 15, 20, 30, 45, 60, cur])].sort((a, b) => a - b);
    const andBox = (a, idx) => `<div class="andbox">
        <div class="ahead"><span class="andtag">AND</span><span class="k">within</span>
          <select class="andsecs" data-i="${idx}">${secs(a.seconds).map((x) => `<option value="${x}"${x === a.seconds ? " selected" : ""}>${x} sec</option>`).join("")}</select>
          <span class="grow"></span><button class="x andx" data-i="${idx}" title="Remove this step"><ha-icon icon="mdi:close"></ha-icon></button></div>
        ${picker(a, idx)}</div>`;

    const ptzCams = Object.keys(this._ptz).filter((mac) => mac in this._devices).map((mac) => [mac, this._pickName(mac)]);
    const sel = (idx, f, opts, cur, empty) => `<select class="wide" data-i="${idx}" data-f="${f}">${opts.length ? "" : `<option value="">${empty}</option>`}${(f === "device" && cur && !opts.some(([v]) => v === cur) ? [[cur, this._dev(cur)], ...opts] : opts).map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(cur) ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    const actionBox = (a, idx) => {
      const head = `<div class="ahead"><div class="pick akind" data-i="${idx}">${a.kind === "keep" ? `<button class="on">${esc(a.label)}</button>` : ""}${[["notify", "Notify", "mdi:bell-outline"], ["webhook", "Webhook", "mdi:webhook"], ["light", "Light", "mdi:lightbulb-on-outline"], ...(ptzCams.length ? [["ptz", "PTZ", "mdi:rotate-3d-variant"]] : [])].map(([k, l, ic]) => chip("", k, l, a.kind === k, ic)).join("")}</div>${n.actions.length > 1 ? `<button class="x" data-i="${idx}" title="Remove this action"><ha-icon icon="mdi:close"></ha-icon></button>` : ""}</div>`;
      let body = "";
      if (a.kind === "notify") {
        body = `<div class="item"><ha-icon icon="mdi:bell-ring-outline"></ha-icon><span class="grow">Push to my phone</span><button class="sw" data-i="${idx}" data-f="push"></button></div>
          <div class="item"><ha-icon icon="mdi:email-outline"></ha-icon><span class="grow">Email me</span><button class="sw" data-i="${idx}" data-f="email"></button></div>`;
      } else if (a.kind === "light") {
        body = `<label class="f">Turn on the light of</label><select class="wide" data-i="${idx}" data-f="device"><option value="">Pick a device…</option>${(a.device && !(a.device in this._devices) ? [[a.device, this._dev(a.device)], ...devs] : devs).map(([mac, name]) => `<option value="${esc(mac)}"${mac === a.device ? " selected" : ""}>${esc(name)}</option>`).join("")}</select>
          ${a.device && !(a.device in this._devices) ? '<div class="k warn" style="margin-top:6px">That device is no longer in Protect. Pick another one.</div>' : ""}
          <label class="f">For</label><select class="wide" data-i="${idx}" data-f="seconds">${[...new Set([10, 30, 60, 120, 300, 600, a.seconds])].sort((x, y) => x - y).map((x) => `<option value="${x}"${x === a.seconds ? " selected" : ""}>${x < 60 ? `${x} seconds` : `${x / 60} min`}</option>`).join("")}</select>`;
      } else if (a.kind === "webhook") {
        body = `<label class="f">Send a request to</label><input class="txt" data-i="${idx}" data-f="url" placeholder="https://…" value="${esc(a.url || "")}">
          <div class="item"><select data-i="${idx}" data-f="method">${["POST", "GET"].map((m) => `<option${m === a.method ? " selected" : ""}>${m}</option>`).join("")}</select><span class="grow"></span></div>`;
      } else if (a.kind === "ptz") {
        const lists = this._ptz[a.device] || { presets: [], patrols: [] };
        body = `<div class="pick pmode" data-i="${idx}">${[["preset", "Preset"], ["patrol", "Patrol"], ["autotrack", "Auto-tracking"]].map(([k, l]) => chip("", k, l, a.mode === k)).join("")}</div>
          <label class="f">Camera</label>${sel(idx, "device", ptzCams, a.device, "No PTZ camera")}
          ${a.device && !(a.device in this._devices) ? '<div class="k warn" style="margin-top:6px">That camera is no longer in Protect. Pick another one, or remove this action.</div>' : ""}
          ${a.mode === "preset" ? `<label class="f">Go to preset</label>${sel(idx, "preset_id", lists.presets.map((x) => [x.id, x.name]), a.preset_id, "No presets saved on this camera")}
            <label class="f">Back home after</label>${sel(idx, "return_home", [...new Set([10, 15, 20, 30, 45, 60, a.return_home])].sort((x, y) => x - y).map((x) => [x, `${x} seconds`]), a.return_home, "")}
            ${lists.presets.length ? "" : '<div class="k" style="margin-top:6px">Save a preset on the camera in Protect first; it shows up here within five minutes.</div>'}` : ""}
          ${a.mode === "patrol" ? `<label class="f">Run patrol</label>${sel(idx, "patrol_id", lists.patrols.map((x) => [x.id, x.name]), a.patrol_id, "No patrols set up on this camera")}
            <label class="f">Repeat</label>${sel(idx, "repeat", [1, 2, 3].map((x) => [x, x === 1 ? "Once" : `${x} times`]), a.repeat, "")}
            ${lists.patrols.length ? "" : '<div class="k" style="margin-top:6px">Set up a patrol on the camera in Protect first; it shows up here within five minutes.</div>'}` : ""}
          ${a.mode === "autotrack" ? `<div class="item"><ha-icon icon="mdi:target-account"></ha-icon><span class="grow">Turn auto-tracking ${a.enable ? "on" : "off"}</span><button class="sw" data-i="${idx}" data-f="enable"></button></div>` : ""}`;
      } else {
        body = `<div class="k">This action type is edited in Protect. It stays as it is; pick a type above to replace it.</div>`;
      }
      return `<div class="abox">${head}${body}</div>`;
    };

    root.querySelector(".body").innerHTML = `
      <div class="box"><h3><ha-icon icon="mdi:flash-outline"></ha-icon>Trigger</h3>
        <label class="f">Name</label><input class="txt name" maxlength="80" placeholder="e.g. Driveway person at night" value="${esc(n.name || "")}">
        <label class="f">When any of these happen</label>${picker(n, "m")}
        ${n.also.map(andBox).join("")}
        ${n.also.length < 3 ? '<button class="link addand" title="Only fire when something else also happens shortly after">Add AND step</button>' : ""}
        ${schedBox()}
        ${n.triggers.has("webhook") ? `<div class="k" style="margin-top:8px">${n.id ? "The trigger ID and link are shown on the rule's page." : "Protect gives the rule a trigger ID and link once it is created."}</div>` : ""}</div>
      <div class="box"><h3><ha-icon icon="mdi:cctv"></ha-icon>Scope</h3>
        ${noScope ? '<div class="item"><span class="grow">This trigger works at the system level; no devices to pick.</span></div>'
          : `<div class="pick scope">${chip("", "include", "Include", n.scope === "include")}${chip("", "exclude", "Exclude", n.scope === "exclude")}</div>
             <label class="f">${n.scope === "include" ? "Only these devices (none picked = all devices)" : "Every device except these"}</label>
             <div class="pick devs">${devs.map(([mac, name]) => {
               const html = chip("", mac, name, n.devices.has(mac));
               const able = n.devices.has(mac) || [...n.triggers].some((t) => this._can(t, mac));
               return able ? html : html.replace("<button ", `<button disabled title="${esc(name)} can't trigger this" `);
             }).join("")}${goneDevs.map((mac) => chip("", mac, this._dev(mac), true).replace('class="', 'title="No longer in Protect: click to take it out of the rule" class="gone ')).join("")}</div>
             ${goneDevs.length ? `<div class="k warn" style="margin-top:6px">${goneDevs.length === 1 ? "One device is" : "Some devices are"} no longer in Protect. Click ${goneDevs.length === 1 ? "it" : "them"} to take ${goneDevs.length === 1 ? "it" : "them"} out of the rule.</div>` : ""}
             ${n.scope === "include" ? [...n.devices].map((mac) => {
               const z = this._zones[mac] || {};
               const groups = [["zone", "Zones"], ["line", "Lines"], ["loiter", "Loiter zones"]].filter(([k]) => (z[k] || []).length);
               if (!groups.length) return "";
               const mine = n.zones[mac] || {};
               return `<div class="zbox"><div class="zname">${esc(this._dev(mac))}<span class="k"> · none picked = whole view</span></div>${groups.map(([k, label]) => `<label class="f">${label}</label><div class="pick zones" data-mac="${mac}" data-kind="${k}">${z[k].map((x) => `<button data-id="${x.id}" class="${(mine[k] || []).includes(x.id) ? "on" : ""}"><i class="dot" style="background:${esc(x.color || "#888")}"></i>${esc(x.name)}</button>`).join("")}</div>`).join("")}</div>`;
             }).join("") : ""}`}</div>
      <div class="box"><h3><ha-icon icon="mdi:play-circle-outline"></ha-icon>Action</h3>
        ${n.actions.map(actionBox).join("")}
        ${n.actions.length < 6 ? '<button class="link addact">Add action</button>' : ""}
        <div class="item" style="margin-top:8px;border-top:1px solid #222;padding-top:12px"><span class="grow">Ignore repeated actions<div class="k">Stay quiet for a while after firing</div></span><button class="sw cool${n.cool ? " on" : ""}"></button></div>
        <div class="item"><span class="grow k">Quiet for</span><select class="mins">${[...new Set([...COOLDOWNS, n.mins])].sort((a, b) => a - b).map((m) => `<option value="${m}"${m === n.mins ? " selected" : ""}>${minutes(m)}</option>`).join("")}</select></div></div>`;

    const b = root.querySelector(".body");
    const again = () => this._renderNew();
    b.querySelector(".name").oninput = (ev) => (n.name = ev.target.value);
    // each picker edits its own part: the main triggers or one AND step
    for (const pk of b.querySelectorAll(".picker")) {
      const st = pk.dataset.p === "m" ? n : n.also[Number(pk.dataset.p)];
      for (const el of pk.querySelectorAll(".tabs .tab")) el.onclick = () => ((st.tab = el.dataset.v), again());
      for (const el of pk.querySelectorAll(".trigs button")) {
        el.onclick = () => {
          const k = el.dataset.v;
          if (PICK_LISTS[k] && picked(st, k)) delete st.picks[k]; // from specific ones back to any known
          else if (st.triggers.has(k)) st.triggers.delete(k), delete st.picks[k];
          else {
            // device, system and webhook triggers don't mix in one step
            for (const t of [...st.triggers]) if (trigGroup(t) !== trigGroup(k) || k === "webhook") st.triggers.delete(t);
            st.triggers.add(k);
          }
          again();
        };
      }
      for (const el of pk.querySelectorAll(".plist button")) {
        el.onclick = () => {
          const src = el.parentElement.dataset.src;
          const set = (st.picks[src] = st.picks[src] || new Set());
          set.has(el.dataset.v) ? set.delete(el.dataset.v) : set.add(el.dataset.v);
          if (src !== "geo") {
            // picking a face / vehicle turns that trigger on; unpicking the last one turns it off
            if (set.size) {
              for (const t of [...st.triggers]) if (trigGroup(t) !== trigGroup(src)) st.triggers.delete(t);
              st.triggers.add(src);
            } else st.triggers.delete(src);
          }
          again();
        };
      }
      const speed = pk.querySelector(".speed");
      if (speed) speed.oninput = () => (st.speed = speed.value);
      for (const el of pk.querySelectorAll(".units button")) {
        el.onclick = () => {
          st.triggers.delete("speed_mph");
          st.triggers.delete("speed_kmph");
          st.triggers.add(el.dataset.v);
          again();
        };
      }
    }
    for (const el of b.querySelectorAll(".smode button")) el.onclick = () => ((n.sched.mode = el.dataset.v), again());
    const spre = b.querySelector(".spre");
    if (spre) spre.onchange = () => ((n.sched.id = spre.value), again());
    for (const el of b.querySelectorAll(".sdays button")) {
      el.onclick = () => {
        const days = n.sched.blocks[Number(el.parentElement.dataset.i)].days;
        const d = Number(el.dataset.d);
        days.has(d) ? days.delete(d) : days.add(d);
        again();
      };
    }
    for (const el of b.querySelectorAll(".sstart, .send")) el.onchange = () => (n.sched.blocks[Number(el.dataset.i)][el.classList.contains("sstart") ? "start" : "end"] = el.value);
    for (const el of b.querySelectorAll(".sx")) el.onclick = () => (n.sched.blocks.splice(Number(el.dataset.i), 1), again());
    const addblock = b.querySelector(".addblock");
    if (addblock) addblock.onclick = () => (n.sched.blocks.push({ days: new Set([0, 1, 2, 3, 4, 5, 6]), start: "08:00", end: "17:00" }), again());
    const addand = b.querySelector(".addand");
    if (addand) addand.onclick = () => (n.also.push({ tab: "objects", triggers: new Set(), picks: {}, speed: "20", seconds: 5 }), again());
    for (const el of b.querySelectorAll(".andx")) el.onclick = () => (n.also.splice(Number(el.dataset.i), 1), again());
    for (const el of b.querySelectorAll(".andsecs")) el.onchange = () => (n.also[Number(el.dataset.i)].seconds = Number(el.value));
    for (const el of b.querySelectorAll(".scope button")) el.onclick = () => ((n.scope = el.dataset.v), again());
    for (const el of b.querySelectorAll(".devs button")) el.onclick = () => (n.devices.has(el.dataset.v) ? n.devices.delete(el.dataset.v) : n.devices.add(el.dataset.v), again());
    for (const el of b.querySelectorAll(".zones button")) {
      el.onclick = () => {
        const { mac, kind } = el.parentElement.dataset;
        const id = Number(el.dataset.id);
        const mine = (n.zones[mac] = n.zones[mac] || { zone: [], line: [], loiter: [] });
        mine[kind] = (mine[kind] || []).includes(id) ? mine[kind].filter((x) => x !== id) : [...(mine[kind] || []), id].sort((a, b) => a - b);
        again();
      };
    }
    for (const el of b.querySelectorAll(".akind button[data-v]")) {
      el.onclick = () => {
        const idx = Number(el.parentElement.dataset.i);
        const k = el.dataset.v;
        if (n.actions[idx].kind === k) return;
        n.actions[idx] = k === "notify" ? { kind: "notify", push: true, email: false } : k === "light" ? { kind: "light", device: "", seconds: 30 }
          : k === "ptz" ? this._newPtz(ptzCams[0][0], "preset") : { kind: "webhook", url: "", method: "POST" };
        again();
      };
    }
    for (const el of b.querySelectorAll(".pmode button")) {
      el.onclick = () => {
        const a = n.actions[Number(el.parentElement.dataset.i)];
        a.mode = el.dataset.v;
        again();
      };
    }
    for (const el of b.querySelectorAll(".abox .x")) el.onclick = () => (n.actions.splice(Number(el.dataset.i), 1), again());
    for (const el of b.querySelectorAll(".abox .sw")) {
      const a = n.actions[Number(el.dataset.i)];
      el.classList.toggle("on", !!a[el.dataset.f]);
      el.onclick = () => ((a[el.dataset.f] = !a[el.dataset.f]), again());
    }
    for (const el of b.querySelectorAll(".abox select, .abox input")) {
      const a = n.actions[Number(el.dataset.i)];
      const set = () => {
        a[el.dataset.f] = ["seconds", "return_home", "repeat"].includes(el.dataset.f) ? Number(el.value) : el.value;
        if (a.kind === "ptz" && el.dataset.f === "device") {
          // another camera: its own presets and patrols
          Object.assign(a, this._newPtz(a.device, a.mode), { return_home: a.return_home, repeat: a.repeat, enable: a.enable });
          again();
        }
      };
      el.oninput = set;
      el.onchange = set;
    }
    const add = b.querySelector(".addact");
    if (add) add.onclick = () => (n.actions.push({ kind: "notify", push: true, email: false }), again());
    b.querySelector(".cool").onclick = () => ((n.cool = !n.cool), again());
    b.querySelector(".mins").onchange = (ev) => (n.mins = Number(ev.target.value));

    const foot = root.querySelector(".foot");
    foot.innerHTML = `<span class="msg"></span><button class="btn cancel">Cancel</button><button class="btn primary create"><ha-icon icon="mdi:check"></ha-icon>${n.id ? "Save" : "Create rule"}</button>`;
    foot.querySelector(".cancel").onclick = () => (n.id ? this._openDetail(n.id) : this._closeDetail());
    foot.querySelector(".create").onclick = async () => {
      const msg = foot.querySelector(".msg");
      if (!(n.name || "").trim()) return (msg.textContent = "Give the rule a name.");
      if (!n.triggers.size) return (msg.textContent = "Pick at least one trigger.");
      if (!n.actions.length) return (msg.textContent = "Add at least one action.");
      const speedOn = n.triggers.has("speed_mph") || n.triggers.has("speed_kmph");
      const limit = Math.round(Number(n.speed));
      if (speedOn && !(limit >= 1 && limit <= 500)) return (msg.textContent = "The speed has to be between 1 and 500.");
      // each trigger's setting: the speed limit, or the faces / vehicles / people it is narrowed to
      const valuesOf = (st, speedValue) => {
        const v = {};
        for (const k of st.triggers) {
          if (/^speed_/.test(k)) v[k] = speedValue;
          else if (picked(st, k)) v[k] = picked(st, k);
        }
        return Object.keys(v).length ? v : null;
      };
      const values = valuesOf(n, String(limit));
      let schedule = null; // null: leave the rule's schedule alone
      if (n.sched.mode === "always") schedule = { mode: "always" };
      else if (n.sched.mode === "predefined") schedule = { mode: "predefined", id: n.sched.id };
      else if (n.sched.mode === "custom") {
        const blocks = [];
        for (const bl of n.sched.blocks) {
          if (!bl.days.size) return (msg.textContent = "Pick at least one day for each time range of the schedule.");
          if (!/^\d\d:\d\d$/.test(bl.start) || !/^\d\d:\d\d$/.test(bl.end)) return (msg.textContent = "Fill in the start and end time of the schedule.");
          if (bl.start === bl.end) return (msg.textContent = "A schedule's start and end time can't be the same.");
          blocks.push({ days: [...bl.days].sort((x, y) => x - y), start: bl.start.split(":").map(Number), end: bl.end.split(":").map(Number) });
        }
        schedule = { mode: "custom", blocks };
      }
      const also = [];
      for (const a of n.also) {
        if (!a.triggers.size) return (msg.textContent = "Pick a trigger for each AND step, or remove the step.");
        const unit = a.triggers.has("speed_kmph") ? "speed_kmph" : a.triggers.has("speed_mph") ? "speed_mph" : null;
        const lim = Math.round(Number(a.speed));
        if (unit && !(lim >= 1 && lim <= 500)) return (msg.textContent = "The speed has to be between 1 and 500.");
        const av = valuesOf(a, String(lim));
        also.push({ triggers: [...a.triggers], seconds: a.seconds, ...(av ? { trigger_values: av } : {}) });
      }
      for (const a of n.actions) {
        if (a.kind === "light" && !a.device) return (msg.textContent = "Pick the device whose light to turn on.");
        if (a.kind === "ptz" && a.mode === "preset" && !a.preset_id) return (msg.textContent = "That camera has no saved PTZ preset yet; save one in Protect, or pick another PTZ mode.");
        if (a.kind === "ptz" && a.mode === "patrol" && !a.patrol_id) return (msg.textContent = "That camera has no PTZ patrol yet; set one up in Protect, or pick another PTZ mode.");
        if (a.kind === "webhook" && !/^https?:\/\/\S+$/.test(a.url || "")) return (msg.textContent = "The webhook needs a full address starting with http:// or https://.");
      }
      const actions = n.actions.map((a) =>
        a.kind === "notify" ? { kind: "notify", push: !!a.push, email: !!a.email }
        : a.kind === "light" ? { kind: "light", device: a.device, seconds: a.seconds }
        : a.kind === "webhook" ? { kind: "webhook", url: a.url.trim(), method: a.method }
        : a.kind === "ptz" ? { kind: "ptz", device: a.device, mode: a.mode, ...(a.mode === "preset" ? { preset_id: a.preset_id, return_home: a.return_home } : a.mode === "patrol" ? { patrol_id: a.patrol_id, repeat: a.repeat } : { enable: !!a.enable }) }
        : { kind: "keep", index: a.index }
      );
      const devices = noScope ? [] : [...n.devices];
      const zones = Object.fromEntries(devices.map((mac) => [mac, n.zones[mac] || { zone: [], line: [], loiter: [] }]));
      let req;
      if (n.id) {
        // send only the parts that changed, so untouched parts stay exactly as Protect has them
        const now = this._snapshot(n);
        req = { type: "protect_rules/update", rule_id: n.id, ...(n.base ? { base: n.base } : {}), name: n.name.trim(), cooldown_enabled: n.cool, cooldown_minutes: n.mins };
        if (now.triggers !== n.was.triggers) Object.assign(req, { triggers: [...n.triggers] }, values ? { trigger_values: values } : {});
        if (now.also !== n.was.also) req.also = also;
        if (now.sched !== n.was.sched && schedule) req.schedule = schedule;
        if (now.scope !== n.was.scope) Object.assign(req, { devices, scope: n.scope, zones });
        if (now.actions !== n.was.actions) req.actions = actions;
      } else {
        req = { type: "protect_rules/create", name: n.name.trim(), triggers: [...n.triggers], ...(values ? { trigger_values: values } : {}), ...(also.length ? { also } : {}), ...(schedule && schedule.mode !== "always" ? { schedule } : {}), devices, scope: n.scope, zones, actions, cooldown_enabled: n.cool, cooldown_minutes: n.mins };
      }
      root.querySelector(".lb").classList.add("busy");
      try {
        const res = await this._hass.callWS(req);
        this._openDetail(n.id || res.rule_id); // show what Protect actually stored
      } catch (err) {
        root.querySelector(".lb").classList.remove("busy");
        msg.textContent = err?.message || String(err);
      }
    };
  }
}

// (loaded twice, e.g. also as a dashboard resource, it is defined once)
if (!customElements.get("protect-rules-card")) {
  customElements.define("protect-rules-card", ProtectRulesCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "protect-rules-card",
    name: "Protect Alarm Rules",
    description: "UniFi Protect Alarm Manager rules as a searchable, sortable table.",
  });
}
