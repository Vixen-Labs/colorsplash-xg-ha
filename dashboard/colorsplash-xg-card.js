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

const VERSION = "0.9.1";

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
  recipe_entity: null,         // text_sensor with "0xNN,wait_ms"
  scrub_service: "esphome.colorsplash_xg_bridge_pool_scrub",
  presets: [],
};

// localStorage key for user-saved presets. Stored as a JSON array
// of {name, hex, start_byte, wait_ms}. YAML-defined presets and
// localStorage presets are merged in the picker — YAML is
// version-controlled / shareable, localStorage is per-browser
// persistence for ad-hoc captures.
const PRESET_STORAGE_KEY = "colorsplash-xg-card.presets";

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
    this._config = merged;
    this._userPresets = this._loadUserPresets();
  }

  _loadUserPresets() {
    try {
      const raw = window.localStorage.getItem(PRESET_STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      console.warn("[colorsplash-xg-card] failed to load user presets", e);
      return [];
    }
  }

  _saveUserPresets() {
    try {
      window.localStorage.setItem(
          PRESET_STORAGE_KEY,
          JSON.stringify(this._userPresets || []));
    } catch (e) {
      console.warn("[colorsplash-xg-card] failed to save user presets", e);
    }
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

  // Returns the merged YAML + localStorage preset list for
  // rendering. localStorage presets carry a `_user: true` flag so
  // delete-affordance shows only on those.
  _allPresets() {
    const cfg = this._config;
    const yaml = (Array.isArray(cfg.presets) ? cfg.presets : [])
        .map((p) => ({...p, _user: false}));
    const user = (this._userPresets || [])
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

    const key = [
      lightFound, isOn, activeEffect || "",
      rgbColor ? rgbColor.join(",") : "",
      this._effectsOpen,
      JSON.stringify(cfg.presets || []),
      JSON.stringify(this._userPresets || []),
      this._readCurrentRecipe() ? "have-recipe" : "no-recipe",
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
    //   - the current recipe doesn't already match a saved preset
    //     (avoids double-saving the same recipe under a different
    //     name; user wants the button to disappear post-save)
    const recipe = this._readCurrentRecipe();
    const haveRecipe = !!recipe;
    const alreadySaved = recipe && this._allPresets().some((p) =>
        p.start_byte === recipe.start_byte
        && p.wait_ms === recipe.wait_ms);
    const canSave = isOn && haveRecipe && rgbColor
        && !hasEffect && !alreadySaved;
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
    `;
  }

  // ---- event handling ----

  async _onClick(e) {
    if (this._suppressNextClick) {
      this._suppressNextClick = false;
      return;
    }
    const t = e.target.closest("[data-action]");
    if (!t) return;
    const action = t.dataset.action;
    const cfg = this._config;
    const hass = this._hass;
    if (!hass) {
      console.warn("[colorsplash-xg-card] hass not yet attached");
      return;
    }
    console.info(
        `[colorsplash-xg-card v${VERSION}] click action=${action}`,
        {dataset: {...t.dataset}, light_entity: cfg.light_entity});

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
            {idx, preset: p, scrub_service: cfg.scrub_service});
        if (!p) {
          console.warn("preset index out of range", idx);
          break;
        }
        // ESPHome service names contain dots in the form
        // "esphome.<device_slug>_<service_name>". The first dot
        // separates domain from service. Split with limit 2 picks
        // ALL of the suffix into the second slot, even if it
        // contains underscores.
        const dotIdx = cfg.scrub_service.indexOf(".");
        if (dotIdx < 0) {
          console.warn("scrub_service missing '.': "
                       + cfg.scrub_service);
          break;
        }
        const domain = cfg.scrub_service.slice(0, dotIdx);
        const name = cfg.scrub_service.slice(dotIdx + 1);
        const args = {
          start_byte: p.start_byte | 0,
          wait_ms: p.wait_ms | 0,
        };
        console.info("calling service", {domain, name, args});
        try {
          await hass.callService(domain, name, args);
        } catch (err) {
          console.error("scrub service call failed:", err);
          break;
        }
        try {
          await hass.callService("light", "turn_on",
              {entity_id: cfg.light_entity, effect: "None"});
        } catch (err) {
          console.error("light.turn_on(effect:None) failed:", err);
        }
        break;
      }

      case "save-preset": {
        const recipe = this._readCurrentRecipe();
        if (!recipe) {
          console.warn("no recipe available — has the user picked a color?");
          break;
        }
        const lightState = hass.states[cfg.light_entity];
        const rgb = lightState && lightState.attributes &&
            lightState.attributes.rgb_color;
        if (!Array.isArray(rgb)) {
          console.warn("no rgb_color on light entity");
          break;
        }
        const hex = "#" + rgb.map((c) =>
            c.toString(16).padStart(2, "0")).join("");
        // Use window.prompt for v0.9.0 — minimal but functional.
        // A nicer modal can come later.
        const name = window.prompt(
            "Name this preset:",
            `My Color ${(this._userPresets || []).length + 1}`);
        if (!name) break;
        this._userPresets = [
          ...(this._userPresets || []),
          {name, hex, start_byte: recipe.start_byte,
           wait_ms: recipe.wait_ms},
        ];
        this._saveUserPresets();
        this._lastRenderedKey = "";
        this._render();
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

    // Long-press on a user preset swatch → confirm + delete.
    // Short taps fall through to the normal preset replay path
    // (the click event bubbles up to shadowRoot's _onClick
    // delegate). When a long-press fires the delete confirm, we
    // set _suppressNextClick so the trailing click — which would
    // otherwise replay the preset on its way out — is dropped.
    const userSwatches = this.shadowRoot.querySelectorAll(
        ".swatch.preset.user");
    userSwatches.forEach((sw) => {
      let pressTimer = null;
      const cancel = () => {
        if (pressTimer) clearTimeout(pressTimer);
        pressTimer = null;
      };
      sw.addEventListener("pointerdown", () => {
        pressTimer = setTimeout(() => {
          pressTimer = null;
          this._suppressNextClick = true;
          this._maybeDeletePreset(sw);
        }, 600);
      });
      sw.addEventListener("pointerup",     cancel);
      sw.addEventListener("pointermove",   cancel);
      sw.addEventListener("pointerleave",  cancel);
      sw.addEventListener("pointercancel", cancel);
      sw.addEventListener("contextmenu", (e) => {
        // Right-click on desktop also opens the delete prompt.
        e.preventDefault();
        this._suppressNextClick = true;
        this._maybeDeletePreset(sw);
      });
    });
  }

  _maybeDeletePreset(sw) {
    const idx = parseInt(sw.dataset.presetIndex, 10);
    const all = this._allPresets();
    const p = all[idx];
    if (!p || !p._user) return;
    // user-preset index in this._userPresets:
    const yamlCount = (Array.isArray(this._config.presets)
                       ? this._config.presets.length : 0);
    const userIdx = idx - yamlCount;
    if (userIdx < 0 || userIdx >= (this._userPresets || []).length) return;
    if (!window.confirm(`Delete preset "${p.name}"?`)) return;
    this._userPresets.splice(userIdx, 1);
    this._saveUserPresets();
    this._lastRenderedKey = "";
    this._render();
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
