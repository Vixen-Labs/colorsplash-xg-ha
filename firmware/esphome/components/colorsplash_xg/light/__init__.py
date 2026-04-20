"""ESPHome light platform for the ColorSplash XG pool-light bridge.

Exposes a binary (on/off) light entity whose effects cover the 12
canonical presets the controller speaks (5 solid colors + 7 shows).
Lock (0x0D), Return (0x0E), and Standby (0x00) are deliberately
omitted — Standby is the OFF semantic, Lock/Return are surfaced as
separate button entities.
"""

import esphome.codegen as cg
from esphome.components import light
import esphome.config_validation as cv
from esphome.const import CONF_OUTPUT_ID

from .. import CONF_COLORSPLASH_XG_ID, ColorSplashXG, colorsplash_xg_ns

DEPENDENCIES = ["colorsplash_xg"]

ColorSplashLightOutput = colorsplash_xg_ns.class_(
    "ColorSplashLightOutput",
    light.LightOutput,
)

# Single source of truth for the light entity's effect list. Tested
# by tests/test_esphome_light_effects.py against tools/cli.py. The
# order below is the HA-displayed order — solid colors first, then
# shows, matching the stock app's tile grid layout.
PRESET_EFFECTS: list[tuple[str, int]] = [
    # Solid colors
    ("Parisian Blue",      0x08),
    ("Brazilian Red",      0x0A),
    ("Arctic White",       0x0B),
    ("Miami Pink",         0x0C),
    ("New Zealand Green",  0x09),
    # Shows
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

    for name, byte in PRESET_EFFECTS:
        cg.add(var.register_preset(name, byte))
