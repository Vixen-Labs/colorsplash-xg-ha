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
 *   - HSV colour wheel (drag to pick → light.turn_on rgb_color)
 *   - Swatches row: 5 solids + Return badge + saved presets
 *   - Effect dropdown: collapsible list with circular show
 *     swatch (gradient or discrete-slice) per entry
 *   - Lock button at the bottom
 *
 * Mirrors HA's circular-swatch convention: 40 px discs, white /
 * light colours get a `--divider-color` border; dark colours
 * have a transparent border so the swatch reads cleanly on both
 * light and dark themes. Active selections get a primary-colour
 * outline.
 *
 * Resolves issue #41. See dashboard/README.md for install.
 */

const VERSION = "0.7.3";

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
// hard-edged colour slices instead of a smooth gradient (Nova
// and Super Nova jump between colours without blending).
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
    // Same colours as Nova but rendered twice so each slice is
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
  scrub_service: "esphome.colorsplash_xg_bridge_pool_scrub",
  presets: [],
};

const WHEEL_SIZE = 220;     // px — outer diameter of the HSV wheel
const WHEEL_THROTTLE = 90;  // ms between rgb_color writes during drag


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
function luminosity(hex) {
  const [r, g, b] = hexToRgb(hex);
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
}

// Build a CSS gradient string for a show preview swatch. Uses
// hard stops for `discrete` shows (Nova / Super Nova) so the
// colour bands have crisp edges.
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
    this._lastWheelEmit = 0;
    this._wheelCursor = null;  // {hue, sat} or null

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
    this._config = merged;
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
        transition: background-color 0.18s ease, color 0.18s ease;
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

      /* ─── Colour wheel ──────────────────────────────────────
         Pre-rendered HSV wheel; the cursor dot is positioned
         absolutely over it to indicate the current selection. */
      .wheel-wrap {
        position: relative;
        width: ${WHEEL_SIZE}px;
        height: ${WHEEL_SIZE}px;
        margin: 4px auto 8px;
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

      /* ─── Swatch grid ─────────────────────────────────────
         Mirrors HA's ha-favorite-color-button: 40 px discs,
         pill-shaped (i.e. circle when square). Light colours
         get a divider-coloured border so they show against
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
      }
      .swatch.return .badge {
        font-size: 1.1em;
        font-weight: 700;
        color: var(--primary-text-color, #fff);
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
        font-size: 1.2em;
        line-height: 1;
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
      .effect-item.active {
        background: var(--secondary-background-color, #2c2c2e);
        font-weight: 600;
      }
      .effect-item.active .effect-swatch {
        box-shadow: 0 0 0 2px var(--primary-color, #03a9f4);
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
      }
      .lock-btn:active {
        transform: scale(0.97);
      }
      .lock-btn::before {
        content: "🔒  ";
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

    // Lightbulb tint — fill the icon with the current displayed
    // colour. When a show effect is running, fall back to the
    // theme's active-icon colour because the colour is cycling.
    let iconStyle = "";
    if (isOn && !hasEffect && rgbColor) {
      const rgbCss = `rgb(${rgbColor[0]},${rgbColor[1]},${rgbColor[2]})`;
      const rgbBg = `rgba(${rgbColor[0]},${rgbColor[1]},${rgbColor[2]},0.22)`;
      iconStyle = `color:${rgbCss};background:${rgbBg};`;
    } else if (isOn && hasEffect) {
      iconStyle = "color:var(--state-icon-active-color,#f9a825);" +
                  "background:rgba(249,168,37,0.22);";
    }

    // Wheel cursor position. Reflects rgb_color whenever it's
    // available and no show is running. During a show, the
    // cursor hides because the colour is cycling and any cached
    // rgb_color is stale.
    let cursorStyle = "";
    let cursorActive = "";
    if (isOn && !hasEffect && rgbColor) {
      const [h, s] = rgbToHsv(rgbColor[0], rgbColor[1], rgbColor[2]);
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

    // Solid swatches — circular discs with HA-style border
    // handling for light colours.
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
              title="Return — replay last-locked colour"
              aria-label="Return to last-locked colour">
        <span class="badge">R</span>
      </button>`;

    // User presets — each has {name, hex, start_byte, wait_ms}.
    const presets = Array.isArray(cfg.presets) ? cfg.presets : [];
    const presetSwatches = presets.map((p, i) => {
      const isLight = luminosity(p.hex || "#444") > 0.8;
      const tip = `${p.name || ""} — start_byte=0x${(p.start_byte || 0).toString(16)} wait_ms=${p.wait_ms || 0}`;
      return `<button class="swatch preset ${isLight ? "light" : ""}"
                      data-action="preset"
                      data-preset-index="${i}"
                      title="${tip}"
                      aria-label="Preset ${p.name || i}"
                      style="background:${p.hex || "#444"};"></button>`;
    }).join("");

    // Effect dropdown — collapsible; entries show a circular
    // show swatch (gradient or discrete-slice) instead of a
    // bullet point.
    const triggerLabel = activeEffect && activeEffect !== "None"
        ? activeEffect : "Effect";
    const triggerClass = this._effectsOpen
        ? "effect-trigger open" : "effect-trigger";
    const listClass = this._effectsOpen
        ? "effect-list open" : "effect-list";
    const effectItems = SHOWS.map((sh) => {
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

    return `
      <div class="card">
        ${errorBanner}

        <button class="${tileClass}" data-action="toggle"
                aria-label="${stateText}">
          <div class="tile-icon" style="${iconStyle}">
            <ha-icon icon="${isOn ? "mdi:lightbulb" : "mdi:lightbulb-off"}"></ha-icon>
          </div>
          <div class="tile-text">
            <div class="tile-name">Pool Light</div>
            <div class="tile-state">${stateText}</div>
          </div>
          <div class="toggle-indicator"></div>
        </button>

        <div class="section-label">Colour</div>
        <div class="wheel-wrap" data-wheel>
          <img class="wheel"
               src="${WHEEL_IMAGE_CACHE}"
               draggable="false"
               alt="Colour wheel" />
          <div class="wheel-cursor ${cursorActive}"
               style="${cursorStyle}"></div>
        </div>

        <div class="swatches">
          ${solidSwatches}
          ${returnSwatch}
          ${presetSwatches}
        </div>

        <div class="effect-section">
          <button class="${triggerClass}"
                  data-action="toggle-effects">
            <span class="effect-icon">✨</span>
            <span>${triggerLabel}</span>
            <span class="chevron">▼</span>
          </button>
          <div class="${listClass}">
            ${effectItems}
          </div>
        </div>

        <button class="lock-btn" data-action="lock">
          Lock current colour
        </button>
      </div>
    `;
  }

  // ---- event handling ----

  async _onClick(e) {
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

    switch (action) {
      case "toggle":
        await hass.callService(
            "light", "toggle", {entity_id: cfg.light_entity});
        break;

      case "solid": {
        // Route through light.turn_on(rgb_color) so HA records
        // the colour on the entity (drives the wheel cursor +
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
        const p = (cfg.presets || [])[idx];
        if (!p) {
          console.warn("preset index out of range", idx);
          break;
        }
        const [domain, name] = cfg.scrub_service.split(".", 2);
        await hass.callService(domain, name, {
          start_byte: p.start_byte | 0,
          wait_ms: p.wait_ms | 0,
        });
        await hass.callService("light", "turn_on",
            {entity_id: cfg.light_entity, effect: "None"});
        break;
      }
    }
  }

  // ---- colour wheel pointer handling ----

  _wireWheel() {
    const wrap = this.shadowRoot.querySelector("[data-wheel]");
    if (!wrap) return;
    wrap.addEventListener("pointerdown", (e) => this._onWheelDown(e));
    wrap.addEventListener("pointermove", (e) => this._onWheelMove(e));
    wrap.addEventListener("pointerup",   (e) => this._onWheelUp(e));
    wrap.addEventListener("pointercancel", (e) => this._onWheelUp(e));
  }

  _onWheelDown(e) {
    e.preventDefault();
    this._wheelDragging = true;
    e.target.setPointerCapture && e.target.setPointerCapture(e.pointerId);
    this._emitWheelColour(e, true);
  }

  _onWheelMove(e) {
    if (!this._wheelDragging) return;
    e.preventDefault();
    this._emitWheelColour(e, false);
  }

  _onWheelUp(e) {
    if (!this._wheelDragging) return;
    this._wheelDragging = false;
    // Final commit on release, ignoring throttle so the last
    // position always lands.
    this._emitWheelColour(e, true);
  }

  _emitWheelColour(e, force) {
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
    const [R, G, B] = hsvToRgb(h, s, 1);

    // Live-update the cursor dot without a full re-render.
    const cursor = this.shadowRoot.querySelector(".wheel-cursor");
    if (cursor) {
      cursor.classList.add("active");
      cursor.style.left = `${x + r}px`;
      cursor.style.top = `${y + r}px`;
      cursor.style.background = `rgb(${R},${G},${B})`;
    }

    const now = Date.now();
    if (!force && now - this._lastWheelEmit < WHEEL_THROTTLE) return;
    this._lastWheelEmit = now;

    const cfg = this._config;
    const hass = this._hass;
    if (!hass) return;
    hass.callService("light", "turn_on", {
      entity_id: cfg.light_entity,
      rgb_color: [R, G, B],
    });
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
      "Pool light controls — big toggle tile, RGB colour wheel, "
      + "solid swatches, custom show dropdown, Lock + Return.",
  preview: false,
});
