"""ESPHome light platform for the ColorSplash XG pool-light bridge.

Exposes a binary (on/off) light entity whose effects cover the 12
canonical presets the controller speaks (5 solid colors + 7 shows).
Lock (0x0D), Return (0x0E), and Standby (0x00) are deliberately
omitted — Standby is the OFF semantic, Lock/Return are surfaced as
separate button entities.
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

# The fixture emits pure saturated primaries — per user observation,
# there's no nuance. "Miami Pink" is pure magenta, not salmon; the
# colors map cleanly to the 6 RGB vertices/faces. Arctic White is
# full-white.
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

    # Register each solid color's (byte, r, g, b). The light's
    # write_state uses this table to snap HA's requested RGB to the
    # nearest preset when HA calls turn_on with a color.
    for name, byte, (r, g, b) in SOLID_COLORS:
        cg.add(var.register_solid(name, byte, r, g, b))

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
