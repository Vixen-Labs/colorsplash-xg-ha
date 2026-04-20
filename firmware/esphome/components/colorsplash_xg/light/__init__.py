"""ESPHome light platform for the ColorSplash XG pool-light bridge.

Exposes a binary (on/off) light entity whose effects cover only
the 7 show animations the controller speaks. The 5 solid colors
and the Lock/Return controls surface as button entities defined
in YAML — HA's light-entity color picker can't be constrained to
the fixture's exact palette, so buttons give a cleaner 1:1 mapping.
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

# Single source of truth for the light entity's display structure.
# Cross-verified by tests/test_esphome_light_effects.py against
# tools/cli.py.
#
# The 5 solid colors are NOT exposed as effects — they're registered
# as RGB targets so HA's light card shows them via its color picker
# rather than cluttering the effect dropdown. The 7 shows remain as
# effects (they're animations, not steady colors).
#
# RGB values are chosen to match each solid's color name. The
# fixture's actual emission may differ slightly due to LED spectrum
# and the controller's DAC; these values are what HA displays.

# Reference table of the 5 solid colors. Not used by the light
# platform itself (the 5 solids are exposed as button entities in
# YAML, not effects); kept here as single-source-of-truth
# documentation and for the cross-check test.
#
# The fixture emits pure saturated primaries (user-observed
# 2026-04-20) — red #FF0000, green #00FF00, blue #0000FF, white
# #FFFFFF, magenta #FF00FF.
SOLID_COLORS: list[tuple[str, int, tuple[int, int, int]]] = [
    ("Parisian Blue",      0x08, (0x00, 0x00, 0xFF)),
    ("Brazilian Red",      0x0A, (0xFF, 0x00, 0x00)),
    ("Arctic White",       0x0B, (0xFF, 0xFF, 0xFF)),
    ("Miami Pink",         0x0C, (0xFF, 0x00, 0xFF)),
    ("New Zealand Green",  0x09, (0x00, 0xFF, 0x00)),
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

# LIGHT_SCHEMA (not BINARY_LIGHT_SCHEMA) — we don't want the `strobe`
# effect or other user-added effects muddling our hardcoded presets.
CONFIG_SCHEMA = light.LIGHT_SCHEMA.extend(
    {
        cv.GenerateID(CONF_OUTPUT_ID): cv.declare_id(ColorSplashLightOutput),
        cv.GenerateID(CONF_COLORSPLASH_XG_ID): cv.use_id(ColorSplashXG),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_OUTPUT_ID])
    await light.register_light(var, config)

    parent = await cg.get_variable(config[CONF_COLORSPLASH_XG_ID])
    cg.add(var.set_parent(parent))

    # Build the 7 show effects in codegen and pass them all to
    # LightState::add_effects in a single call. LightState's
    # implementation assigns (`this->effects_ = effects;`) rather
    # than appending, so the list must be passed whole.
    light_var = await cg.get_variable(config[CONF_ID])
    effect_vars = []
    for i, (name, byte) in enumerate(SHOW_EFFECTS):
        effect_id = ID(
            f"{config[CONF_ID].id}_show_{i}",
            is_declaration=True,
            type=ColorSplashPresetEffect,
        )
        effect_var = cg.new_Pvariable(effect_id, name, byte, parent)
        effect_vars.append(effect_var)
    cg.add(light_var.add_effects(effect_vars))
