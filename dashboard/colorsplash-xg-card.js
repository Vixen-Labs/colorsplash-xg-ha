/**
 * ColorSplash XG custom Lovelace card.
 *
 * A cohesive pool-control surface for the LPL-XG-CTRL-1 fixture
 * driven by the headless ESP32 bridge. Renders the five solid
 * colours as full-fill swatches, the seven shows as gradient
 * thumbnails, the Return primitive as a neutral "R" tile, and
 * Lock as a visually distinct save button.
 *
 * Resolves issue #41. See dashboard/README.md for install
 * instructions.
 *
 * Design notes:
 * - Single vanilla `customElements` class. No build step. Drop
 *   into /config/www/ and register as a Lovelace resource.
 * - Shadow DOM for style isolation.
 * - All theming via HA CSS custom properties so dark/light look
 *   right.
 * - Event delegation on shadowRoot keyed by data-action so
 *   re-renders never leak listeners.
 *
 * No HA-side modules are imported — this file targets HA's
 * built-in Lovelace runtime which provides hass + setConfig.
 */

const VERSION = "0.3.1";

// 5 documented solid presets (from PROTOCOL.md and the firmware's
// SOLID_COLORS table). RGB values are the canonical bright primaries
// the names imply, used both for the swatch fill and as a hint for
// the user about what each one does.
const SOLIDS = [
  {name: "Parisian Blue",      btn: "pool_parisian_blue",      hex: "#0000FF"},
  {name: "Brazilian Red",      btn: "pool_brazilian_red",      hex: "#FF0000"},
  {name: "Arctic White",       btn: "pool_arctic_white",       hex: "#FFFFFF"},
  {name: "Miami Pink",         btn: "pool_miami_pink",         hex: "#FF00FF"},
  {name: "New Zealand Green",  btn: "pool_new_zealand_green",  hex: "#00FF00"},
];

// 7 documented shows. The gradient[] arrays are sampled from the
// hex sequences documented in docs/PROTOCOL.md §Show color
// gradients. For shows with truncated gradients, we use endpoints
// + a midpoint guess; full fidelity is left for a future re-grep
// of the app decompile.
const SHOWS = [
  {
    name: "Nova",
    effect: "Nova",
    gradient: ["#FEEA00", "#71CD2E", "#02ADF9", "#1649D5", "#DC0BB3",
               "#FFBF1C", "#17B63F", "#00B2E1", "#205ADB", "#CB00A9"],
  },
  {
    name: "Super Nova",
    effect: "Super Nova",
    gradient: ["#FEEA00", "#71CD2E", "#02ADF9", "#1649D5", "#DC0BB3",
               "#FFBF1C", "#17B63F", "#00B2E1", "#205ADB", "#CB00A9"],
  },
  {
    name: "Northern Lights",
    effect: "Northern Lights",
    gradient: ["#FD3000", "#FFC000", "#54CD00", "#01C2F4", "#0E65F7", "#FD01AE"],
  },
  {
    name: "Tidal Wave",
    effect: "Tidal Wave",
    // Documented as "12-step blue-to-cyan #00A351 … #0675AB"; using
    // documented endpoints + a midpoint. Re-grep for full fidelity.
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
    // Documented as "23-step amber → magenta"; placeholder
    // endpoints + midpoint until re-grep.
    gradient: ["#FFA000", "#FF6080", "#FF00C0"],
  },
  {
    name: "Peruvian Paradise",
    effect: "Peruvian Paradise",
    // Documented as "33-step white → magenta → teal"; placeholder
    // endpoints + middle until re-grep.
    gradient: ["#FFFFFF", "#FF40E0", "#00C0A0"],
  },
];

// Entity-id prefix that HA prepends to all entities created by the
// ESPHome integration. Matches `friendly_name: ColorSplash XG Bridge`
// → `colorsplash_xg_bridge_`. If you flashed the display variant
// instead, set prefix to `colorsplash_xg_` (no `_bridge`). If you
// renamed the device in HA, set prefix to whatever shows up in
// Developer Tools → States.
const DEFAULT_PREFIX = "colorsplash_xg_bridge_";

const DEFAULTS = {
  // Entity-id prefix override — see DEFAULT_PREFIX comment above.
  prefix: DEFAULT_PREFIX,

  // Per-entity overrides take precedence over the prefix-built
  // defaults. Pass any subset; unspecified ones use prefix + slug.
  light_entity: null,
  lock_entity: null,
  return_entity: null,

  // ESPHome service name for the bridge's pool_scrub — used to
  // fire saved presets. Default matches the headless variant's
  // device-name slug (`colorsplash-xg-bridge`). HA service names
  // use underscores: dots between domain.service are auto-handled.
  scrub_service: "esphome.colorsplash_xg_bridge_pool_scrub",

  // Reserved for issue #53 — saved colour presets. Each preset is
  // a `{name, hex, start_byte, wait_ms}` object:
  //
  //   - name        human label rendered under / over the swatch
  //   - hex         CSS colour string for the swatch fill (the
  //                 colour the user observed when they saved this)
  //   - start_byte  show byte to send (0x01..0x07) — see PROTOCOL.md
  //   - wait_ms     offset within the show cycle to send Lock at
  //
  // When the array is non-empty the card renders a "Saved Presets"
  // section between the Colours row and the Shows row. Tapping a
  // preset calls scrub_service with {start_byte, wait_ms} and the
  // bridge runs the lock sequence.
  //
  // Empty by default. The future preset-card UI work in #53 will
  // populate this dynamically (HA storage, in-card editor, etc.).
  // For now it can be set manually via card YAML:
  //
  //   type: custom:colorsplash-xg-card
  //   presets:
  //     - {name: "Sunset Magenta", hex: "#dc6b9c", start_byte: 5, wait_ms: 7000}
  //     - {name: "Pool Cyan",      hex: "#5fa8c4", start_byte: 4, wait_ms: 15788}
  presets: [],
};


class ColorSplashCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: "open"});
    this._delegated = false;
    this._lastRenderedKey = "";
  }

  setConfig(config) {
    const merged = {...DEFAULTS, ...(config || {})};
    const prefix = merged.prefix || "";
    // Resolve entity IDs: explicit override wins, otherwise built
    // from prefix + slug. Solid buttons are always built from
    // prefix + solid.btn unless the user overrides at the per-solid
    // level (rare; not exposed for v1).
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
    return 5;  // ~5 rows tall in HA's grid layout
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

    // Cheap re-render gate so re-rendering on every hass update
    // doesn't churn the DOM if nothing relevant changed.
    const key = `${lightFound}|${isOn}|${activeEffect || ""}`;
    if (key === this._lastRenderedKey && this.shadowRoot.firstChild) {
      return;
    }
    this._lastRenderedKey = key;

    this.shadowRoot.innerHTML =
        `<style>${this._buildStyle()}</style>` +
        this._buildHTML(isOn, activeEffect);

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
        background: var(--card-background-color, #1c1c1e);
        color: var(--primary-text-color, #fff);
        border-radius: var(--ha-card-border-radius, 12px);
        padding: 16px;
        box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.2));
      }
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
      .toggle {
        background: var(--primary-color, #03a9f4);
        color: var(--text-primary-color, #fff);
        border: none;
        border-radius: 999px;
        padding: 6px 16px;
        font-size: 0.95em;
        cursor: pointer;
        transition: transform 0.08s ease;
      }
      .toggle.off {
        background: var(--secondary-background-color, #2c2c2e);
        color: var(--secondary-text-color, #a0a0a0);
      }
      .toggle:active { transform: scale(0.96); }
      .group-label {
        font-size: 0.75em;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--secondary-text-color, #a0a0a0);
        margin: 12px 0 8px;
      }
      .row {
        display: grid;
        gap: 8px;
      }
      .solids {
        grid-template-columns: repeat(6, 1fr);
      }
      .shows {
        grid-template-columns: repeat(2, 1fr);
      }
      .swatch, .show-tile, .control-tile {
        position: relative;
        border-radius: 10px;
        height: 56px;
        cursor: pointer;
        border: 2px solid transparent;
        overflow: hidden;
        transition: transform 0.08s ease, border-color 0.15s ease;
        user-select: none;
      }
      .swatch:active,
      .show-tile:active,
      .control-tile:active {
        transform: scale(0.95);
      }
      .swatch.return {
        background: var(--secondary-background-color, #2c2c2e);
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .swatch.return .badge {
        font-size: 1.6em;
        font-weight: 700;
        color: var(--primary-text-color, #fff);
      }
      .swatch.preset {
        display: flex;
        align-items: flex-end;
        padding: 4px 6px;
      }
      .swatch.preset .preset-name {
        font-size: 0.7em;
        font-weight: 600;
        color: #fff;
        text-shadow: 0 1px 2px rgba(0,0,0,0.7);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 100%;
      }
      .empty-presets {
        font-size: 0.8em;
        color: var(--secondary-text-color, #a0a0a0);
        font-style: italic;
        padding: 6px 0;
      }
      .swatch[title] { /* tooltip handled by browser */ }
      .show-tile {
        height: 64px;
        display: flex;
        align-items: flex-end;
        padding: 6px 8px;
      }
      .show-tile .name {
        font-size: 0.78em;
        font-weight: 600;
        color: #fff;
        text-shadow: 0 1px 2px rgba(0,0,0,0.6);
      }
      .show-tile.active {
        border-color: var(--primary-color, #03a9f4);
        box-shadow: 0 0 0 3px rgba(3,169,244,0.25);
      }
      .lock-btn {
        margin-top: 12px;
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
      .lock-btn:active { transform: scale(0.97); }
      .lock-btn::before {
        content: "🔒  ";
      }
      /* No off-state dim — every tap turns the light on, so the
         card always looks active. State is reflected in the toggle
         button at the top, not by greying out controls. */
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

  _buildHTML(isOn, activeEffect) {
    const cfg = this._config;
    const lightFound = !!this._hass.states[cfg.light_entity];
    const toggleLabel = isOn ? "On" : "Off";
    const toggleClass = isOn ? "toggle" : "toggle off";

    // If the configured light entity isn't in HA's state map, the
    // card has nothing real to drive — show an obvious banner with
    // the configured ID + a hint to override `prefix:` rather than
    // silently rendering a greyed-out card.
    const errorBanner = lightFound ? "" : `
      <div class="error-banner">
        Entity <code>${cfg.light_entity}</code> not found in
        Home Assistant. Either flash the bridge, or add a
        <code>prefix:</code> override to the card's YAML config.
        Look up the real ID in
        Developer Tools → States (search for <code>pool_light</code>).
      </div>`;

    const solidSwatches = SOLIDS.map((s) =>
      `<div class="swatch" data-action="solid"
            data-button="${s.btn}"
            title="${s.name}"
            style="background:${s.hex};"></div>`
    ).join("");

    const returnSwatch =
        `<div class="swatch return" data-action="return"
              title="Return — replay last-locked colour">
           <span class="badge">R</span>
         </div>`;

    const showTiles = SHOWS.map((sh) => {
      const grad = sh.gradient.length === 1
          ? sh.gradient[0]
          : `linear-gradient(135deg, ${sh.gradient.join(", ")})`;
      const cls = activeEffect === sh.effect ? "show-tile active" : "show-tile";
      return `<div class="${cls}" data-action="show"
                   data-effect="${sh.effect}"
                   style="background:${grad};">
                <span class="name">${sh.name}</span>
              </div>`;
    }).join("");

    // Saved presets — empty by default until #53 lands a UI for
    // saving / managing them. Renders a "Saved Presets" section
    // between Colours and Shows so the layout is already grouped
    // for the user when presets exist.
    const presets = Array.isArray(cfg.presets) ? cfg.presets : [];
    const presetsBlock = presets.length === 0
        ? `<div class="empty-presets">
             No saved presets yet. Issue #53 will add a save button
             to the colour wheel; for now you can pre-populate
             <code>presets:</code> in this card's YAML config.
           </div>`
        : `<div class="row solids">
             ${presets.map((p, i) =>
               `<div class="swatch preset"
                     data-action="preset"
                     data-preset-index="${i}"
                     title="${p.name || ""} — start_byte=0x${(p.start_byte || 0).toString(16)} wait_ms=${p.wait_ms || 0}"
                     style="background:${p.hex || "#444"};">
                  <span class="preset-name">${p.name || ""}</span>
                </div>`
             ).join("")}
           </div>`;

    return `
      <div class="card">
        ${errorBanner}
        <div class="header">
          <span class="title">Pool Light</span>
          <button class="${toggleClass}" data-action="toggle">${toggleLabel}</button>
        </div>

        <div class="group-label">Colours</div>
        <div class="row solids">
          ${solidSwatches}
          ${returnSwatch}
        </div>

        <div class="group-label">Saved Presets</div>
        ${presetsBlock}

        <div class="group-label">Shows</div>
        <div class="row shows">
          ${showTiles}
        </div>

        <button class="lock-btn" data-action="lock">Lock current colour</button>
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
        // Press the solid's button entity FIRST so the bridge's
        // last_preset_byte is updated to the new colour. Then
        // call light.turn_on with effect: None so HA's light
        // entity flips to on + clears the effect attribute. The
        // light.turn_on triggers the bridge's write_state which
        // re-sends last_preset_byte; the dedup window in
        // send_effect_byte (500 ms) catches the duplicate.
        await hass.callService("button", "press",
                               {entity_id:
                                `button.${cfg.prefix}${t.dataset.button}`});
        await hass.callService("light", "turn_on",
                               {entity_id: cfg.light_entity,
                                effect: "None"});
        break;

      case "return":
        // Return (0x0e) tells the controller to replay the colour
        // that was Locked previously. After firing it we also
        // call light.turn_on(effect:None) so HA's light entity
        // flips to "on" + clears the effect attribute. The bridge
        // detects the post-Return state via was_last_send_return()
        // in write_state and short-circuits the last_preset
        // replay that would otherwise stomp the locked colour.
        await hass.callService("button", "press",
                               {entity_id: cfg.return_entity});
        await hass.callService("light", "turn_on",
                               {entity_id: cfg.light_entity,
                                effect: "None"});
        break;

      case "show":
        await hass.callService("light", "turn_on",
                               {entity_id: cfg.light_entity,
                                effect: t.dataset.effect});
        break;

      case "lock":
        await hass.callService("button", "press",
                               {entity_id: cfg.lock_entity});
        break;

      case "preset": {
        // Saved preset: fire pool_scrub on the bridge, which sends
        // start_byte → waits wait_ms → sends Lock. Format of the
        // preset object is documented in DEFAULTS.presets.
        const idx = parseInt(t.dataset.presetIndex, 10);
        const p = (cfg.presets || [])[idx];
        if (!p) {
          console.warn("preset index out of range", idx);
          break;
        }
        // Service IDs in HA are dot-separated "domain.service".
        const [domain, name] = cfg.scrub_service.split(".", 2);
        await hass.callService(domain, name, {
          start_byte: p.start_byte | 0,
          wait_ms: p.wait_ms | 0,
        });
        // Mirror the colour-pick state: light on, effect cleared.
        await hass.callService("light", "turn_on",
                               {entity_id: cfg.light_entity,
                                effect: "None"});
        break;
      }
    }
  }
}


customElements.define("colorsplash-xg-card", ColorSplashCard);
console.info(`%c colorsplash-xg-card %c v${VERSION} `,
  "color: white; background: #03a9f4; font-weight: 700;",
  "color: #03a9f4; background: white; font-weight: 700;");

// Register with HA's Lovelace card-picker so it shows up nicely
// in "Add card" UI.
window.customCards = window.customCards || [];
window.customCards.push({
  type: "colorsplash-xg-card",
  name: "ColorSplash XG",
  description:
      "Pool light controls — solid colours, shows with gradient previews, "
      + "Lock + Return + on/off.",
  preview: false,
});
