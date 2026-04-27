/**
 * ColorSplash XG custom Lovelace card.
 *
 * Visual design follows HA's native more-info-light dialog
 * (favorite-color-button + state-control-light-color-picker
 * patterns from the home-assistant/frontend repo). Adapted to
 * our constrained palette + show-scrub picker:
 *
 *   - Header: title + slider toggle
 *   - State label: shows current colour / show / "Off"
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

const VERSION = "0.6.0";

// 5 documented solid presets.
const SOLIDS = [
  {name: "Parisian Blue",      btn: "pool_parisian_blue",      hex: "#0000FF"},
  {name: "Brazilian Red",      btn: "pool_brazilian_red",      hex: "#FF0000"},
  {name: "Arctic White",       btn: "pool_arctic_white",       hex: "#FFFFFF"},
  {name: "Miami Pink",         btn: "pool_miami_pink",         hex: "#FF00FF"},
  {name: "New Zealand Green",  btn: "pool_new_zealand_green",  hex: "#00FF00"},
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


// ─── Card class ─────────────────────────────────────────────────────

class ColorSplashCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: "open"});
    this._delegated = false;
    this._lastRenderedKey = "";
    this._effectsOpen = false;
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
    return 5;
  }

  // ---- rendering ----

  _render() {
    if (!this._hass || !this._config) return;
    const cfg = this._config;
    const lightState = this._hass.states[cfg.light_entity];
    const isOn = lightState && lightState.state === "on";
    const activeEffect = lightState && lightState.attributes
        ? lightState.attributes.effect
        : null;
    const lightFound = !!lightState;

    const key = [
      lightFound, isOn, activeEffect || "",
      this._effectsOpen,
      JSON.stringify(cfg.presets || []),
    ].join("|");
    if (key === this._lastRenderedKey && this.shadowRoot.firstChild) {
      return;
    }
    this._lastRenderedKey = key;

    this.shadowRoot.innerHTML =
        `<style>${this._buildStyle()}</style>` +
        this._buildHTML(isOn, activeEffect, lightFound);

    if (!this._delegated) {
      this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
      this._delegated = true;
    }
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

      /* ─── Header ────────────────────────────────────────── */
      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;
      }
      .title {
        font-size: 1.1em;
        font-weight: 500;
      }

      /* HA's standard switch shape. Matches ha-switch via
         --switch-checked-* and --switch-unchecked-* CSS vars. */
      .toggle {
        position: relative;
        width: 44px;
        height: 24px;
        background: var(--switch-unchecked-track-color,
                        var(--secondary-background-color, #6b6b6b));
        border: none;
        border-radius: 999px;
        padding: 0;
        cursor: pointer;
        transition: background-color 0.18s ease;
        outline: none;
        font-size: 0;
      }
      .toggle::before {
        content: "";
        position: absolute;
        top: 3px;
        left: 3px;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: var(--switch-unchecked-button-color, #fafafa);
        box-shadow: 0 1px 3px rgba(0,0,0,0.3);
        transition: left 0.18s ease, background-color 0.18s ease;
      }
      .toggle.on {
        background: var(--switch-checked-track-color,
                        var(--primary-color, #03a9f4));
      }
      .toggle.on::before {
        left: 23px;
        background: var(--switch-checked-button-color, #fff);
      }

      /* ─── State label (big "Off" / current effect / etc.) ─ */
      .state-label {
        text-align: center;
        font-size: 1.6em;
        font-weight: 400;
        margin: 14px 0 4px;
      }
      .state-sublabel {
        text-align: center;
        font-size: 0.85em;
        color: var(--secondary-text-color, #a0a0a0);
        margin-bottom: 18px;
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
      .swatch.preset {
        position: relative;
      }
      .preset-name-tooltip {
        /* tooltip via title attribute — no inline label */
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

  _buildHTML(isOn, activeEffect, lightFound) {
    const cfg = this._config;
    const toggleClass = isOn ? "toggle on" : "toggle";
    const toggleAria = isOn ? "Pool light on" : "Pool light off";

    const errorBanner = lightFound ? "" : `
      <div class="error-banner">
        Entity <code>${cfg.light_entity}</code> not found in
        Home Assistant. Add a <code>prefix:</code> override to
        the card's YAML config or look up the real ID in
        Developer Tools → States.
      </div>`;

    // State label (the big "Off" / "Nova" / "On" text under the
    // header — mimics the prominent state display in HA's
    // more-info-light dialog).
    let stateMain;
    let stateSub = "";
    if (!isOn) {
      stateMain = "Off";
    } else if (activeEffect && activeEffect !== "None") {
      stateMain = activeEffect;
      stateSub = "Show";
    } else {
      stateMain = "On";
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
        <div class="header">
          <span class="title">Pool Light</span>
          <button class="${toggleClass}" data-action="toggle"
                  aria-label="${toggleAria}"></button>
        </div>

        <div class="state-label">${stateMain}</div>
        ${stateSub ? `<div class="state-sublabel">${stateSub}</div>`
                   : `<div style="height:18px;"></div>`}

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

      case "solid":
        await hass.callService("button", "press",
            {entity_id: `button.${cfg.prefix}${t.dataset.button}`});
        await hass.callService("light", "turn_on",
            {entity_id: cfg.light_entity, effect: "None"});
        break;

      case "return":
        // Don't call light.turn_on after — bridge handles state via
        // last_send_was_return short-circuit.
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
        this._lastRenderedKey = "";  // bust cache → re-render
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
      "Pool light controls — solid colour swatches, custom show "
      + "dropdown with circular previews, Lock + Return + on/off.",
  preview: false,
});
