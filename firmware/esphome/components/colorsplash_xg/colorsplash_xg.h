#pragma once

#ifdef USE_ESP32

#include "effect_codec.h"

#include "esphome/components/esp32_ble_client/ble_client_base.h"
#include "esphome/components/esp32_ble_tracker/esp32_ble_tracker.h"
#include "esphome/core/component.h"

#include <deque>

namespace esphome {
namespace colorsplash_xg {

namespace espbt = esphome::esp32_ble_tracker;

// Matches the local name the J&J LPL-XG-CTRL-1 advertises — the
// Silicon Labs BT121 BGScript runtime identifier. See
// docs/PROTOCOL.md §Controller hardware.
constexpr const char *CONTROLLER_LOCAL_NAME = "BGScripr";

// Vendor GATT identifiers from docs/PROTOCOL.md §BLE topology.
constexpr const char *SERVICE_UUID_STR =
    "5d5f4714-57e5-11e5-885d-feff819cdc9f";
constexpr const char *COMMAND_CHAR_UUID_STR =
    "4cabed4d-3f58-4429-b29c-f9a26205f28e";

// Standard Bluetooth SIG Client Characteristic Configuration.
constexpr uint16_t CCCD_UUID_U16 = 0x2902;

// Single-byte value written to the CCCD to enable indications (not
// notifications) on the command characteristic. See
// docs/PROTOCOL.md §Framing step 2.
constexpr uint16_t CCCD_INDICATION_ENABLE = 0x0002;

class ColorSplashXG : public esp32_ble_client::BLEClientBase {
 public:
  void setup() override;
  void loop() override;
  void dump_config() override;

  // Discovery hook — fires for every observed advertising packet.
  // We match on local name (or the optional MAC override), then hand
  // off to the base class to drive the DISCOVERED→CONNECTING state
  // machine.
  bool parse_device(const espbt::ESPBTDevice &device) override;

  // Post-connect GATT events — we chain to the base class for
  // ESPHome's standard lifecycle handling, then add our own logic
  // on top (locate characteristic, arm CCCD, observe echoes).
  bool gattc_event_handler(esp_gattc_cb_event_t event,
                           esp_gatt_if_t gattc_if,
                           esp_ble_gattc_cb_param_t *param) override;

  // Public API — used by YAML lambdas and (soon) the light entity
  // in #11.
  void send_effect_byte(uint8_t byte_value);
  bool is_ready() const { return this->cccd_armed_; }
  optional<uint8_t> last_echoed_byte() const { return this->last_echoed_; }

  // Optional YAML override for environments with multiple BGScripr
  // peripherals in range.
  void set_mac_override(uint64_t mac) { this->mac_override_ = mac; }

 protected:
  // Attempt to send the next byte from the pending queue. No-op if
  // disconnected or no echo has been received yet for a prior write
  // (we keep in-flight depth to 1 to avoid confusing the controller).
  void try_drain_pending_();

  void arm_cccd_();
  bool cccd_armed_{false};

  // Handle cache populated during service discovery.
  uint16_t cmd_char_handle_{0};
  uint16_t cmd_cccd_handle_{0};

  uint64_t mac_override_{0};
  bool write_in_flight_{false};
  std::deque<uint8_t> pending_writes_;
  optional<uint8_t> last_echoed_;
};

}  // namespace colorsplash_xg
}  // namespace esphome

#endif  // USE_ESP32
