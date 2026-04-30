"""ESPHome light platform for the ColorSplash XG pool-light bridge.

Exposes a binary (on/off) light entity whose effects cover all
12 selectable hardware states: 5 solid colors + 7 show animations.
Lock and Return are control bytes (not selectable colors), so they
remain as button entities in YAML.

Folding solids into the effect list lets HA scenes capture solid
selection natively via `light.pool_light.effect: <name>` — the
same shape scenes already use for shows. User-saved presets
(recipe-based, runtime-mutable) are exposed separately via
`select.pool_active_preset` since ESPHome light effects are
compile-time-fixed.
"""

import esphome.codegen as cg
from esphome.components import light
from esphome.components.light.types import LightEffect
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_OUTPUT_ID
from esphome.core import ID

from .. import CONF_COLORSPLASH_XG_ID, ColorSplashXG, colorsplash_xg_ns

DEPENDENCIES = ["colorsplash_xg"]

ColorSplashLightOutput = colorsplash_xg_ns.class_(
    "ColorSplashLightOutput",
    light.LightOutput,
)
ColorSplashPresetEffect = colorsplash_xg_ns.class_(
    "ColorSplashPresetEffect",
    LightEffect,
)

# Single source of truth for the light entity's effect list.
# Cross-verified by tests/test_esphome_light_effects.py against
# tools/cli.py.
#
# All 12 selectable hardware states (5 solids + 7 shows) are
# advertised as light effects so HA scenes can natively capture
# fixture selection via the effect attribute. Lock (0x0D) and
# Return (0x0E) stay as button entities (not selectable colors).
SOLID_EFFECTS: list[tuple[str, int]] = [
    ("Arctic White",       0x0B),
    ("Brazilian Red",      0x0A),
    ("New Zealand Green",  0x09),
    ("Parisian Blue",      0x08),
    ("Miami Pink",         0x0C),
]

SHOW_EFFECTS: list[tuple[str, int]] = [
    ("Nova",               0x07),
    ("Super Nova",         0x02),
    ("Northern Lights",    0x03),
    ("Tidal Wave",         0x04),
    ("Patriot Dream",      0x05),
    ("Desert Skies",       0x06),
    ("Peruvian Paradise",  0x01),
]

# Combined list passed to LightState::add_effects. Solids first so
# they appear at the top of HA's effect dropdown.
ALL_EFFECTS: list[tuple[str, int]] = SOLID_EFFECTS + SHOW_EFFECTS

# Phase 4b experimental flag — when true, the light advertises
# ColorMode::RGB in addition to ON_OFF, so HA's standard light card
# shows a color wheel that drives the embedded show-scrub picker
# (see firmware/esphome/components/colorsplash_xg/show_color_lut.h).
# Default off — issue #54 keeps the classic effects-only interface
# as the stable default since the color gamut is constrained and
# can confuse users who expect arbitrary RGB to "just work".
CONF_RGB_MODE = "rgb_mode"

# LIGHT_SCHEMA (not BINARY_LIGHT_SCHEMA) — we don't want the `strobe`
# effect or other user-added effects muddling our hardcoded presets.
CONFIG_SCHEMA = light.LIGHT_SCHEMA.extend(
    {
        cv.GenerateID(CONF_OUTPUT_ID): cv.declare_id(ColorSplashLightOutput),
        cv.GenerateID(CONF_COLORSPLASH_XG_ID): cv.use_id(ColorSplashXG),
        cv.Optional(CONF_RGB_MODE, default=False): cv.boolean,
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_OUTPUT_ID])
    await light.register_light(var, config)

    parent = await cg.get_variable(config[CONF_COLORSPLASH_XG_ID])
    cg.add(var.set_parent(parent))
    cg.add(var.set_rgb_mode(config[CONF_RGB_MODE]))

    # Build all 12 effects in codegen and pass them to
    # LightState::add_effects in a single call. LightState's
    # implementation assigns (`this->effects_ = effects;`) rather
    # than appending, so the list must be passed whole.
    light_var = await cg.get_variable(config[CONF_ID])
    effect_vars = []
    for i, (name, byte) in enumerate(ALL_EFFECTS):
        effect_id = ID(
            f"{config[CONF_ID].id}_effect_{i}",
            is_declaration=True,
            type=ColorSplashPresetEffect,
        )
        effect_var = cg.new_Pvariable(effect_id, name, byte, parent)
        effect_vars.append(effect_var)
    cg.add(light_var.add_effects(effect_vars))
