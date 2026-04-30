"""ESPHome select platform for the ColorSplash XG bridge — exposes
saved color presets as an HA select entity.

The select's options list mirrors the bridge's preset table at
runtime: a `(none)` sentinel + the slug of every saved preset.
Selecting an option calls `color_preset_recall(slug)` on the
parent component. The select also publishes its state when a
preset is recalled via any other path (the JS card, an
automation, a scene activation), so HA scene snapshots round-trip
cleanly.

This pairs with the light entity's effect list (which carries the
12 hardware effects) — together they let HA scenes capture the
fixture's full state via two natural entities (#73, #75).
"""

import esphome.codegen as cg
from esphome.components import select
import esphome.config_validation as cv
from esphome.const import CONF_ID

from .. import CONF_COLORSPLASH_XG_ID, ColorSplashXG, colorsplash_xg_ns

DEPENDENCIES = ["colorsplash_xg"]

ColorSplashSelect = colorsplash_xg_ns.class_(
    "ColorSplashSelect",
    select.Select,
    cg.PollingComponent,
)

# Sentinel option used when no preset is currently active (e.g.,
# right after Standby or a hardware effect). Kept in sync with
# colorsplash_select.cpp's NONE_OPTION constant.
NONE_OPTION = "(none)"

CONFIG_SCHEMA = select.select_schema(ColorSplashSelect).extend(
    {
        cv.GenerateID(): cv.declare_id(ColorSplashSelect),
        cv.GenerateID(CONF_COLORSPLASH_XG_ID): cv.use_id(ColorSplashXG),
    }
).extend(cv.polling_component_schema("1s"))


async def to_code(config):
    parent = await cg.get_variable(config[CONF_COLORSPLASH_XG_ID])
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    # Initial options list — at least the sentinel must be present
    # before HA discovers the entity. The runtime updates the list
    # via traits.set_options() as presets are added/deleted; HA
    # picks up the new options on the next API connection.
    await select.register_select(var, config, options=[NONE_OPTION])
    cg.add(var.set_parent(parent))
