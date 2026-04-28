/**
 * ColorSplash XG custom Lovelace card.
 *
 * Visual design follows HA's native more-info-light dialog
 * (favorite-color-button, state-control-light-color-picker,
 * tile-card-features patterns from the home-assistant/frontend
 * repo). Adapted to our constrained palette + show-scrub
 * picker:
 *
 *   - Big tile-style toggle button (full-width, tap to toggle)
 *   - HSV color wheel (drag to pick → light.turn_on rgb_color)
 *   - Swatches row: 5 solids + Return badge + saved presets
 *   - Effect dropdown: collapsible list with circular show
 *     swatch (gradient or discrete-slice) per entry
 *   - Lock button at the bottom
 *
 * Mirrors HA's circular-swatch convention: 40 px discs, white /
 * light colors get a `--divider-color` border; dark colors
 * have a transparent border so the swatch reads cleanly on both
 * light and dark themes. Active selections get a primary-color
 * outline.
 *
 * Resolves issue #41. See dashboard/README.md for install.
 */

const VERSION = "0.9.7";

// 5 documented solid presets, in rainbow order with white at
// the front. Return badge follows the swatches in _buildHTML.
const SOLIDS = [
  {name: "Arctic White",       btn: "pool_arctic_white",       hex: "#FFFFFF"},
  {name: "Brazilian Red",      btn: "pool_brazilian_red",      hex: "#FF0000"},
  {name: "New Zealand Green",  btn: "pool_new_zealand_green",  hex: "#00FF00"},
  {name: "Parisian Blue",      btn: "pool_parisian_blue",      hex: "#0000FF"},
  {name: "Miami Pink",         btn: "pool_miami_pink",         hex: "#FF00FF"},
];

// 7 documented shows. `discrete: true` → preview tile renders
// hard-edged color slices instead of a smooth gradient (Nova
// and Super Nova jump between colors without blending).
const SHOWS = [
  {
    name: "Nova",
    effect: "Nova",
    discrete: true,
    gradient: ["#FEEA00", "#71CD2E", "#02ADF9", "#1649D5", "#DC0BB3",
               "#FFBF1C", "#17B63F", "#00B2E1", "#205ADB", "#CB00A9"],
  },
  {
    name: "Super Nova",
    effect: "Super Nova",
    discrete: true,
    // Same colors as Nova but rendered twice so each slice is
    // half-width — Super Nova switches ~3× as fast as Nova.
    gradient: ["#FEEA00", "#71CD2E", "#02ADF9", "#1649D5", "#DC0BB3",
               "#FFBF1C", "#17B63F", "#00B2E1", "#205ADB", "#CB00A9",
               "#FEEA00", "#71CD2E", "#02ADF9", "#1649D5", "#DC0BB3",
               "#FFBF1C", "#17B63F", "#00B2E1", "#205ADB", "#CB00A9"],
  },
  {
    name: "Northern Lights",
    effect: "Northern Lights",
    gradient: ["#FD3000", "#FFC000", "#54CD00", "#01C2F4", "#0E65F7",
               "#FD01AE"],
  },
  {
    name: "Tidal Wave",
    effect: "Tidal Wave",
    gradient: ["#00A351", "#04886E", "#0675AB"],
  },
  {
    name: "Patriot Dream",
    effect: "Patriot Dream",
    gradient: ["#E32139", "#FFFFFF", "#398CC6",
               "#E32139", "#FFFFFF", "#398CC6"],
  },
  {
    name: "Desert Skies",
    effect: "Desert Skies",
    gradient: ["#FFA000", "#FF6080", "#FF00C0"],
  },
  {
    name: "Peruvian Paradise",
    effect: "Peruvian Paradise",
    gradient: ["#FFFFFF", "#FF40E0", "#00C0A0"],
  },
];

const DEFAULT_PREFIX = "colorsplash_xg_bridge_";

const DEFAULTS = {
  prefix: DEFAULT_PREFIX,
  light_entity: null,
  lock_entity: null,
  return_entity: null,
  recipe_entity: null,         // text_sensor "0xNN,wait_ms_decimal"
  presets_entity: null,        // text_sensor with JSON preset list
  scrub_service: "esphome.colorsplash_xg_bridge_pool_scrub",
  preset_save_service:
      "esphome.colorsplash_xg_bridge_color_preset_save",
  preset_recall_service:
      "esphome.colorsplash_xg_bridge_color_preset_recall",
  preset_delete_service:
      "esphome.colorsplash_xg_bridge_color_preset_delete",
  presets: [],                 // optional YAML-defined static list
};

// Curated reference colors for auto-suggested preset names.
// Keep ~50 entries — broad coverage of the visible-light wheel
// without bloating the card. When a save fires, we pick the
// nearest entry by squared-RGB distance and offer that name as
// the default.
const COLOR_NAME_REFS = [
  ["#ffffff","White"],     ["#000000","Black"],
  ["#7f7f7f","Grey"],
  ["#ff0000","Red"],       ["#dc143c","Crimson"],
  ["#b22222","Firebrick"], ["#ff6347","Tomato"],
  ["#ff7f50","Coral"],     ["#fa8072","Salmon"],
  ["#ffa07a","Light Salmon"],
  ["#ff4500","Orange Red"],["#ffa500","Orange"],
  ["#ff8c00","Dark Orange"],
  ["#ffd700","Gold"],      ["#ffff00","Yellow"],
  ["#ffe4b5","Moccasin"],
  ["#9acd32","Yellow Green"],
  ["#7cfc00","Lawn Green"],
  ["#00ff00","Green"],     ["#32cd32","Lime"],
  ["#228b22","Forest Green"],
  ["#2e8b57","Sea Green"], ["#3cb371","Medium Sea Green"],
  ["#00fa9a","Mint"],      ["#7fffd4","Aquamarine"],
  ["#00ced1","Turquoise"], ["#40e0d0","Turquoise"],
  ["#00ffff","Cyan"],      ["#5f9ea0","Cadet Blue"],
  ["#87ceeb","Sky Blue"],  ["#1e90ff","Dodger Blue"],
  ["#0000ff","Blue"],      ["#4169e1","Royal Blue"],
  ["#000080","Navy"],      ["#191970","Midnight Blue"],
  ["#4b0082","Indigo"],
  ["#8a2be2","Blue Violet"],
  ["#9400d3","Violet"],    ["#9370db","Purple"],
  ["#ba55d3","Orchid"],
  ["#ff00ff","Magenta"],   ["#da70d6","Pink Orchid"],
  ["#ff1493","Pink"],      ["#ff69b4","Hot Pink"],
  ["#ffb6c1","Light Pink"],
  ["#dc6b9c","Sunset Magenta"],
  ["#5fa8c4","Pool Cyan"],
  ["#a0522d","Sienna"],    ["#8b4513","Saddle Brown"],
];

// Auto-test fire on every preset-edit nudge — debounce so a
// burst of ±10/±100 taps fires the recipe only once when the
// user settles. Same idea as the wheel/slider commit debounce
// but with its own timer so the picker's own commits don't
// accidentally cancel a pending edit-modal test.
const TEST_FIRE_DEBOUNCE_MS = 600;

const WHEEL_SIZE = 220;       // px — outer diameter of the HSV wheel
const SLIDER_WIDTH = 100;     // px — vertical slider thickness
                              // (HA's brightness slider uses 130 px; we
                              // shrink slightly so the picker row fits
                              // in a typical Lovelace card width)
const SLIDER_RADIUS = 28;     // px — heavily rounded, approx HA's 6xl
const SLIDER_HANDLE_MARGIN = 12;  // px — distance from edge of bar to handle bar
const SLIDER_HANDLE_HEIGHT = 4;   // px — handle bar thickness
const BRIGHTNESS_MIN = 0.05;  // floor — V=0 would just be black for any hue
// Debounce window — after the last pointer interaction on the
// wheel or slider, wait this long before sending the resolved
// rgb_color to the fixture. Lets the user adjust both controls
// to settle on the intended hue + brightness before the LUT
// match fires.
const SEND_DEBOUNCE = 600;    // ms


// ─── Helpers ────────────────────────────────────────────────────────

function hexToRgb(hex) {
  const c = hex.replace("#", "");
  return [
    parseInt(c.slice(0, 2), 16),
    parseInt(c.slice(2, 4), 16),
    parseInt(c.slice(4, 6), 16),
  ];
}

// Matches HA's luminosity() helper from frontend/src/common/color/rgb.
// Returns sRGB-weighted luminance in 0..1; > 0.8 reads as "light".
function luminosityRgb(r, g, b) {
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
}
function luminosity(hex) {
  const [r, g, b] = hexToRgb(hex);
  return luminosityRgb(r, g, b);
}

// Build a CSS gradient string for a show preview swatch. Uses
// hard stops for `discrete` shows (Nova / Super Nova) so the
// color bands have crisp edges.
function showGradient(sh) {
  if (sh.gradient.length === 1) return sh.gradient[0];
  if (sh.discrete) {
    const n = sh.gradient.length;
    const stops = sh.gradient.flatMap((c, i) => [
      `${c} ${(i / n) * 100}%`,
      `${c} ${((i + 1) / n) * 100}%`,
    ]);
    return `linear-gradient(135deg, ${stops.join(", ")})`;
  }
  return `linear-gradient(135deg, ${sh.gradient.join(", ")})`;
}

// HSV → RGB at full V (1.0). h is 0..360, s is 0..1.
function hsvToRgb(h, s, v) {
  const c = v * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  let r1, g1, b1;
  if (h < 60)       [r1, g1, b1] = [c, x, 0];
  else if (h < 120) [r1, g1, b1] = [x, c, 0];
  else if (h < 180) [r1, g1, b1] = [0, c, x];
  else if (h < 240) [r1, g1, b1] = [0, x, c];
  else if (h < 300) [r1, g1, b1] = [x, 0, c];
  else              [r1, g1, b1] = [c, 0, x];
  return [
    Math.round((r1 + m) * 255),
    Math.round((g1 + m) * 255),
    Math.round((b1 + m) * 255),
  ];
}

// Port of the contrast adjustment from HA's
// ha-state-control-light-brightness: very desaturated colors get
// either a saturation bump (S→0.4) or a value reduction (V→225/255)
// for near-whites, so the slider tint stays visible against the
// card background. Returns adjusted [r, g, b] in 0..255.
function adjustSliderColor(r, g, b) {
  let [h, s, v] = rgbToHsv(r, g, b);
  if (s < 0.4) {
    if (s < 0.1) {
      v = 225 / 255;
    } else {
      s = 0.4;
    }
  }
  return hsvToRgb(h, s, v);
}

function rgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;
  let h = 0;
  if (d !== 0) {
    if (max === r)      h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else                h = (r - g) / d + 4;
    h *= 60;
    if (h < 0) h += 360;
  }
  const s = max === 0 ? 0 : d / max;
  return [h, s, max];
}

// Pre-render the HSV wheel into an offscreen canvas exactly once.
// Returns a data URL that can be set as <img src=...>; embedding
// as an image avoids re-rasterising on every card render.
//
// Orientation matches HA's native ha-state-control-light-color-picker:
// red sits at 3 o'clock (hue 0°) and hue sweeps counter-clockwise
// (yellow → green → cyan → blue → magenta → back to red).
function buildWheelDataUrl(size) {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(size, size);
  const r = size / 2;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = x - r;
      const dy = y - r;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const idx = (y * size + x) * 4;
      if (dist > r) {
        img.data[idx + 3] = 0;
        continue;
      }
      // CSS y is flipped (positive y points DOWN). Negate dy so
      // the angle works in standard math convention: 0 at +x
      // (right / 3 o'clock), positive angles counter-clockwise.
      const angle = Math.atan2(-dy, dx);
      const h = ((angle * 180 / Math.PI) + 360) % 360;
      const s = Math.min(1, dist / r);
      const [R, G, B] = hsvToRgb(h, s, 1);
      img.data[idx]     = R;
      img.data[idx + 1] = G;
      img.data[idx + 2] = B;
      img.data[idx + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return canvas.toDataURL();
}


// ─── Card class ─────────────────────────────────────────────────────

let WHEEL_IMAGE_CACHE = null;

class ColorSplashCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: "open"});
    this._delegated = false;
    this._lastRenderedKey = "";
    this._effectsOpen = false;
    this._wheelDragging = false;
    this._brightnessDragging = false;
    // Edit-modal time-format mode: "ms" (default) or "s". Lives
    // on the instance so toggling persists across re-renders.
    this._timeFormat = "ms";
    this._pendingTestFireTimer = null;
    this._wheelCursor = null;  // {hue, sat} or null
    // Last (h, s) the user picked from the wheel — kept so a
    // brightness drag re-emits the same hue with the new V.
    this._lastHs = null;
    // Last V the user picked from the slider — kept so a wheel
    // drag emits the same V (without bouncing back to whatever
    // HA last reported).
    this._lastV = null;
    // Debounced send: rgb tuple to commit after SEND_DEBOUNCE
    // ms of inactivity on either control. Cleared once sent.
    this._pendingRgb = null;
    this._pendingTimer = null;

    if (!WHEEL_IMAGE_CACHE) {
      WHEEL_IMAGE_CACHE = buildWheelDataUrl(WHEEL_SIZE);
    }
  }

  setConfig(config) {
    const merged = {...DEFAULTS, ...(config || {})};
    const prefix = merged.prefix || "";
    merged.light_entity = merged.light_entity
        || `light.${prefix}pool_light`;
    merged.lock_entity = merged.lock_entity
        || `button.${prefix}pool_color_lock`;
    merged.return_entity = merged.return_entity
        || `button.${prefix}pool_color_return`;
    merged.recipe_entity = merged.recipe_entity
        || `sensor.${prefix}pool_last_picked_recipe`;
    merged.presets_entity = merged.presets_entity
        || `sensor.${prefix}pool_color_presets`;
    this._config = merged;
  }

  // Read user presets from the bridge's pool_color_presets
  // text_sensor (JSON array). Single source of truth — survives
  // browser swaps and is addressable by HA automations via the
  // color_preset_recall service.
  _readUserPresets() {
    const cfg = this._config;
    const hass = this._hass;
    if (!hass) return [];
    const st = hass.states[cfg.presets_entity];
    if (!st || !st.state || st.state === "unavailable"
        || st.state === "unknown" || st.state === "") {
      return [];
    }
    try {
      const parsed = JSON.parse(st.state);
      if (!Array.isArray(parsed)) return [];
      return parsed;
    } catch (e) {
      console.warn("[colorsplash-xg-card] presets JSON parse error",
                   st.state, e);
      return [];
    }
  }

  // Service-call wrappers. Use indexOf("." ) instead of split so
  // the suffix can contain dots without breaking.
  _callService(serviceFqn, payload) {
    const hass = this._hass;
    if (!hass) return Promise.reject(new Error("hass not attached"));
    const dotIdx = serviceFqn.indexOf(".");
    if (dotIdx < 0) {
      return Promise.reject(new Error(
          `service "${serviceFqn}" missing '.'`));
    }
    return hass.callService(
        serviceFqn.slice(0, dotIdx),
        serviceFqn.slice(dotIdx + 1),
        payload);
  }

  // Suggest a name for a freshly-saved preset based on the RGB
  // it represents. Pick the nearest curated name in squared-RGB
  // distance.
  _suggestPresetName(r, g, b) {
    let bestName = "Custom Color";
    let bestDist = Infinity;
    for (const [hex, name] of COLOR_NAME_REFS) {
      const [er, eg, eb] = hexToRgb(hex);
      const d = (er - r) ** 2 + (eg - g) ** 2 + (eb - b) ** 2;
      if (d < bestDist) {
        bestDist = d;
        bestName = name;
      }
    }
    return bestName;
  }

  // Build a slug from a display name. lowercase + alphanumeric +
  // underscore, max 15 chars. If the resulting slug collides with
  // an existing preset, append _2, _3, etc.
  _slugify(name) {
    let base = String(name).toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "")
        .slice(0, 15);
    if (!base) base = "preset";
    const taken = new Set(this._readUserPresets()
        .map((p) => p.slug)
        .filter((s) => typeof s === "string"));
    if (!taken.has(base)) return base;
    for (let n = 2; n < 99; n++) {
      const trimLen = Math.max(1, 15 - String(n).length - 1);
      const candidate = `${base.slice(0, trimLen)}_${n}`;
      if (!taken.has(candidate)) return candidate;
    }
    return `${base.slice(0, 13)}_${Date.now() % 1000}`;
  }

  // Read the current pick recipe from the bridge's exposed
  // text_sensor (format: "0xNN,wait_ms_decimal"). Returns
  // {start_byte, wait_ms} or null if no pick has happened yet.
  _readCurrentRecipe() {
    const cfg = this._config;
    const hass = this._hass;
    if (!hass) return null;
    const st = hass.states[cfg.recipe_entity];
    if (!st || !st.state || st.state === "unknown" ||
        st.state === "unavailable") {
      return null;
    }
    const m = String(st.state).match(/^0x([0-9a-f]{1,2}),(\d+)$/i);
    if (!m) return null;
    return {
      start_byte: parseInt(m[1], 16),
      wait_ms:    parseInt(m[2], 10),
    };
  }

  // Merge YAML-defined static presets with bridge-stored ones.
  // YAML presets are read-only (no _user flag); bridge presets
  // carry _user: true and a `slug` (their automation address).
  _allPresets() {
    const cfg = this._config;
    const yaml = (Array.isArray(cfg.presets) ? cfg.presets : [])
        .map((p) => ({...p, _user: false}));
    const user = this._readUserPresets()
        .map((p) => ({...p, _user: true}));
    return [...yaml, ...user];
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 7;
  }

  // ---- rendering ----

  _render() {
    if (!this._hass || !this._config) return;
    const cfg = this._config;
    const lightState = this._hass.states[cfg.light_entity];
    const isOn = lightState && lightState.state === "on";
    const attrs = lightState ? lightState.attributes || {} : {};
    const activeEffect = attrs.effect || null;
    const rgbColor = Array.isArray(attrs.rgb_color) ? attrs.rgb_color : null;
    const lightFound = !!lightState;

    const presetsState = this._hass &&
        this._hass.states[cfg.presets_entity];
    const key = [
      lightFound, isOn, activeEffect || "",
      rgbColor ? rgbColor.join(",") : "",
      this._effectsOpen,
      JSON.stringify(cfg.presets || []),
      presetsState ? presetsState.state : "",
      this._readCurrentRecipe() ? "have-recipe" : "no-recipe",
      this._editingSlug || "",
    ].join("|");
    if (key === this._lastRenderedKey && this.shadowRoot.firstChild) {
      return;
    }
    this._lastRenderedKey = key;

    this.shadowRoot.innerHTML =
        `<style>${this._buildStyle()}</style>` +
        this._buildHTML(isOn, activeEffect, lightFound, rgbColor);

    if (!this._delegated) {
      this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
      this._delegated = true;
    }

    this._wireWheel();
  }

  _buildStyle() {
    return `
      :host {
        display: block;
      }
      .card {
        background: var(--ha-card-background,
                         var(--card-background-color, #1c1c1e));
        color: var(--primary-text-color, #fff);
        border-radius: var(--ha-card-border-radius, 12px);
        padding: 16px;
        box-shadow: var(--ha-card-box-shadow, none);
        border: var(--ha-card-border-width, 1px) solid
                var(--ha-card-border-color,
                     var(--divider-color, transparent));
      }

      /* ─── Big tile-style toggle ─────────────────────────────
         Mirrors HA's tile-card layout: icon on the left, name +
         state stacked, switch indicator on the right. The whole
         tile is the click target. */
      .tile {
        display: flex;
        align-items: center;
        gap: 14px;
        background: var(--secondary-background-color, #2c2c2e);
        border: 1px solid transparent;
        border-radius: 14px;
        padding: 14px 16px;
        cursor: pointer;
        width: 100%;
        text-align: left;
        color: inherit;
        font: inherit;
        transition: background-color 0.15s ease;
      }
      .tile:hover {
        background: var(--divider-color, #3a3a3c);
      }
      .tile.on {
        background: rgba(255, 200, 80, 0.18);
      }
      .tile-icon {
        flex: 0 0 auto;
        width: 42px;
        height: 42px;
        border-radius: 50%;
        background: var(--secondary-background-color, #1c1c1e);
        display: flex;
        align-items: center;
        justify-content: center;
        --mdc-icon-size: 24px;
        color: var(--state-icon-color, #a0a0a0);
        border: 1px solid transparent;
        background-clip: padding-box;
        transition: background-color 0.18s ease, color 0.18s ease;
      }
      /* Mirrors the .swatch.light convention: when the tile is
         showing a light/white tint, the icon itself gets a
         divider-colored outline so the bulb shape stays
         readable. ha-icon renders as a filled SVG with no
         native stroke, so we fake one via four offset
         drop-shadow filters. */
      .tile-icon.light ha-icon {
        filter:
          drop-shadow(1px 0 0 var(--divider-color, rgba(127,127,127,0.7)))
          drop-shadow(-1px 0 0 var(--divider-color, rgba(127,127,127,0.7)))
          drop-shadow(0 1px 0 var(--divider-color, rgba(127,127,127,0.7)))
          drop-shadow(0 -1px 0 var(--divider-color, rgba(127,127,127,0.7)));
      }
      .tile-text {
        flex: 1 1 auto;
        display: flex;
        flex-direction: column;
        min-width: 0;
      }
      .tile-name {
        font-size: 1em;
        font-weight: 500;
        color: var(--primary-text-color, #fff);
      }
      .tile-state {
        font-size: 0.85em;
        color: var(--secondary-text-color, #a0a0a0);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      /* iOS-style switch — grey track + white knob when off,
         green track + white knob when on. Theme-independent so
         it always reads "off=grey, on=green". */
      .toggle-indicator {
        position: relative;
        width: 40px;
        height: 22px;
        background: #8e8e93;
        border-radius: 999px;
        flex: 0 0 auto;
        pointer-events: none;
        transition: background-color 0.18s ease;
      }
      .toggle-indicator::before {
        content: "";
        position: absolute;
        top: 2px;
        left: 2px;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: #ffffff;
        box-shadow: 0 1px 3px rgba(0,0,0,0.3);
        transition: left 0.18s ease;
      }
      .tile.on .toggle-indicator {
        background: #34c759;
      }
      .tile.on .toggle-indicator::before {
        left: 20px;
      }

      /* ─── Section heading ──────────────────────────────────── */
      .section-label {
        font-size: 0.72em;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--secondary-text-color, #a0a0a0);
        margin: 18px 0 10px;
      }

      /* ─── Color picker row (wheel + brightness slider) ──── */
      .picker-row {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 14px;
        margin: 4px 0 8px;
      }

      /* ─── Color wheel ──────────────────────────────────────
         Pre-rendered HSV wheel; the cursor dot is positioned
         absolutely over it to indicate the current selection. */
      .wheel-wrap {
        position: relative;
        width: ${WHEEL_SIZE}px;
        height: ${WHEEL_SIZE}px;
        flex: 0 0 auto;
        touch-action: none;
        user-select: none;
        -webkit-user-select: none;
      }
      .wheel {
        width: 100%;
        height: 100%;
        display: block;
        border-radius: 50%;
        cursor: crosshair;
        -webkit-user-drag: none;
      }
      .wheel-cursor {
        position: absolute;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        border: 2px solid #fff;
        box-shadow: 0 1px 4px rgba(0,0,0,0.5),
                    inset 0 0 0 1px rgba(0,0,0,0.4);
        transform: translate(-50%, -50%);
        pointer-events: none;
        opacity: 0;
        transition: opacity 0.12s ease;
      }
      .wheel-cursor.active {
        opacity: 1;
      }

      /* ─── Brightness slider ────────────────────────────────
         Direct port of HA's ha-control-slider (vertical, "start"
         mode, show-handle) as used by ha-state-control-light-
         brightness. Two stacked layers — a faded background and
         a full-opacity bar — share the same colour. The bar's
         transform shifts it down by (1 - value) of its height,
         so when value=1 the bar covers the full track and when
         value=0 it's fully clipped. The handle is a thin white
         bar drawn near the top of the bar so it always lands at
         the value-marker. Tooltip lives to the LEFT of the
         slider and tracks the value vertically. */
      .brightness-wrap {
        position: relative;
        width: ${SLIDER_WIDTH}px;
        height: ${WHEEL_SIZE}px;
        flex: 0 0 auto;
        touch-action: none;
        user-select: none;
        -webkit-user-select: none;
        --cs-color: var(--primary-color, #03a9f4);
        --cs-value: 1;
      }
      .brightness-slider {
        position: relative;
        height: 100%;
        width: 100%;
        border-radius: ${SLIDER_RADIUS}px;
        overflow: hidden;
        cursor: pointer;
      }
      .brightness-bg {
        position: absolute;
        top: 0;
        left: 0;
        height: 100%;
        width: 100%;
        background: var(--cs-color);
        opacity: 0.2;
      }
      .brightness-bar {
        position: absolute;
        bottom: 0;
        left: 0;
        height: 100%;
        width: 100%;
        background: var(--cs-color);
        transform: translate3d(0,
          calc((1 - var(--cs-value)) * 100%), 0);
        transition: transform 60ms linear;
      }
      .brightness-bar.dragging {
        transition: none;
      }
      /* Handle bar at the top of the filled portion. Sits inside
         the bar so it moves with the value. */
      .brightness-bar::after {
        content: "";
        position: absolute;
        top: ${SLIDER_HANDLE_MARGIN}px;
        left: 0;
        right: 0;
        margin: auto;
        width: 50%;
        height: ${SLIDER_HANDLE_HEIGHT}px;
        border-radius: ${SLIDER_HANDLE_HEIGHT}px;
        background: #ffffff;
      }
      /* Tooltip — positioned left of the slider, vertical pos
         tracks the value. Visible only while dragging. */
      .brightness-tooltip {
        position: absolute;
        right: calc(100% + 8px);
        bottom: calc(var(--cs-value) * 100% - 12px);
        background: var(--clear-background-color,
                        var(--card-background-color, #1c1c1e));
        color: var(--primary-text-color, #fff);
        padding: 4px 10px;
        border-radius: 10px;
        font-size: 0.9em;
        font-weight: 500;
        white-space: nowrap;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.25);
        pointer-events: none;
        opacity: 0;
        transition: opacity 180ms ease, bottom 60ms linear;
      }
      .brightness-tooltip.visible {
        opacity: 1;
      }

      /* ─── Swatch grid ─────────────────────────────────────
         Mirrors HA's ha-favorite-color-button: 40 px discs,
         pill-shaped (i.e. circle when square). Light colors
         get a divider-colored border so they show against
         pale backgrounds; dark ones get transparent. */
      .swatches {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        gap: 12px;
        margin-bottom: 16px;
      }
      .swatch {
        position: relative;
        width: 40px;
        height: 40px;
        border-radius: 999px;
        border: 1px solid transparent;
        cursor: pointer;
        transition: transform 0.08s ease,
                    box-shadow 0.15s ease;
        background-clip: padding-box;
        padding: 0;
        font: inherit;
      }
      .swatch.light {
        border-color: var(--divider-color, rgba(127,127,127,0.4));
      }
      .swatch:active {
        transform: scale(0.92);
      }
      .swatch:focus-visible {
        box-shadow: 0 0 0 2px var(--primary-color, #03a9f4);
        outline: none;
      }
      .swatch.return {
        background: var(--secondary-background-color, #2c2c2e);
        display: flex;
        align-items: center;
        justify-content: center;
        --mdc-icon-size: 22px;
        color: var(--primary-text-color, #fff);
      }
      /* mdi:lock-reset has the recall arrow on the right side,
         which shifts the visual center off to the right. Nudge
         the glyph 2 px left so the lock circle inside the icon
         sits concentric with the swatch circle. */
      .swatch.return ha-icon {
        transform: translateX(-2px);
      }

      /* ─── Effect dropdown ───────────────────────────────── */
      .effect-section {
        margin-bottom: 14px;
      }
      .effect-trigger {
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        background: var(--secondary-background-color, #2c2c2e);
        color: var(--primary-text-color, #fff);
        border: none;
        border-radius: 18px;
        padding: 8px 14px;
        cursor: pointer;
        font-size: 0.95em;
        text-align: left;
        transition: background-color 0.15s ease;
      }
      .effect-trigger:hover {
        background: var(--divider-color, #3a3a3c);
      }
      .effect-icon {
        --mdc-icon-size: 20px;
        line-height: 1;
        flex: 0 0 auto;
      }
      .effect-trigger .chevron {
        margin-left: auto;
        font-size: 0.7em;
        opacity: 0.7;
        transform: rotate(0deg);
        transition: transform 0.18s ease;
      }
      .effect-trigger.open .chevron {
        transform: rotate(180deg);
      }
      .effect-list {
        display: none;
        flex-direction: column;
        gap: 4px;
        margin-top: 8px;
        padding: 4px 0;
      }
      .effect-list.open {
        display: flex;
      }
      .effect-item {
        display: flex;
        align-items: center;
        gap: 12px;
        background: transparent;
        border: none;
        color: inherit;
        padding: 8px 12px;
        cursor: pointer;
        border-radius: 8px;
        text-align: left;
        font: inherit;
        width: 100%;
      }
      .effect-item:hover {
        background: var(--secondary-background-color, #2c2c2e);
      }
      .effect-swatch {
        width: 24px;
        height: 24px;
        border-radius: 50%;
        flex: 0 0 auto;
        border: 1px solid var(--divider-color,
                              rgba(127,127,127,0.4));
      }
      .effect-swatch.none {
        background: transparent;
        border-style: dashed;
      }
      .effect-item.active {
        background: var(--secondary-background-color, #2c2c2e);
        font-weight: 600;
      }
      .effect-item.active .effect-swatch {
        box-shadow: 0 0 0 2px var(--primary-color, #03a9f4);
      }

      /* ─── Save preset button ──────────────────────────────
         Shown only when the bridge has reported a fresh pick
         recipe and the light is on with an rgb_color. */
      .save-preset-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        width: 100%;
        background: transparent;
        color: var(--primary-text-color, #fff);
        border: 1px dashed var(--divider-color, rgba(127,127,127,0.5));
        border-radius: 10px;
        padding: 8px;
        margin-bottom: 12px;
        font-size: 0.9em;
        cursor: pointer;
        --mdc-icon-size: 18px;
        transition: background-color 0.15s ease;
      }
      .save-preset-btn:hover {
        background: var(--secondary-background-color, #2c2c2e);
      }
      .save-preset-btn:active {
        transform: scale(0.99);
      }
      /* User-saved preset swatches: a primary-color halo so they
         read clearly against the YAML / built-in solid swatches.
         Also a tiny bookmark badge in the corner to signal "you
         can long-press / right-click to delete this one." */
      .swatch.preset.user {
        box-shadow: 0 0 0 2px var(--primary-color, #03a9f4);
      }
      .swatch.preset.user::after {
        content: "";
        position: absolute;
        top: -3px;
        right: -3px;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: var(--primary-color, #03a9f4);
        border: 2px solid var(--ha-card-background,
                              var(--card-background-color, #1c1c1e));
        pointer-events: none;
      }

      /* ─── Lock button ───────────────────────────────────── */
      .lock-btn {
        margin-top: 8px;
        width: 100%;
        background: var(--state-active-color, #f9a825);
        color: #000;
        border: none;
        border-radius: 10px;
        padding: 10px;
        font-size: 0.95em;
        font-weight: 600;
        cursor: pointer;
        transition: transform 0.08s ease;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        --mdc-icon-size: 20px;
      }
      .lock-btn:active {
        transform: scale(0.97);
      }

      /* ─── Edit-preset modal ───────────────────────────────
         Overlays the whole card via fixed positioning. The
         backdrop click closes; clicks inside the modal body
         don't propagate to the backdrop. */
      .modal-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.55);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
        animation: cs-fade-in 120ms ease;
      }
      @keyframes cs-fade-in {
        from { opacity: 0; }
        to   { opacity: 1; }
      }
      .edit-modal {
        background: var(--ha-card-background,
                         var(--card-background-color, #1c1c1e));
        color: var(--primary-text-color, #fff);
        border-radius: 14px;
        padding: 16px 18px;
        min-width: 320px;
        max-width: 90vw;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);
      }
      .edit-modal * {
        box-sizing: border-box;
      }
      .modal-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        font-size: 1.05em;
        font-weight: 600;
        padding-bottom: 12px;
        border-bottom: 1px solid var(--divider-color,
                                       rgba(127,127,127,0.25));
      }
      .modal-close {
        background: transparent;
        border: none;
        color: inherit;
        cursor: pointer;
        padding: 4px;
        --mdc-icon-size: 20px;
      }
      .modal-body {
        padding: 14px 0;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .modal-row {
        display: flex;
        align-items: center;
        gap: 12px;
      }
      .modal-row.tight {
        gap: 6px;
      }
      .modal-swatch-label {
        position: relative;
        flex: 0 0 auto;
        cursor: pointer;
      }
      .modal-swatch {
        width: 56px;
        height: 56px;
        border-radius: 50%;
        border: 1px solid var(--divider-color,
                              rgba(127,127,127,0.4));
      }
      /* Hide the native color input but keep it overlapping the
         swatch so a click on the swatch opens the OS color
         picker. */
      .modal-swatch-label input[type="color"] {
        position: absolute;
        inset: 0;
        opacity: 0;
        cursor: pointer;
        border: none;
        background: transparent;
        padding: 0;
      }
      .modal-hint-small {
        font-size: 0.75em;
        color: var(--secondary-text-color, #a0a0a0);
        line-height: 1.4;
        margin-top: 4px;
      }
      .modal-meta {
        flex: 1 1 auto;
        font-size: 0.9em;
        line-height: 1.5;
        color: var(--secondary-text-color, #a0a0a0);
      }
      .modal-hex {
        color: var(--primary-text-color, #fff);
        font-weight: 600;
        font-family: ui-monospace, "SF Mono", Menlo, monospace;
      }
      .modal-label {
        display: flex;
        flex-direction: column;
        gap: 6px;
        font-size: 0.85em;
        color: var(--secondary-text-color, #a0a0a0);
      }
      .modal-label input[type="text"],
      .modal-label input[type="number"] {
        background: var(--secondary-background-color, #2c2c2e);
        color: var(--primary-text-color, #fff);
        border: 1px solid var(--divider-color,
                              rgba(127,127,127,0.35));
        border-radius: 8px;
        padding: 8px 10px;
        font-size: 1em;
        font-family: inherit;
        width: 100%;
      }
      .modal-label input[name="slug"] {
        font-family: ui-monospace, "SF Mono", Menlo, monospace;
      }
      .modal-label-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }
      .modal-format-toggle {
        background: var(--secondary-background-color, #2c2c2e);
        color: var(--primary-text-color, #fff);
        border: 1px solid var(--divider-color,
                              rgba(127,127,127,0.35));
        border-radius: 6px;
        padding: 2px 8px;
        font-size: 0.78em;
        font-family: ui-monospace, "SF Mono", Menlo, monospace;
        cursor: pointer;
        min-width: 32px;
      }
      /* Tight nudge row wraps to two lines on narrow modals so
         the input stays usable. */
      .modal-nudges {
        flex-wrap: wrap;
        justify-content: center;
      }
      .modal-nudges input[type="number"] {
        flex: 1 1 90px;
        min-width: 0;
      }
      .modal-nudges button {
        font-size: 0.85em;
        padding: 6px 8px;
        min-width: 38px;
      }
      .modal-hint {
        font-size: 0.78em;
        color: var(--secondary-text-color, #a0a0a0);
        line-height: 1.4;
      }
      .modal-hint code {
        background: var(--secondary-background-color, #2c2c2e);
        padding: 1px 5px;
        border-radius: 4px;
        font-size: 0.95em;
      }
      .modal-row.tight input[type="number"] {
        flex: 1 1 auto;
        text-align: center;
      }
      .modal-row.tight button {
        background: var(--secondary-background-color, #2c2c2e);
        color: var(--primary-text-color, #fff);
        border: 1px solid var(--divider-color,
                              rgba(127,127,127,0.35));
        border-radius: 8px;
        padding: 8px 12px;
        cursor: pointer;
        font-weight: 600;
      }
      .modal-test {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        background: var(--secondary-background-color, #2c2c2e);
        color: var(--primary-text-color, #fff);
        border: 1px dashed var(--divider-color,
                                rgba(127,127,127,0.5));
        border-radius: 10px;
        padding: 8px;
        cursor: pointer;
        --mdc-icon-size: 18px;
      }
      .modal-footer {
        display: flex;
        align-items: center;
        gap: 8px;
        padding-top: 12px;
        border-top: 1px solid var(--divider-color,
                                    rgba(127,127,127,0.25));
      }
      .modal-spacer {
        flex: 1 1 auto;
      }
      .modal-delete {
        display: flex;
        align-items: center;
        gap: 6px;
        background: transparent;
        color: var(--error-color, #d32f2f);
        border: 1px solid var(--error-color, #d32f2f);
        border-radius: 8px;
        padding: 8px 12px;
        cursor: pointer;
        --mdc-icon-size: 18px;
      }
      .modal-cancel,
      .modal-save {
        background: transparent;
        color: var(--primary-text-color, #fff);
        border: 1px solid var(--divider-color,
                              rgba(127,127,127,0.4));
        border-radius: 8px;
        padding: 8px 14px;
        cursor: pointer;
        font-weight: 600;
      }
      .modal-save {
        background: var(--primary-color, #03a9f4);
        color: #fff;
        border-color: var(--primary-color, #03a9f4);
      }

      /* ─── Error banner ──────────────────────────────────── */
      .error-banner {
        background: var(--error-color, #d32f2f);
        color: #fff;
        padding: 8px 12px;
        border-radius: 6px;
        margin-bottom: 10px;
        font-size: 0.85em;
        line-height: 1.4;
      }
      .error-banner code {
        background: rgba(0,0,0,0.25);
        padding: 1px 4px;
        border-radius: 3px;
        font-size: 0.95em;
      }
    `;
  }

  _buildHTML(isOn, activeEffect, lightFound, rgbColor) {
    const cfg = this._config;
    const tileClass = isOn ? "tile on" : "tile";
    const hasEffect = activeEffect && activeEffect !== "None";

    const errorBanner = lightFound ? "" : `
      <div class="error-banner">
        Entity <code>${cfg.light_entity}</code> not found in
        Home Assistant. Add a <code>prefix:</code> override to
        the card's YAML config or look up the real ID in
        Developer Tools → States.
      </div>`;

    // Big tile state line.
    let stateText;
    if (!isOn) {
      stateText = "Off";
    } else if (hasEffect) {
      stateText = activeEffect;
    } else if (rgbColor) {
      stateText = `On — RGB ${rgbColor.join(", ")}`;
    } else {
      stateText = "On";
    }

    // Lightbulb tint — fill the icon with the last selected
    // color. Retained even while a show is running because
    // dismissing the effect (effect: None) returns the fixture
    // to that color, so it represents the "underlying" state.
    //
    // Background tint inverts based on lightness: dark colors get
    // a faint same-hue wash, light/white colors get a darkened
    // version of the same hue so the (light-colored) bulb stays
    // readable against it.
    let iconStyle = "";
    let iconClass = "tile-icon";
    if (isOn && rgbColor) {
      const [rR, rG, rB] = rgbColor;
      const rgbCss = `rgb(${rR},${rG},${rB})`;
      const isLight = luminosityRgb(rR, rG, rB) > 0.8;
      let bgCss;
      if (isLight) {
        const dr = Math.round(rR * 0.30);
        const dg = Math.round(rG * 0.30);
        const db = Math.round(rB * 0.30);
        bgCss = `rgb(${dr},${dg},${db})`;
        iconClass = "tile-icon light";
      } else {
        bgCss = `rgba(${rR},${rG},${rB},0.22)`;
      }
      iconStyle = `color:${rgbCss};background:${bgCss};`;
    }

    // Wheel cursor position. Stays pinned to the last rgb_color
    // even during a show, because that's where the fixture
    // returns when the effect is cleared. The wheel itself is
    // drawn at V=1, so the cursor is placed using the (h, s)
    // derived from the rgb_color regardless of its V — otherwise
    // a dim color would land outside the visible disc.
    let cursorStyle = "";
    let cursorActive = "";
    let brightnessVal = 1;  // 0..1 — drives slider thumb position
    if (isOn && rgbColor) {
      const [h, s, v] = rgbToHsv(rgbColor[0], rgbColor[1], rgbColor[2]);
      brightnessVal = v;
      // h: 0° = right (red), sweeps counter-clockwise. Invert
      // the buildWheel mapping by using cos for x and -sin for
      // y (CSS y is flipped).
      const angleRad = h * Math.PI / 180;
      const cx = WHEEL_SIZE / 2;
      const cy = WHEEL_SIZE / 2;
      const r = s * (WHEEL_SIZE / 2);
      const x = cx + Math.cos(angleRad) * r;
      const y = cy - Math.sin(angleRad) * r;
      cursorStyle = `left:${x}px;top:${y}px;` +
                    `background:rgb(${rgbColor.join(",")});`;
      cursorActive = "active";
    }
    const brightnessPct = Math.round(brightnessVal * 100);

    // CSS vars for the slider: --cs-value is 0..1 driving bar
    // position via translate3d; --cs-color is the contrast-
    // adjusted active hue (matches ha-state-control-light-
    // brightness's color computation).
    let trackTintStyle = `--cs-value:${brightnessVal};`;
    if (rgbColor) {
      const [cR, cG, cB] = adjustSliderColor(
          rgbColor[0], rgbColor[1], rgbColor[2]);
      trackTintStyle += `--cs-color:rgb(${cR},${cG},${cB});`;
    }

    // Solid swatches — circular discs with HA-style border
    // handling for light colors.
    const solidSwatches = SOLIDS.map((s) => {
      const isLight = luminosity(s.hex) > 0.8;
      return `<button class="swatch ${isLight ? "light" : ""}"
                      data-action="solid"
                      data-button="${s.btn}"
                      title="${s.name}"
                      aria-label="${s.name}"
                      style="background:${s.hex};"></button>`;
    }).join("");

    const returnSwatch = `
      <button class="swatch return"
              data-action="return"
              title="Return — replay last-locked color"
              aria-label="Return to last-locked color">
        <ha-icon icon="mdi:lock-reset"></ha-icon>
      </button>`;

    // YAML + localStorage presets, merged. _user=true marks
    // localStorage entries (gain a delete affordance).
    const presets = this._allPresets();
    const presetSwatches = presets.map((p, i) => {
      const isLight = luminosity(p.hex || "#444") > 0.8;
      const tip = `${p.name || ""} — `
                + `start_byte=0x${(p.start_byte || 0).toString(16)} `
                + `wait_ms=${p.wait_ms || 0}`
                + (p._user ? " (user, long-press to delete)" : "");
      const userClass = p._user ? " user" : "";
      return `<button class="swatch preset${userClass} `
            + `${isLight ? "light" : ""}"
                      data-action="preset"
                      data-preset-index="${i}"
                      title="${tip}"
                      aria-label="Preset ${p.name || i}"
                      style="background:${p.hex || "#444"};"></button>`;
    }).join("");

    // "Save current as preset" button — shows when:
    //   - light is on with an rgb_color
    //   - the bridge has reported a recipe (picker has run)
    //   - no show effect is active
    //   - the recipe didn't come from tapping a hardware solid
    //     (solids fire a single byte with wait_ms=0; saving is
    //     redundant since the user can just tap the built-in
    //     swatch)
    //   - the current recipe doesn't already match a saved preset
    const recipe = this._readCurrentRecipe();
    const haveRecipe = !!recipe;
    const isSolidRecipe = recipe && recipe.wait_ms === 0;
    const alreadySaved = recipe && this._allPresets().some((p) =>
        p.start_byte === recipe.start_byte
        && p.wait_ms === recipe.wait_ms);
    const canSave = isOn && haveRecipe && rgbColor
        && !hasEffect && !isSolidRecipe && !alreadySaved;
    const saveBtn = canSave ? `
      <button class="save-preset-btn" data-action="save-preset">
        <ha-icon icon="mdi:bookmark-plus-outline"></ha-icon>
        <span>Save current color as preset…</span>
      </button>` : "";

    // Effect dropdown — collapsible; entries show a circular
    // show swatch (gradient or discrete-slice) instead of a
    // bullet point.
    const triggerLabel = activeEffect && activeEffect !== "None"
        ? activeEffect : "Effect";
    const triggerClass = this._effectsOpen
        ? "effect-trigger open" : "effect-trigger";
    const listClass = this._effectsOpen
        ? "effect-list open" : "effect-list";
    // "None" tops the list so the user can stop a running show.
    // Picking it fires light.turn_on(effect: None); the firmware
    // falls through to last_preset replay and the fixture
    // returns to the most recent solid.
    const noneItemClass = !hasEffect
        ? "effect-item active" : "effect-item";
    const noneItem = `<button class="${noneItemClass}"
                              data-action="show"
                              data-effect="None">
                        <span class="effect-swatch none"></span>
                        <span>None</span>
                      </button>`;
    const showItems = SHOWS.map((sh) => {
      const grad = showGradient(sh);
      const itemClass = activeEffect === sh.effect
          ? "effect-item active" : "effect-item";
      return `<button class="${itemClass}"
                      data-action="show"
                      data-effect="${sh.effect}">
                <span class="effect-swatch"
                      style="background:${grad};"></span>
                <span>${sh.name}</span>
              </button>`;
    }).join("");
    const effectItems = noneItem + showItems;

    return `
      <div class="card">
        ${errorBanner}

        <button class="${tileClass}" data-action="toggle"
                aria-label="${stateText}">
          <div class="${iconClass}" style="${iconStyle}">
            <ha-icon icon="${isOn ? "mdi:lightbulb" : "mdi:lightbulb-off"}"></ha-icon>
          </div>
          <div class="tile-text">
            <div class="tile-name">Pool Light</div>
            <div class="tile-state">${stateText}</div>
          </div>
          <div class="toggle-indicator"></div>
        </button>

        <div class="section-label">Color</div>
        <div class="picker-row">
          <div class="wheel-wrap" data-wheel>
            <img class="wheel"
                 src="${WHEEL_IMAGE_CACHE}"
                 draggable="false"
                 alt="Color wheel" />
            <div class="wheel-cursor ${cursorActive}"
                 style="${cursorStyle}"></div>
          </div>
          <div class="brightness-wrap"
               style="${trackTintStyle}"
               aria-label="Brightness">
            <div class="brightness-slider" data-brightness>
              <div class="brightness-bg"></div>
              <div class="brightness-bar"></div>
            </div>
            <div class="brightness-tooltip">${brightnessPct}%</div>
          </div>
        </div>

        <div class="swatches">
          ${solidSwatches}
          ${returnSwatch}
          ${presetSwatches}
        </div>
        ${saveBtn}

        <div class="effect-section">
          <button class="${triggerClass}"
                  data-action="toggle-effects">
            <ha-icon class="effect-icon" icon="mdi:creation"></ha-icon>
            <span>${triggerLabel}</span>
            <span class="chevron">▼</span>
          </button>
          <div class="${listClass}">
            ${effectItems}
          </div>
        </div>

        <button class="lock-btn" data-action="lock">
          <ha-icon icon="mdi:lock"></ha-icon>
          <span>Lock current color</span>
        </button>
      </div>
      ${this._buildEditModal(this._editDraft)}
    `;
  }

  // Edit-preset modal — opened automatically after a save, and
  // by long-press / right-click on a user preset swatch. Lets
  // the user rename, tweak the timing in 100 ms steps, test-fire,
  // delete, or cancel.
  _buildEditModal(draft) {
    if (!draft) return "";
    const showName = this._showNameForByte(draft.start_byte);
    return `
      <div class="modal-backdrop" data-modal-backdrop>
        <div class="edit-modal" data-modal>
          <div class="modal-header">
            <span>Edit preset</span>
            <button class="modal-close"
                    data-action="edit-preset-cancel"
                    aria-label="Cancel">
              <ha-icon icon="mdi:close"></ha-icon>
            </button>
          </div>

          <div class="modal-body">
            <div class="modal-row">
              <label class="modal-swatch-label"
                     title="Click to refine the swatch color">
                <div class="modal-swatch"
                     style="background:${draft.hex};">
                </div>
                <input type="color" name="hex"
                       value="${draft.hex}" />
              </label>
              <div class="modal-meta">
                <div class="modal-hex">${draft.hex.toUpperCase()}</div>
                <div class="modal-show">Show: ${showName}</div>
                <div class="modal-hint-small">
                  Tap the swatch to refine the preview color.
                  The recipe (show + timing) doesn't change.
                </div>
              </div>
            </div>

            <label class="modal-label">
              Name
              <input type="text" name="name" maxlength="31"
                     value="${draft.name.replace(/"/g, "&quot;")}" />
            </label>

            <label class="modal-label">
              Slug
              <input type="text" name="slug" maxlength="15"
                     spellcheck="false" autocapitalize="none"
                     value="${draft.slug}" />
              <span class="modal-hint">
                Used by HA automations:
                <code>color_preset_recall(slug: ${draft.slug})</code>.
                Lowercase a-z, 0-9, underscore or hyphen.
              </span>
            </label>

            <label class="modal-label">
              <span class="modal-label-row">
                <span>Time offset</span>
                <button class="modal-format-toggle"
                        data-action="edit-preset-toggle-format"
                        title="Toggle between milliseconds and seconds">
                  ${this._timeFormat}
                </button>
              </span>
              <div class="modal-row tight modal-nudges">
                <button data-action="edit-preset-nudge"
                        data-delta-ms="-1000">−1s</button>
                <button data-action="edit-preset-nudge"
                        data-delta-ms="-100">−100</button>
                <button data-action="edit-preset-nudge"
                        data-delta-ms="-10">−10</button>
                <input type="number" name="wait_ms"
                       min="0"
                       step="${this._timeFormat === 's' ? '0.001' : '100'}"
                       value="${this._formatWaitMs(draft.wait_ms)}" />
                <button data-action="edit-preset-nudge"
                        data-delta-ms="10">+10</button>
                <button data-action="edit-preset-nudge"
                        data-delta-ms="100">+100</button>
                <button data-action="edit-preset-nudge"
                        data-delta-ms="1000">+1s</button>
              </div>
            </label>

            <button class="modal-test"
                    data-action="edit-preset-test">
              <ha-icon icon="mdi:flask"></ha-icon>
              <span>Test fire</span>
            </button>
          </div>

          <div class="modal-footer">
            <button class="modal-delete"
                    data-action="edit-preset-delete">
              <ha-icon icon="mdi:trash-can-outline"></ha-icon>
              <span>Delete</span>
            </button>
            <span class="modal-spacer"></span>
            <button class="modal-cancel"
                    data-action="edit-preset-cancel">Cancel</button>
            <button class="modal-save"
                    data-action="edit-preset-save">Save</button>
          </div>
        </div>
      </div>`;
  }

  // Schedule a test-fire of the current edit-modal draft's
  // recipe ~600 ms after the last interaction. Lets the user
  // tap a series of nudge buttons (or type into the wait_ms
  // input) and have the fixture chase only once they stop.
  // Skips firing for solid-byte recipes (wait_ms === 0) — the
  // bridge interprets those as instant solids, no scrub needed.
  _scheduleTestFire() {
    if (this._pendingTestFireTimer) {
      clearTimeout(this._pendingTestFireTimer);
    }
    this._pendingTestFireTimer = setTimeout(() => {
      this._pendingTestFireTimer = null;
      const d = this._editDraft;
      if (!d || !this._hass) return;
      if ((d.wait_ms | 0) === 0) return;
      this._callService(this._config.scrub_service, {
        start_byte: d.start_byte | 0,
        wait_ms: d.wait_ms | 0,
      }).catch((err) =>
          console.warn("[colorsplash-xg-card] auto test-fire "
              + "skipped:", err));
    }, TEST_FIRE_DEBOUNCE_MS);
  }

  // Format wait_ms for the input field per current _timeFormat.
  _formatWaitMs(ms) {
    if (this._timeFormat === "s") {
      return (ms / 1000).toFixed(3);
    }
    return String(ms | 0);
  }

  // Inverse of _formatWaitMs: parse the input field's raw value
  // back to integer milliseconds, clamping invalid input to 0.
  _parseWaitInput(raw) {
    if (this._timeFormat === "s") {
      const v = parseFloat(raw);
      if (!Number.isFinite(v)) return 0;
      return Math.max(0, Math.round(v * 1000));
    }
    const v = parseInt(raw, 10);
    if (!Number.isFinite(v)) return 0;
    return Math.max(0, v);
  }

  _showNameForByte(byte) {
    const known = {
      0x01: "Peruvian Paradise",
      0x02: "Super Nova",
      0x03: "Northern Lights",
      0x04: "Tidal Wave",
      0x05: "Patriot Dream",
      0x06: "Desert Skies",
      0x07: "Nova",
      0x08: "Parisian Blue (solid)",
      0x09: "New Zealand Green (solid)",
      0x0a: "Brazilian Red (solid)",
      0x0b: "Arctic White (solid)",
      0x0c: "Miami Pink (solid)",
    };
    return known[byte] || `byte 0x${byte.toString(16)}`;
  }

  // ---- event handling ----

  async _onClick(e) {
    const t = e.target.closest("[data-action]");
    console.info(
        `[colorsplash-xg-card v${VERSION}] _onClick`,
        {target: e.target, action: t && t.dataset.action,
         dataset: t && {...t.dataset}});
    if (!t) return;
    const action = t.dataset.action;
    const cfg = this._config;
    const hass = this._hass;
    if (!hass) {
      console.warn("[colorsplash-xg-card] hass not yet attached");
      return;
    }

    // Any discrete action that changes fixture state invalidates
    // an in-flight debounced wheel/slider commit. save-preset
    // doesn't change state — let the pending commit fire normally
    // so the saved recipe reflects what the user just dragged to.
    if (action !== "toggle-effects" && action !== "save-preset") {
      this._cancelPendingSend();
    }

    switch (action) {
      case "toggle":
        await hass.callService(
            "light", "toggle", {entity_id: cfg.light_entity});
        break;

      case "solid": {
        // Route through light.turn_on(rgb_color) so HA records
        // the color on the entity (drives the wheel cursor +
        // tile state). The firmware's pick_color resolves the
        // exact preset RGB to the same solid byte that
        // button.press would have fired, thanks to the
        // solid_preference bias.
        const solid = SOLIDS.find((s) => s.btn === t.dataset.button);
        if (!solid) {
          console.warn("[colorsplash-xg-card] unknown solid", t.dataset.button);
          break;
        }
        const [r, g, b] = hexToRgb(solid.hex);
        await hass.callService("light", "turn_on", {
          entity_id: cfg.light_entity,
          rgb_color: [r, g, b],
          effect: "None",
        });
        break;
      }

      case "return":
        // Bridge handles state via last_send_was_return short-circuit.
        await hass.callService("button", "press",
            {entity_id: cfg.return_entity});
        await hass.callService("light", "turn_on",
            {entity_id: cfg.light_entity, effect: "None"});
        break;

      case "show":
        await hass.callService("light", "turn_on",
            {entity_id: cfg.light_entity, effect: t.dataset.effect});
        // Close the dropdown after picking, mirroring native HA UX.
        this._effectsOpen = false;
        this._lastRenderedKey = "";
        this._render();
        break;

      case "toggle-effects":
        this._effectsOpen = !this._effectsOpen;
        this._lastRenderedKey = "";
        this._render();
        break;

      case "lock":
        await hass.callService("button", "press",
            {entity_id: cfg.lock_entity});
        break;

      case "preset": {
        const idx = parseInt(t.dataset.presetIndex, 10);
        const p = this._allPresets()[idx];
        console.info(
            `[colorsplash-xg-card v${VERSION}] preset replay`,
            {idx, preset: p});
        if (!p) {
          console.warn("preset index out of range", idx);
          break;
        }
        // Do NOT follow the recall with light.turn_on(effect:None).
        // ESPHome's light component re-runs write_state on every
        // turn_on call and will pick_color() against the cached
        // rgb_color from the previous user action — which dispatches
        // a fresh byte and stomps the preset's Nova/Tidal/etc.
        // start that's already in flight. The bridge handles the
        // full sequence (start_byte → set_timeout(wait_ms) →
        // Lock byte) inside color_preset_recall; the card has
        // nothing to add.
        try {
          if (p._user && p.slug) {
            await this._callService(cfg.preset_recall_service,
                                    {slug: p.slug});
          } else {
            // Static YAML preset → fall back to pool_scrub recipe
            await this._callService(cfg.scrub_service, {
              start_byte: p.start_byte | 0,
              wait_ms: p.wait_ms | 0,
            });
          }
        } catch (err) {
          console.error("preset replay failed:", err);
        }
        break;
      }

      case "save-preset": {
        const recipe = this._readCurrentRecipe();
        if (!recipe) {
          console.warn("no recipe available — picker hasn't run yet");
          break;
        }
        const lightState = hass.states[cfg.light_entity];
        const rgb = lightState && lightState.attributes
            && lightState.attributes.rgb_color;
        if (!Array.isArray(rgb)) {
          console.warn("no rgb_color on light entity");
          break;
        }
        const [r, g, b] = rgb;
        const suggested = this._suggestPresetName(r, g, b);
        const slug = this._slugify(suggested);
        const hex = "#" + rgb.map((c) =>
            c.toString(16).padStart(2, "0")).join("");
        try {
          await this._callService(cfg.preset_save_service, {
            slug, name: suggested,
            red: r, green: g, blue: b,
            start_byte: recipe.start_byte,
            wait_ms: recipe.wait_ms,
          });
        } catch (err) {
          console.error("color_preset_save failed:", err);
          break;
        }
        // Open the edit modal pointing at the just-saved preset
        // so the user can rename, retag the slug, or tweak the
        // timing immediately. original_slug captures what's
        // currently in NVS — if the user edits the slug, save
        // will write the new one and delete the old.
        this._editingSlug = slug;
        this._editDraft = {
          slug,
          original_slug: slug,
          name: suggested,
          hex,
          start_byte: recipe.start_byte,
          wait_ms: recipe.wait_ms,
        };
        this._lastRenderedKey = "";
        this._render();
        break;
      }

      case "edit-preset-cancel": {
        if (this._pendingTestFireTimer) {
          clearTimeout(this._pendingTestFireTimer);
          this._pendingTestFireTimer = null;
        }
        this._editingSlug = null;
        this._editDraft = null;
        this._lastRenderedKey = "";
        this._render();
        break;
      }

      case "edit-preset-save": {
        if (!this._editDraft) break;
        const d = this._editDraft;
        const slugInput = this.shadowRoot.querySelector(
            ".edit-modal input[name=slug]");
        const nameInput = this.shadowRoot.querySelector(
            ".edit-modal input[name=name]");
        let newSlug = slugInput
            ? this._sanitizeSlug(slugInput.value)
            : d.slug;
        if (!newSlug) newSlug = d.original_slug || d.slug;
        const newName = nameInput
            ? String(nameInput.value).slice(0, 31)
            : d.name;
        // wait_ms is kept in sync via the input event listener
        // (which honors _timeFormat), so use the draft directly.
        const newWaitMs = Math.max(0, d.wait_ms | 0);
        const [er, eg, eb] = hexToRgb(d.hex);
        // Save (or overwrite) under the current slug.
        try {
          await this._callService(cfg.preset_save_service, {
            slug: newSlug,
            name: newName,
            red: er, green: eg, blue: eb,
            start_byte: d.start_byte,
            wait_ms: newWaitMs,
          });
        } catch (err) {
          console.error("color_preset_save (edit) failed:", err);
          break;
        }
        // If the slug was renamed, drop the old slot. Saving
        // first means we never lose the preset if delete fails.
        if (d.original_slug && d.original_slug !== newSlug) {
          try {
            await this._callService(cfg.preset_delete_service,
                                    {slug: d.original_slug});
          } catch (err) {
            console.warn("rename — could not delete old slug "
                         + d.original_slug, err);
          }
        }
        this._editingSlug = null;
        this._editDraft = null;
        this._lastRenderedKey = "";
        this._render();
        break;
      }

      case "edit-preset-delete": {
        if (!this._editDraft) break;
        if (!window.confirm(
            `Delete preset "${this._editDraft.name}"?`)) break;
        try {
          await this._callService(cfg.preset_delete_service, {
            slug: this._editDraft.slug,
          });
        } catch (err) {
          console.error("color_preset_delete failed:", err);
          break;
        }
        this._editingSlug = null;
        this._editDraft = null;
        this._lastRenderedKey = "";
        this._render();
        break;
      }

      case "edit-preset-test": {
        if (!this._editDraft) break;
        // Fire the (possibly tweaked) recipe via pool_scrub
        // without persisting the changes. Cancel any pending
        // auto-test so this manual fire doesn't get followed by
        // a duplicate.
        if (this._pendingTestFireTimer) {
          clearTimeout(this._pendingTestFireTimer);
          this._pendingTestFireTimer = null;
        }
        const d = this._editDraft;
        try {
          await this._callService(cfg.scrub_service, {
            start_byte: d.start_byte,
            wait_ms: d.wait_ms | 0,
          });
        } catch (err) {
          console.error("test-fire pool_scrub failed:", err);
        }
        break;
      }

      case "edit-preset-nudge": {
        if (!this._editDraft) break;
        const delta = parseInt(t.dataset.deltaMs, 10) | 0;
        const next = Math.max(0,
            (this._editDraft.wait_ms | 0) + delta);
        this._editDraft.wait_ms = next;
        const waitInput = this.shadowRoot.querySelector(
            ".edit-modal input[name=wait_ms]");
        if (waitInput) waitInput.value = this._formatWaitMs(next);
        this._scheduleTestFire();
        break;
      }

      case "edit-preset-toggle-format": {
        if (!this._editDraft) break;
        this._timeFormat = this._timeFormat === "ms" ? "s" : "ms";
        const waitInput = this.shadowRoot.querySelector(
            ".edit-modal input[name=wait_ms]");
        if (waitInput) {
          waitInput.value =
              this._formatWaitMs(this._editDraft.wait_ms);
          waitInput.step = this._timeFormat === "s" ? "0.001" : "100";
        }
        const toggleBtn = this.shadowRoot.querySelector(
            "[data-action=edit-preset-toggle-format]");
        if (toggleBtn) toggleBtn.textContent = this._timeFormat;
        break;
      }
    }
  }

  // ---- color wheel + brightness slider pointer handling ----

  _wireWheel() {
    const wheel = this.shadowRoot.querySelector("[data-wheel]");
    if (wheel) {
      wheel.addEventListener("pointerdown", (e) => this._onWheelDown(e));
      wheel.addEventListener("pointermove", (e) => this._onWheelMove(e));
      wheel.addEventListener("pointerup",   (e) => this._onWheelUp(e));
      wheel.addEventListener("pointercancel", (e) => this._onWheelUp(e));
    }
    const bright = this.shadowRoot.querySelector("[data-brightness]");
    if (bright) {
      bright.addEventListener("pointerdown", (e) => this._onBrightDown(e));
      bright.addEventListener("pointermove", (e) => this._onBrightMove(e));
      bright.addEventListener("pointerup",   (e) => this._onBrightUp(e));
      bright.addEventListener("pointercancel", (e) => this._onBrightUp(e));
    }

    // Long-press on a user preset swatch → opens the edit modal.
    // Short taps still bubble normally to _onClick → preset case.
    // We track longPressed in a closure local to the swatch and
    // ATTACH A CLICK LISTENER ON THE SWATCH that swallows the
    // trailing click only when longPressed is set. No class-level
    // suppression flag, so there's no risk of leaking suppression
    // across unrelated interactions.
    const userSwatches = this.shadowRoot.querySelectorAll(
        ".swatch.preset.user");
    userSwatches.forEach((sw) => {
      let pressTimer = null;
      let longPressed = false;
      const cancel = () => {
        if (pressTimer) clearTimeout(pressTimer);
        pressTimer = null;
      };
      sw.addEventListener("pointerdown", () => {
        longPressed = false;
        pressTimer = setTimeout(() => {
          pressTimer = null;
          longPressed = true;
          this._openEditModalForSwatch(sw);
        }, 600);
      });
      sw.addEventListener("pointerup",     cancel);
      sw.addEventListener("pointermove",   cancel);
      sw.addEventListener("pointerleave",  cancel);
      sw.addEventListener("pointercancel", cancel);
      sw.addEventListener("click", (e) => {
        if (longPressed) {
          // Eat the trailing click after a long-press so it
          // doesn't bubble to _onClick and replay the preset.
          e.preventDefault();
          e.stopPropagation();
          longPressed = false;
        }
      });
      sw.addEventListener("contextmenu", (e) => {
        // Right-click on desktop also opens the edit modal.
        e.preventDefault();
        longPressed = true;
        this._openEditModalForSwatch(sw);
      });
    });

    // Edit-modal wiring: backdrop-click closes; input changes
    // sync into _editDraft so re-renders preserve typing.
    const backdrop = this.shadowRoot.querySelector(
        "[data-modal-backdrop]");
    if (backdrop) {
      backdrop.addEventListener("click", (e) => {
        if (e.target === backdrop) {
          this._editingSlug = null;
          this._editDraft = null;
          this._lastRenderedKey = "";
          this._render();
        }
      });
    }
    const nameInput = this.shadowRoot.querySelector(
        ".edit-modal input[name=name]");
    if (nameInput && this._editDraft) {
      nameInput.addEventListener("input", (e) => {
        if (this._editDraft) {
          this._editDraft.name = e.target.value;
        }
      });
    }
    const waitInput = this.shadowRoot.querySelector(
        ".edit-modal input[name=wait_ms]");
    if (waitInput && this._editDraft) {
      waitInput.addEventListener("input", (e) => {
        if (!this._editDraft) return;
        this._editDraft.wait_ms =
            this._parseWaitInput(e.target.value);
        this._scheduleTestFire();
      });
    }
    const hexInput = this.shadowRoot.querySelector(
        ".edit-modal input[name=hex]");
    if (hexInput && this._editDraft) {
      hexInput.addEventListener("input", (e) => {
        if (!this._editDraft) return;
        const v = e.target.value;
        this._editDraft.hex = v;
        // Live-update the swatch background and hex label without
        // a full re-render (which would close the OS picker).
        const sw = this.shadowRoot.querySelector(".modal-swatch");
        if (sw) sw.style.background = v;
        const lbl = this.shadowRoot.querySelector(".modal-hex");
        if (lbl) lbl.textContent = v.toUpperCase();
      });
    }
    const slugInput = this.shadowRoot.querySelector(
        ".edit-modal input[name=slug]");
    if (slugInput && this._editDraft) {
      slugInput.addEventListener("input", (e) => {
        // Live-sanitize: lowercase + [a-z0-9_-], <= 15 chars.
        // Preserve caret position when stripping disallowed
        // characters so the user's typing experience stays
        // smooth even with arrow / mid-string edits.
        const before = e.target.value;
        const caret = e.target.selectionStart;
        const after = this._sanitizeSlug(before);
        if (after !== before) {
          e.target.value = after;
          const newCaret = Math.min(caret || 0, after.length);
          try {
            e.target.setSelectionRange(newCaret, newCaret);
          } catch (_) { /* not all input types support it */ }
        }
        if (this._editDraft) {
          this._editDraft.slug = after;
        }
      });
    }
  }

  _openEditModalForSwatch(sw) {
    const idx = parseInt(sw.dataset.presetIndex, 10);
    const p = this._allPresets()[idx];
    if (!p || !p._user || !p.slug) return;
    this._editingSlug = p.slug;
    this._editDraft = {
      slug:           p.slug,
      original_slug:  p.slug,    // for rename-then-delete-old logic
      name:           p.name || "",
      hex:            p.hex || "#444",
      start_byte:     p.start_byte | 0,
      wait_ms:        p.wait_ms | 0,
    };
    this._lastRenderedKey = "";
    this._render();
  }

  // Sanitize a slug to the allowed character set: lowercase
  // alphanumeric, underscore, hyphen. Used both by the live
  // input handler and by the auto-suggest path.
  _sanitizeSlug(raw) {
    return String(raw || "")
        .toLowerCase()
        .replace(/[^a-z0-9_-]/g, "")
        .slice(0, 15);
  }

  // Returns the current V (0..1) for any new outgoing color.
  // Priority: most recent slider drag this session → state's
  // rgb_color → 1.
  _currentBrightness() {
    if (this._lastV != null) return this._lastV;
    const lightState = this._hass &&
        this._hass.states[this._config.light_entity];
    const rgb = lightState && lightState.attributes &&
        Array.isArray(lightState.attributes.rgb_color)
            ? lightState.attributes.rgb_color : null;
    if (!rgb) return 1;
    const [, , v] = rgbToHsv(rgb[0], rgb[1], rgb[2]);
    return v;
  }

  // Schedule a debounced light.turn_on(rgb_color) call. Each
  // wheel/slider interaction restarts the timer so the user
  // can dial in both controls before the LUT match fires.
  _scheduleSend(rgb) {
    this._pendingRgb = rgb;
    if (this._pendingTimer) clearTimeout(this._pendingTimer);
    this._pendingTimer = setTimeout(() => {
      this._pendingTimer = null;
      const rgbToSend = this._pendingRgb;
      this._pendingRgb = null;
      // After commit, drop the cached H/S/V so subsequent
      // interactions read fresh values from the new state.
      this._lastHs = null;
      this._lastV = null;
      if (!rgbToSend || !this._hass) return;
      this._hass.callService("light", "turn_on", {
        entity_id: this._config.light_entity,
        rgb_color: rgbToSend,
      });
    }, SEND_DEBOUNCE);
  }

  // Discrete actions (solid / show / Return / toggle / lock /
  // preset) bypass the debounce and need to cancel any pending
  // wheel/slider commit so it doesn't stomp the new state.
  _cancelPendingSend() {
    if (this._pendingTimer) clearTimeout(this._pendingTimer);
    this._pendingTimer = null;
    this._pendingRgb = null;
    this._lastHs = null;
    this._lastV = null;
  }

  _onWheelDown(e) {
    e.preventDefault();
    this._wheelDragging = true;
    e.target.setPointerCapture && e.target.setPointerCapture(e.pointerId);
    this._emitWheelColor(e, true);
  }

  _onWheelMove(e) {
    if (!this._wheelDragging) return;
    e.preventDefault();
    this._emitWheelColor(e, false);
  }

  _onWheelUp(e) {
    if (!this._wheelDragging) return;
    this._wheelDragging = false;
    // Final commit on release, ignoring throttle so the last
    // position always lands.
    this._emitWheelColor(e, true);
  }

  _emitWheelColor(e, force) {
    const wrap = this.shadowRoot.querySelector("[data-wheel]");
    if (!wrap) return;
    const rect = wrap.getBoundingClientRect();
    const r = WHEEL_SIZE / 2;
    let x = e.clientX - rect.left - r;
    let y = e.clientY - rect.top - r;
    let dist = Math.sqrt(x * x + y * y);
    if (dist > r) {
      // Snap to the rim — picker stays inside the disc.
      x = (x / dist) * r;
      y = (y / dist) * r;
      dist = r;
    }
    // Match buildWheelDataUrl orientation: 0° at +x (3 o'clock),
    // positive angles counter-clockwise. CSS y points down so
    // negate it.
    const angleRad = Math.atan2(-y, x);
    const h = ((angleRad * 180 / Math.PI) + 360) % 360;
    const s = Math.min(1, dist / r);
    this._lastHs = [h, s];
    // Apply the current slider brightness when sending — the
    // wheel itself is rendered at V=1 (so cursor placement stays
    // visible), but the actual color carried to the fixture is
    // dimmed per the slider.
    const v = Math.max(BRIGHTNESS_MIN, this._currentBrightness());
    const [R, G, B] = hsvToRgb(h, s, v);
    // Cursor dot + slider tint use the V=1 chroma so the wheel
    // selection stays visible regardless of the slider value.
    const [rW, gW, bW] = hsvToRgb(h, s, 1);

    // Live-update the cursor dot without a full re-render.
    const cursor = this.shadowRoot.querySelector(".wheel-cursor");
    if (cursor) {
      cursor.classList.add("active");
      cursor.style.left = `${x + r}px`;
      cursor.style.top = `${y + r}px`;
      cursor.style.background = `rgb(${rW},${gW},${bW})`;
    }
    // Live-update the slider tint to follow the new hue. Run the
    // same contrast adjustment HA's brightness slider uses.
    const sliderWrap = this.shadowRoot.querySelector(".brightness-wrap");
    if (sliderWrap) {
      const [cR, cG, cB] = adjustSliderColor(rW, gW, bW);
      sliderWrap.style.setProperty("--cs-color", `rgb(${cR},${cG},${cB})`);
    }

    this._scheduleSend([R, G, B]);
  }

  _onBrightDown(e) {
    e.preventDefault();
    this._brightnessDragging = true;
    e.target.setPointerCapture && e.target.setPointerCapture(e.pointerId);
    const bar = this.shadowRoot.querySelector(".brightness-bar");
    if (bar) bar.classList.add("dragging");
    const tip = this.shadowRoot.querySelector(".brightness-tooltip");
    if (tip) tip.classList.add("visible");
    this._emitBrightness(e, true);
  }

  _onBrightMove(e) {
    if (!this._brightnessDragging) return;
    e.preventDefault();
    this._emitBrightness(e, false);
  }

  _onBrightUp(e) {
    if (!this._brightnessDragging) return;
    this._brightnessDragging = false;
    const bar = this.shadowRoot.querySelector(".brightness-bar");
    if (bar) bar.classList.remove("dragging");
    const tip = this.shadowRoot.querySelector(".brightness-tooltip");
    if (tip) tip.classList.remove("visible");
    this._emitBrightness(e, true);
  }

  _emitBrightness(e, force) {
    const slider = this.shadowRoot.querySelector("[data-brightness]");
    if (!slider) return;
    const rect = slider.getBoundingClientRect();
    const yClamped = Math.max(0,
        Math.min(rect.height, e.clientY - rect.top));
    const v = Math.max(BRIGHTNESS_MIN, 1 - (yClamped / rect.height));
    this._lastV = v;

    // Live-update --cs-value on the wrap so both the bar
    // transform and the tooltip's vertical position track.
    const wrap = this.shadowRoot.querySelector(".brightness-wrap");
    if (wrap) wrap.style.setProperty("--cs-value", v.toFixed(3));
    // Live-update tooltip text.
    const tip = this.shadowRoot.querySelector(".brightness-tooltip");
    if (tip) tip.textContent = `${Math.round(v * 100)}%`;

    // Reuse the most recent hue/sat from the wheel; if the user
    // hasn't picked one this session, derive from rgb_color.
    let h, s;
    if (this._lastHs) {
      [h, s] = this._lastHs;
    } else {
      const hass = this._hass;
      const lightState = hass && hass.states[this._config.light_entity];
      const rgb = lightState && lightState.attributes &&
          Array.isArray(lightState.attributes.rgb_color)
              ? lightState.attributes.rgb_color : [255, 255, 255];
      [h, s] = rgbToHsv(rgb[0], rgb[1], rgb[2]);
    }
    const [R, G, B] = hsvToRgb(h, s, v);
    this._scheduleSend([R, G, B]);
  }
}


customElements.define("colorsplash-xg-card", ColorSplashCard);
console.info(`%c colorsplash-xg-card %c v${VERSION} `,
  "color: white; background: #03a9f4; font-weight: 700;",
  "color: #03a9f4; background: white; font-weight: 700;");

window.customCards = window.customCards || [];
window.customCards.push({
  type: "colorsplash-xg-card",
  name: "ColorSplash XG",
  description:
      "Pool light controls — big toggle tile, RGB color wheel, "
      + "solid swatches, custom show dropdown, Lock + Return.",
  preview: false,
});
