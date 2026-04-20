# dashboard

Home Assistant Lovelace card configs for controlling the
ColorSplash XG fixture through the ESPHome bridge firmware shipped
in `firmware/esphome/`.

## Files

- **`colorsplash-xg.yaml`** — stock-Lovelace card config (tile + grid
  + light cards). No custom resources, no HACS. Paste-to-install.

## Install (paste-into-dashboard version)

1. In Home Assistant, open the dashboard where you want the card.
2. Click the pencil (Edit Dashboard) → **`+ Add Card`** →
   **Manual** at the bottom.
3. Paste the entire contents of
   [`colorsplash-xg.yaml`](colorsplash-xg.yaml) into the YAML
   editor.
4. Save.

That's it. The card assumes the default entity IDs the ESPHome
firmware exposes — if you renamed any entities in HA (e.g.
`light.pool_light` → `light.backyard_pool`), update the matching
`entity:` line in your pasted YAML.

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
