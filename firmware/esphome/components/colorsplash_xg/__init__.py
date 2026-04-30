"""ESPHome codegen for the ColorSplash XG pool-light BLE component.

Wraps the single-byte protocol documented in ``docs/PROTOCOL.md``
inside a BLEClientBase subclass so it integrates with the standard
ESPHome BLE stack.
"""

import esphome.codegen as cg
from esphome.components import esp32_ble, esp32_ble_client, esp32_ble_tracker
from esphome.components.esp32_ble import BTLoggers
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_MAC_ADDRESS

AUTO_LOAD = ["esp32_ble_client"]
CODEOWNERS = ["@Vixen-Labs"]
DEPENDENCIES = ["esp32_ble_tracker"]

colorsplash_xg_ns = cg.esphome_ns.namespace("colorsplash_xg")
ColorSplashXG = colorsplash_xg_ns.class_(
    "ColorSplashXG",
    esp32_ble_client.BLEClientBase,
)

# Exported for platform subdirectories (e.g. light/__init__.py) so a
# user's light: block can reference the parent component by id.
CONF_COLORSPLASH_XG_ID = "colorsplash_xg_id"

CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(ColorSplashXG),
            # Optional override. Leave unset (the normal case) to use
            # local-name auto-discovery — the controller advertises
            # itself as ``BGScripr`` per PROTOCOL.md §Controller hardware.
            cv.Optional(CONF_MAC_ADDRESS): cv.mac_address,
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
    .extend(esp32_ble_tracker.ESP_BLE_DEVICE_SCHEMA),
    # Reserve one of the limited ESP32 BLE connection slots for us.
    esp32_ble.consume_connection_slots(1, "colorsplash_xg"),
)


async def to_code(config):
    # Register the GATT logger category so BLEClientBase's
    # event-handler ESP_LOGD lines survive the link-time prune.
    esp32_ble.register_bt_logger(BTLoggers.GATT)
    # Our effect_codec + GATT calls reference ESPBTUUID.
    cg.add_define("USE_ESP32_BLE_UUID")

    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await esp32_ble_tracker.register_client(var, config)

    if CONF_MAC_ADDRESS in config:
        cg.add(var.set_mac_override(config[CONF_MAC_ADDRESS].as_hex))
