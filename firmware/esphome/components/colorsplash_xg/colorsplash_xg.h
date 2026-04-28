#pragma once

#ifdef USE_ESP32

#include "effect_codec.h"

#include "esphome/components/esp32_ble_client/ble_client_base.h"
#include "esphome/components/esp32_ble_tracker/esp32_ble_tracker.h"
#include "esphome/core/component.h"
#include "esphome/core/preferences.h"

#include <deque>
#include <functional>
#include <string>
#include <vector>

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

// User-defined color preset table (issue #53). Presets live in
// NVS so they survive bridge reboots and are addressable by HA
// automations via the color_preset_recall service. The hex
// fields are stored alongside the (start_byte, wait_ms) recipe
// so HA / the JS card can render a preview swatch without re-
// querying the original RGB target.
constexpr size_t MAX_COLOR_PRESETS = 20;
struct ColorPreset {
  char     slug[16];   // automation-addressable id [a-z0-9_]
  char     name[32];   // human display label
  uint8_t  r, g, b;    // hex preview color
  uint8_t  start_byte; // pool_scrub recipe — fixture byte
  uint32_t wait_ms;    // pool_scrub recipe — Lock delay
};
struct ColorPresetStore {
  uint32_t    magic;   // schema version sentinel
  uint32_t    count;
  ColorPreset entries[MAX_COLOR_PRESETS];
};
constexpr uint32_t COLOR_PRESET_MAGIC = 0xC050E751;

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

  // Public API — used by YAML lambdas and the light entity in #11.
  void send_effect_byte(uint8_t byte_value);

  // Phase 4a probe escape hatch: write an arbitrary byte sequence
  // to the command characteristic, bypassing the single-byte queue.
  // Intended only for the RGB-experiment workflow (multi-byte
  // writes to test whether the controller accepts parameterised
  // commands). Drops the request if the link is not ready or a
  // previous write is still in flight; logs the byte sequence at
  // INFO level so probe runs are reproducible from the log.
  void probe_write_raw(const std::vector<uint8_t> &bytes);

  // Phase 4b show-scrub picker. Result of looking up a target RGB
  // in the embedded calibration LUT. See show_color_lut.h.
  struct PickRecipe {
    uint8_t  start_byte;     // byte to send to start the show or solid
    uint32_t wait_ms;        // delay before sending Lock; 0 for solids
    bool     is_solid;       // true = no Lock needed (deterministic)
    uint8_t  r, g, b;        // observed RGB at the matched sample
    float    distance;       // Euclidean RGB distance to target
    const char *name;        // human-readable show / solid name
  };

  // Look up the best (start_byte, wait_ms) for a target RGB. Solids
  // get a `solid_preference_bias` distance bonus (subtracted from
  // their distance) to favor deterministic single-byte commands when
  // results are similar. lock_comp_ms is subtracted from wait_ms
  // to compensate for the Lock byte's settling latency. Both default
  // to the empirically-tuned values from docs/RGB_EXPERIMENT.md.
  PickRecipe find_recipe(uint8_t r, uint8_t g, uint8_t b,
                         float solid_preference_bias = 30.0f,
                         uint32_t lock_comp_ms = 700) const;

  // Phase 4b: drive the fixture to display a target observed RGB.
  // Calls find_recipe() then dispatches: send the start byte, and
  // (for shows) schedule a Lock send at wait_ms. Returns the
  // matched recipe so callers can read back the LUT-resolved RGB
  // (used by the light entity to republish the actual displayed
  // color on the HA side, since the user's target may not be
  // exactly reachable by the LUT).
  PickRecipe pick_color(uint8_t r, uint8_t g, uint8_t b);

  bool is_ready() const { return this->cccd_armed_; }
  optional<uint8_t> last_echoed_byte() const { return this->last_echoed_; }

  // Most recent recipe returned by pick_color(). The card reads
  // this to save user presets directly as (start_byte, wait_ms)
  // pairs that reproduce the exact color the user picked, rather
  // than re-running the LUT search from a stored RGB. See #53.
  optional<PickRecipe> last_picked_recipe() const {
    return this->last_picked_recipe_;
  }

  // ─── Color preset table (NVS-backed, addressable by HA
  // automations via the color_preset_* services) ──────────────

  // Save (or update by slug). Returns false if the slot table is
  // full or the slug is not a valid identifier.
  bool color_preset_save(const std::string &slug,
                         const std::string &name,
                         uint8_t r, uint8_t g, uint8_t b,
                         uint8_t start_byte, uint32_t wait_ms);

  // Look up by slug; if found, dispatch the recipe (start_byte
  // → set_timeout(wait_ms) → Lock byte). Returns false if not
  // found or BLE not ready.
  bool color_preset_recall(const std::string &slug);

  // Remove from NVS. Returns false if not found.
  bool color_preset_delete(const std::string &slug);

  // Serialize all presets to a JSON array string for the
  // pool_color_presets text_sensor. Format:
  //   [{"slug":"...","name":"...","hex":"#rrggbb",
  //     "start_byte":N,"wait_ms":N}, ...]
  std::string color_presets_json() const;

  // Most recent "preset" byte sent — one of the 12 visible effects
  // (0x01..0x0c). Used by the light entity to decide what to send
  // when HA requests ON without a selected effect. Not updated for
  // Standby (0x00), Lock (0x0D), or Return (0x0E) since those don't
  // correspond to a steady displayed color.
  optional<uint8_t> last_preset_byte() const { return this->last_preset_byte_; }

  // True if the most recent display-changing byte was Return
  // (0x0e). Lock (0x0d) preserves the flag because it doesn't
  // change displayed color. Used by the light entity's
  // write_state to short-circuit the "fall through to last_preset"
  // path after a Return — without this, an HA-side
  // light.turn_on(effect:None) called for state-mirroring purposes
  // would re-fire the prior preset and stomp the locked color the
  // fixture is now showing.
  bool was_last_send_return() const {
    return this->last_send_was_return_;
  }

  // Watchdog / diagnostic surface for the HA binary_sensor +
  // text_sensor wired in YAML. `connected()` is inherited from
  // BLEClientBase (true once ESTABLISHED). `last_error()` returns
  // the most recent human-readable BLE error, empty when clean.
  const std::string &last_error() const { return this->last_error_; }

  // Diagnostic surface for #13 entities. RSSI is polled every
  // ~30 s while connected (0 when unknown). last_command_name()
  // formats the most recent sent byte as "name (0xNN)" — empty
  // before any byte has been sent this session. Counters are
  // monotonic within a boot session.
  int8_t last_rssi() const { return this->last_rssi_; }
  const std::string &last_command_name() const {
    return this->last_command_name_;
  }
  uint32_t total_commands() const { return this->total_commands_; }
  uint32_t total_errors() const { return this->total_errors_; }

  // GAP events land here so we can pick up RSSI read results.
  // Chains to BLEClientBase's handler for everything else.
  void gap_event_handler(esp_gap_ble_cb_event_t event,
                         esp_ble_gap_cb_param_t *param) override;

  // Subscribe to every indication echo from the controller. Invoked
  // from the BLE stack context; downstream code should treat the
  // callback as best-effort and avoid long-running work inside it.
  void add_on_echo_callback(std::function<void(uint8_t)> &&cb) {
    this->on_echo_callbacks_.push_back(std::move(cb));
  }

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

  // Compute the retry delay after the N-th consecutive failure.
  // Exponential-ish table: 1/2/5/15/30 s, capped at 30 s.
  static uint32_t backoff_ms_for_(uint32_t consecutive_failures);

  // Record a failure (timeout, bad GATT status, early disconnect)
  // and arm the next reconnect window. May trigger App.safe_reboot()
  // as a last-resort stack reset after many failures.
  void note_failure_(const char *reason, int code);

  // Called from the OPEN_EVT success path. Resets the failure
  // counter and arms diagnostic state.
  void note_connect_success_();

  uint64_t mac_override_{0};
  bool write_in_flight_{false};
  std::deque<uint8_t> pending_writes_;
  optional<uint8_t> last_echoed_;
  optional<uint8_t> last_queued_byte_;
  uint32_t last_queued_at_ms_{0};
  optional<uint8_t> last_preset_byte_;
  optional<PickRecipe> last_picked_recipe_;
  bool last_send_was_return_{false};

  // Color preset NVS storage (#53). Loaded once at setup(),
  // re-saved after every save/delete service call.
  void load_color_presets_();
  void save_color_presets_();
  ColorPresetStore preset_store_{};
  ESPPreferenceObject preset_pref_;
  std::vector<std::function<void(uint8_t)>> on_echo_callbacks_;

  // Watchdog state — see PROTOCOL.md §Auto-reconnect (#12) for the
  // backoff table + reboot policy.
  uint32_t consecutive_failures_{0};
  uint32_t next_connect_at_ms_{0};
  uint32_t last_connect_success_at_ms_{0};
  uint32_t last_reboot_request_at_ms_{0};
  std::string last_error_;

  // Diagnostic counters + last-seen values for #13 entities.
  // RSSI is 0 until the first READ_RSSI_COMPLETE lands; counters
  // reset on reboot (documented in SOAK_TEST.md).
  int8_t last_rssi_{0};
  uint32_t next_rssi_poll_at_ms_{0};
  std::string last_command_name_;
  uint32_t total_commands_{0};
  uint32_t total_errors_{0};
};

}  // namespace colorsplash_xg
}  // namespace esphome

#endif  // USE_ESP32
