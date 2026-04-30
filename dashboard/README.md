# dashboard

Home Assistant Lovelace card configs for controlling the
ColorSplash XG fixture through the ESPHome bridge firmware shipped
in `firmware/esphome/`.

## Files

- **`colorsplash-xg-stack.yaml`** — *recommended*. Native HA
  light card on top (with the color wheel from the firmware's
  RGB mode) + button rows for shows + Color Lock/Return below.
  No custom resources required. Paste-to-install.
- **`colorsplash-xg.yaml`** — older stock-Lovelace card config
  with tile-card color accents instead of the native light
  card. Predates the Phase 4b RGB picker. Kept for users who
  prefer the simpler effects-only interface (no color wheel).
- **`colorsplash-xg-card.js`** — alternate custom card with
  from-scratch swatch grid + gradient show thumbnails. Vanilla
  JS, no build step. Doesn't expose the color wheel — use this
  if you want a more compact pool-control surface than the
  stack approach. See [Custom card install](#custom-card-install)
  below.
- **`automations.yaml`** — example HA automations
  (sunset-on / sunrise-off, RSSI alerts, RGB-picker calls).
  Copy individual blocks into your `automations.yaml` or the UI.

## Install (paste-into-dashboard version)

1. In Home Assistant, open the dashboard where you want the card.
2. Click the pencil (Edit Dashboard) → **`+ Add Card`** →
   **Manual** at the bottom.
3. Paste the entire contents of
   [`colorsplash-xg.yaml`](colorsplash-xg.yaml) into the YAML
   editor.
4. Save.

That's it. The card assumes the default entity IDs the ESPHome
firmware exposes — they all carry the `colorsplash_xg_` prefix
because HA auto-prepends the device's `friendly_name` to entity IDs
whose display name doesn't already start with it.

If you renamed the device or any entities in HA (e.g. the light
to `light.backyard_pool`), update the matching `entity:` line in
your pasted YAML. You can see the real IDs under
**Settings → Devices & Services → ColorSplash XG** or in
**Developer Tools → States** filtered by `pool`.

## What you get

```
┌────────────────────────────────────────┐
│  Pool Light                    [ON  ]  │
│                                         │
│  ● Effect: (dropdown with 7 shows)      │
└────────────────────────────────────────┘
┌──────────┬──────────┬──────────┐
│  ● Blue  │  ● Red   │  ○ White │
├──────────┼──────────┼──────────┤
│  ● Pink  │  ● Green │  ↻ Return│
└──────────┴──────────┴──────────┘
┌────────────────────────────────────────┐
│  🔒 Lock                                │
└────────────────────────────────────────┘
```

- Top: master on/off + 7-effect dropdown via HA's built-in light
  card.
- Middle: 3×2 grid — the 5 solid presets + Return. Tap any tile to
  apply that preset.
- Bottom: Lock — captures the currently-displayed color into the
  controller's "last locked" slot. Return replays it.

## Known limitations of the stock version

The tile card's `color:` property renders as an icon + accent bar
tint, not a full color swatch. This is a stock-Lovelace constraint:
HA doesn't expose full-color-fill tiles in a card-agnostic way.

Specifically:

- The 5 color tiles look subtle — the color hint is a thin accent,
  not a large swatch.
- Arctic White shows as white-on-light-gray in light mode, which
  can be hard to see. Contrast improves in dark mode.
- Miami Pink uses HA's `pink` named color, which isn't pure
  magenta — it's a lighter, less-saturated pink.
- No gradient thumbnails on the show dropdown.
- No "R" badge on the Return tile.

These are exactly the reasons a custom JS card exists in the
roadmap — see the follow-up issue for full-color swatches +
gradient previews. This YAML version is meant to be the simple
drop-in, not the final UX.

## Dark / light mode

All tile card colors use HA theme variables internally, so the
card adapts to your theme automatically. Tested in both modes;
Arctic White's visibility is the only color that's noticeably
affected.

## Customizing

Renaming entities, reordering tiles, or swapping out `mdi:*` icons
for something else is just YAML edits in the pasted block. No
firmware rebuild needed.

## Custom card install

The custom-card version (`colorsplash-xg-card.js`) replaces the
stock card with full-fill color swatches, gradient show
thumbnails, an "R" Return badge, a distinct Lock button, and a
"Saved Presets" section that's wired up for [#53](https://github.com/swizzlevixen/colorsplash-xg-ha/issues/53).

### Install

1. Copy `colorsplash-xg-card.js` to your HA host's
   `/config/www/` directory (the public Lovelace asset folder —
   create it if it doesn't exist).

   ```sh
   # via Samba / SSH:
   cp dashboard/colorsplash-xg-card.js /config/www/
   ```

2. In Home Assistant, register the resource:
   **Settings → Dashboards → ⋮ → Resources → Add resource**.
   - URL: `/local/colorsplash-xg-card.js`
   - Resource type: **JavaScript Module**

3. Edit your dashboard, **+ Add Card → Manual**, paste:

   ```yaml
   type: custom:colorsplash-xg-card
   ```

   That's it — defaults match the headless firmware's entity
   IDs (HA prepends `colorsplash_xg_bridge_` to every entity
   from the device).

   **If you flashed the display variant** instead, override the
   prefix:

   ```yaml
   type: custom:colorsplash-xg-card
   prefix: colorsplash_xg_
   ```

   **If you renamed the device in HA**, set `prefix` to whatever
   you see in Developer Tools → States (look for any of your
   `light.*` or `button.*` entries — everything before
   `pool_light` is the prefix). Or override individual entity
   IDs explicitly:

   ```yaml
   type: custom:colorsplash-xg-card
   light_entity: light.my_pool
   lock_entity: button.my_pool_color_lock
   return_entity: button.my_pool_color_return
   scrub_service: esphome.my_pool_pool_scrub
   ```

4. Hard-reload the dashboard (Cmd-Shift-R / Ctrl-Shift-R) to
   load the new JS module.

### Updating the card

HA caches Lovelace JS resources aggressively — a hard browser
reload often isn't enough after pulling a new version. The
reliable pattern: append `?v=<version>` to the resource URL
matching the `VERSION` constant at the top of the JS file. So
when v0.5.0 ships, set the resource URL to
`/local/colorsplash-xg-card.js?v=0.5.0`. Each version bump in
the JS gets a matching URL bump in
**Settings → Dashboards → Resources**.

The `VERSION` constant is logged to the browser console on every
card mount, so you can verify what's actually loaded:
`colorsplash-xg-card v0.5.0`.

### Saved Presets

User presets live in the bridge's NVS (5 slots max), addressable
by slug. Save one by dragging the card's color wheel until the
fixture lands on a color you like, then tap "Save current color
as preset…" — the card stores the bridge's resolved recipe
`(start_byte, wait_ms)` plus an RGB preview, and the result
shows up as a swatch in the row.

Card-side, the swatches are populated by reading the bridge's
per-slot text_sensors (`sensor.<prefix>pool_color_preset_0..4`)
plus an optional static `presets:` YAML list for read-only
recipes you want to ship in your config:

```yaml
type: custom:colorsplash-xg-card
presets:
  - {name: "Sunset Magenta", hex: "#dc6b9c", start_byte: 5, wait_ms: 7000}
```

Tapping a preset swatch calls `color_preset_recall(slug)` for
user presets, or `pool_scrub(start_byte, wait_ms)` for static
YAML presets. The currently-active user preset gets a halo on
its swatch, driven by `select.pool_active_preset`'s state.

### Bind a preset to a scene

The bridge exposes a `select.pool_active_preset` entity whose
options mirror the slugs of every saved preset. HA scenes
natively capture select-entity state, so binding a preset to a
scene is just listing it in the scene's entities:

```yaml
scene:
  - name: Pool Sunset
    entities:
      select.colorsplash_xg_bridge_pool_active_preset:
        option: sunset_magenta
```

When the scene activates, HA calls `select.select_option`, which
the bridge translates into `color_preset_recall(slug=…)` —
firing the exact stored `(start_byte, wait_ms)` recipe. No
LUT round-trip, no recipe drift.

The select's option list refreshes whenever you save or delete a
preset via the card. The `(none)` sentinel is a no-op option:
including it in a scene clears the "active preset" state without
changing what the fixture is currently showing.

For combining a preset with hardware-effect or on/off state in
the same scene, just list both entities — the light handles
on/off + the 12 hardware effects (5 solids + 7 shows), and the
select handles user presets.

### Custom card preview

```
┌───────────────────────────────────────┐
│  Pool Light                  [ On  ]  │
│                                       │
│  COLORS                              │
│  [B][R][W][P][G][R̲]                   │
│                                       │
│  SAVED PRESETS                        │
│   (empty — see #53)                   │
│                                       │
│  SHOWS                                │
│  [Nova       ][Super Nova    ]        │
│  [Northern L ][Tidal Wave    ]        │
│  [Patriot D  ][Desert Skies  ]        │
│  [Peruvian P                 ]        │
│                                       │
│  [🔒 Lock current color    ]         │
└───────────────────────────────────────┘
```

- Solid swatches are full-color fills (not the muted accents
  of the stock card).
- Show tiles get `linear-gradient(...)` backgrounds derived from
  each show's documented gradient hexes (PROTOCOL.md
  §Show color gradients).
- Active effect highlights with a primary-color border.
- All theming uses HA CSS custom properties so dark + light mode
  both look right.

### Tap behaviour

| Tap | Action |
|---|---|
| On/Off button | `light.toggle` |
| Solid swatch | press solid's button entity + clear active effect |
| Return swatch | press `button.pool_color_return` + clear active effect |
| Show tile | `light.turn_on` with that effect |
| Lock button | press `button.pool_color_lock` |
| Preset swatch | call `pool_scrub` with the saved recipe |

Tapping a solid clears the effect attribute on the light entity
to keep HA's view of state aligned with what the fixture is
actually displaying.
