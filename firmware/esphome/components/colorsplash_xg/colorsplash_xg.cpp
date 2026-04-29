#include "colorsplash_xg.h"

#ifdef USE_ESP32

#include "esphome/components/esp32_ble_client/ble_characteristic.h"
#include "esphome/components/esp32_ble_client/ble_descriptor.h"
#include "esphome/components/light/light_state.h"
#include "esphome/core/application.h"
#include "esphome/core/log.h"

#include <cstdio>
#include <cstring>
#include <cmath>

#include "show_color_lut.h"

namespace esphome {
namespace colorsplash_xg {

static const char *const TAG = "colorsplash_xg";

// Watchdog constants — see PROTOCOL.md §Auto-reconnect (#12).
constexpr uint32_t kMaxFailuresBeforeReboot = 20;
constexpr uint32_t kMinRebootIntervalMs = 5 * 60 * 1000;  // 5 minutes
// How often to ask the ESP-IDF controller for the link-layer RSSI
// of our connection. 30 s is plenty; RSSI shifts slowly and this
// value feeds a diagnostic sensor, not a control loop.
constexpr uint32_t kRssiPollIntervalMs = 30 * 1000;
// Disconnects within this window of a successful connect count as
// a connect failure (the peer dropped us during setup). Outside
// this window, a disconnect is just "we used to be connected, now
// we're not" — no need to count against the backoff.
constexpr uint32_t kEarlyDisconnectWindowMs = 5000;

uint32_t ColorSplashXG::backoff_ms_for_(uint32_t n) {
  constexpr uint32_t kTable[] = {1000, 2000, 5000, 15000, 30000};
  if (n == 0) return 0;
  return (n - 1 < 5) ? kTable[n - 1] : 30000;
}

void ColorSplashXG::note_failure_(const char *reason, int code) {
  this->consecutive_failures_++;
  this->total_errors_++;
  char buf[80];
  std::snprintf(buf, sizeof(buf), "%s (code=%d) after %u attempts",
                reason, code, this->consecutive_failures_);
  this->last_error_ = buf;

  const uint32_t now = millis();
  const uint32_t delay_ms = backoff_ms_for_(this->consecutive_failures_);
  this->next_connect_at_ms_ = now + delay_ms;
  ESP_LOGW(TAG,
           "BLE failure #%u: %s — backing off %u ms",
           this->consecutive_failures_, reason, delay_ms);

  // Last-resort: if we've failed too many times, reboot to reset
  // the BLE stack. Guarded against rapid reboot loops by a minimum
  // inter-reboot interval — if we've rebooted within the last 5
  // minutes, just keep backing off and hoping.
  if (this->consecutive_failures_ >= kMaxFailuresBeforeReboot &&
      now - this->last_reboot_request_at_ms_ > kMinRebootIntervalMs) {
    ESP_LOGE(TAG,
             "BLE wedged after %u consecutive failures — rebooting "
             "for stack reset",
             this->consecutive_failures_);
    this->last_reboot_request_at_ms_ = now;
    this->last_error_ = "rebooting after repeated BLE failures";
    App.safe_reboot();
  }
}

void ColorSplashXG::note_connect_success_() {
  if (this->consecutive_failures_ > 0) {
    ESP_LOGI(TAG,
             "connected after %u prior failures — resetting backoff",
             this->consecutive_failures_);
  }
  this->consecutive_failures_ = 0;
  this->next_connect_at_ms_ = 0;
  this->last_connect_success_at_ms_ = millis();
  this->last_error_.clear();
}

void ColorSplashXG::setup() {
  // auto_connect_=true tells the tracker to drive us into CONNECTING
  // once parse_device() claims a match and returns true.
  this->set_auto_connect(true);
  BLEClientBase::setup();
  ESP_LOGCONFIG(TAG,
                "colorsplash_xg: scanning for '%s' advertiser%s",
                CONTROLLER_LOCAL_NAME,
                this->mac_override_ ? " (MAC override active)" : "");
  this->load_color_presets_();
}

void ColorSplashXG::loop() {
  BLEClientBase::loop();
  this->try_drain_pending_();

  // Periodically ask the controller for the link-layer RSSI of
  // our connection. ESP-IDF replies asynchronously via a GAP
  // event (ESP_GAP_BLE_READ_RSSI_COMPLETE_EVT) which lands in
  // gap_event_handler() below.
  const uint32_t now = millis();
  if (this->connected() && now >= this->next_rssi_poll_at_ms_) {
    this->next_rssi_poll_at_ms_ = now + kRssiPollIntervalMs;
    esp_err_t err = esp_ble_gap_read_rssi(this->remote_bda_);
    if (err != ESP_OK) {
      ESP_LOGD(TAG, "esp_ble_gap_read_rssi failed err=%d", err);
    }
  }
}

void ColorSplashXG::gap_event_handler(esp_gap_ble_cb_event_t event,
                                      esp_ble_gap_cb_param_t *param) {
  // Chain to the base so it sees the scan / connection events it
  // relies on — then layer our RSSI hook on top.
  BLEClientBase::gap_event_handler(event, param);
  if (event == ESP_GAP_BLE_READ_RSSI_COMPLETE_EVT) {
    if (param->read_rssi_cmpl.status == ESP_BT_STATUS_SUCCESS) {
      this->last_rssi_ = param->read_rssi_cmpl.rssi;
      ESP_LOGD(TAG, "rssi update: %d dBm", this->last_rssi_);
    } else {
      ESP_LOGD(TAG, "rssi read status=%d",
               param->read_rssi_cmpl.status);
    }
  }
}

void ColorSplashXG::dump_config() {
  ESP_LOGCONFIG(TAG, "ColorSplash XG:");
  ESP_LOGCONFIG(TAG, "  Target local name: %s", CONTROLLER_LOCAL_NAME);
  if (this->mac_override_ != 0) {
    ESP_LOGCONFIG(TAG, "  MAC override: %s", this->address_str());
  }
  ESP_LOGCONFIG(TAG, "  Connection state: %s",
                espbt::client_state_to_string(this->state()));
  ESP_LOGCONFIG(TAG, "  CCCD armed:       %s",
                YESNO(this->cccd_armed_));
  if (this->last_echoed_.has_value()) {
    const char *name = decode_byte(*this->last_echoed_);
    ESP_LOGCONFIG(TAG, "  Last echo byte:   0x%02x (%s)",
                  *this->last_echoed_,
                  name ? name : "unrecognized");
  }
  BLEClientBase::dump_config();
}

bool ColorSplashXG::parse_device(const espbt::ESPBTDevice &device) {
  // Only act while we're actively looking for the peer.
  if (this->state() != espbt::ClientState::IDLE)
    return false;

  // Respect the backoff window. If a previous attempt failed, we
  // deliberately ignore advertisements until the computed retry
  // time arrives — this gives the peer and the stack time to
  // settle instead of hammering esp_ble_gattc_open.
  if (millis() < this->next_connect_at_ms_)
    return false;

  // MAC override wins if set; otherwise match on advertised local
  // name. The controller's advertising payload uniquely identifies
  // itself as "BGScripr" (Silicon Labs BGScript runtime).
  const bool match_mac =
      this->mac_override_ != 0 &&
      device.address_uint64() == this->mac_override_;
  const bool match_name =
      this->mac_override_ == 0 &&
      device.get_name() == CONTROLLER_LOCAL_NAME;

  if (!match_mac && !match_name)
    return false;

  ESP_LOGI(TAG,
           "found ColorSplash XG controller at %s (rssi=%d)",
           device.address_str().c_str(),
           device.get_rssi());

  // Set the peer address so BLEClientBase::connect() can open the
  // link, then transition to DISCOVERED — the tracker loop will call
  // connect() on us.
  this->set_address(device.address_uint64());
  this->remote_addr_type_ = device.get_address_type();
  this->set_state(espbt::ClientState::DISCOVERED);
  return true;
}

bool ColorSplashXG::gattc_event_handler(esp_gattc_cb_event_t event,
                                        esp_gatt_if_t gattc_if,
                                        esp_ble_gattc_cb_param_t *param) {
  // Let the base class handle its standard lifecycle first — this
  // populates services_ on SEARCH_CMPL, drives state machine, etc.
  if (!BLEClientBase::gattc_event_handler(event, gattc_if, param))
    return false;

  switch (event) {
    case ESP_GATTC_SEARCH_CMPL_EVT: {
      auto service_uuid = espbt::ESPBTUUID::from_raw(SERVICE_UUID_STR);
      auto char_uuid = espbt::ESPBTUUID::from_raw(COMMAND_CHAR_UUID_STR);
      auto *chr = this->get_characteristic(service_uuid, char_uuid);
      if (chr == nullptr) {
        ESP_LOGE(TAG,
                 "command characteristic %s not found on peer — "
                 "not a ColorSplash XG controller?",
                 COMMAND_CHAR_UUID_STR);
        this->disconnect();
        break;
      }
      this->cmd_char_handle_ = chr->handle;
      auto *cccd = chr->get_descriptor(CCCD_UUID_U16);
      if (cccd == nullptr) {
        ESP_LOGE(TAG,
                 "CCCD descriptor not found on command characteristic");
        this->disconnect();
        break;
      }
      this->cmd_cccd_handle_ = cccd->handle;
      ESP_LOGD(TAG,
               "char handle=0x%04x cccd handle=0x%04x",
               this->cmd_char_handle_, this->cmd_cccd_handle_);
      // Without this the ESP-IDF stack drops incoming
      // Handle Value Indications before they reach us. Writing 0x0002
      // to the CCCD enables indications on the peer, but this call is
      // what routes them into our gattc_event_handler.
      esp_err_t reg_err = esp_ble_gattc_register_for_notify(
          this->get_gattc_if(), this->get_remote_bda(),
          this->cmd_char_handle_);
      if (reg_err != ESP_OK) {
        ESP_LOGE(TAG,
                 "esp_ble_gattc_register_for_notify failed err=%d",
                 reg_err);
      }
      this->arm_cccd_();
      break;
    }
    case ESP_GATTC_WRITE_DESCR_EVT: {
      // The base class already logged the descriptor write result.
      // If it was our CCCD subscribe, we're now armed.
      if (param->write.handle == this->cmd_cccd_handle_ &&
          param->write.status == ESP_GATT_OK) {
        this->cccd_armed_ = true;
        ESP_LOGI(TAG, "indications enabled — ready to drive fixture");
        // Mark fully established so the tracker knows setup is done.
        this->set_state(espbt::ClientState::ESTABLISHED);
        this->try_drain_pending_();
      }
      break;
    }
    case ESP_GATTC_WRITE_CHAR_EVT: {
      if (param->write.handle == this->cmd_char_handle_) {
        // ATT Write Response received — command was accepted by the
        // peer. We drain the queue on this event rather than on the
        // indication echo: the controller always echoes what we wrote
        // (per PROTOCOL.md §Controller-to-central indications), so
        // the echo carries no new information for routing our next
        // write. last_echoed_ is still updated from NOTIFY_EVT below
        // for callers that want to observe fixture state.
        if (param->write.status != ESP_GATT_OK) {
          ESP_LOGW(TAG, "write failed status=%d", param->write.status);
        }
        this->write_in_flight_ = false;
        this->try_drain_pending_();
      }
      break;
    }
    case ESP_GATTC_NOTIFY_EVT: {
      // esp-idf delivers both notify and indicate through the same
      // event. The controller only uses indications — no notifies —
      // so we don't filter on param->notify.is_notify.
      if (param->notify.handle == this->cmd_char_handle_ &&
          param->notify.value_len >= 1) {
        uint8_t echo = param->notify.value[0];
        this->last_echoed_ = echo;
        const char *name = decode_byte(echo);
        ESP_LOGI(TAG,
                 "indication echo 0x%02x (%s)",
                 echo,
                 name ? name : "unrecognized opcode");
      }
      break;
    }
    case ESP_GATTC_OPEN_EVT: {
      // The connect attempt resolved. Either we made it (ESP_GATT_OK
      // = session starting), or the open was rejected / timed out.
      // Either way, this is where we learn "did this attempt work?".
      if (param->open.status == ESP_GATT_OK) {
        this->note_connect_success_();
      } else {
        this->note_failure_("open failed", param->open.status);
      }
      break;
    }
    case ESP_GATTC_DISCONNECT_EVT: {
      this->cccd_armed_ = false;
      this->write_in_flight_ = false;
      this->cmd_char_handle_ = 0;
      this->cmd_cccd_handle_ = 0;
      // "No signal" beats a stale RSSI reading when disconnected.
      this->last_rssi_ = 0;
      this->next_rssi_poll_at_ms_ = 0;
      // An early disconnect (within kEarlyDisconnectWindowMs of a
      // successful connect) means the peer dropped us during setup
      // — count that as a connect failure so backoff kicks in.
      // Disconnects after a long successful session are ignored
      // here: the scanner will re-match via parse_device() with no
      // delay, matching the happy-path reconnect we already had.
      const uint32_t now = millis();
      if (this->last_connect_success_at_ms_ != 0 &&
          now - this->last_connect_success_at_ms_ <
              kEarlyDisconnectWindowMs) {
        this->note_failure_("early disconnect", param->disconnect.reason);
      }
      // The tracker will start scanning again — parse_device() will
      // pick the peripheral back up once the backoff window closes.
      break;
    }
    default:
      break;
  }
  return true;
}

void ColorSplashXG::arm_cccd_() {
  if (this->cmd_cccd_handle_ == 0)
    return;
  uint16_t value = CCCD_INDICATION_ENABLE;
  esp_err_t err = esp_ble_gattc_write_char_descr(
      this->get_gattc_if(), this->get_conn_id(),
      this->cmd_cccd_handle_, sizeof(value),
      reinterpret_cast<uint8_t *>(&value), ESP_GATT_WRITE_TYPE_RSP,
      ESP_GATT_AUTH_REQ_NONE);
  if (err != ESP_OK) {
    ESP_LOGE(TAG,
             "esp_ble_gattc_write_char_descr failed err=%d — "
             "indications will not work",
             err);
  }
}

void ColorSplashXG::send_effect_byte(uint8_t byte_value) {
  const char *name = decode_byte(byte_value);

  // Drop a same-byte re-request that arrives within 500 ms of the
  // last queued one. The common cause: both effect.start() and
  // write_state() fire on a single turn_on, both resolving to the
  // same byte. Without this, we'd double-send on every effect pick.
  const uint32_t now = millis();
  if (this->last_queued_byte_.has_value() &&
      *this->last_queued_byte_ == byte_value &&
      now - this->last_queued_at_ms_ < 500) {
    ESP_LOGD(TAG,
             "dedup: skipping 0x%02x (%s) — same byte <500 ms ago",
             byte_value, name ? name : "raw");
    return;
  }

  ESP_LOGD(TAG,
           "queueing byte 0x%02x (%s)",
           byte_value, name ? name : "raw");
  // Cap the queue so a disconnected fixture can't cause unbounded
  // growth. A depth of 4 covers any realistic burst from HA.
  constexpr size_t kMaxQueueDepth = 4;
  if (this->pending_writes_.size() >= kMaxQueueDepth) {
    ESP_LOGW(TAG,
             "pending queue full (depth=%u), dropping oldest byte",
             static_cast<unsigned>(this->pending_writes_.size()));
    this->pending_writes_.pop_front();
  }
  this->pending_writes_.push_back(byte_value);
  this->last_queued_byte_ = byte_value;
  this->last_queued_at_ms_ = now;
  // Track the most recent visible preset so the light entity can
  // resume it on a bare turn_on. Preset bytes are 0x01..0x0c — the
  // 5 solids + 7 shows. Standby / Lock / Return don't count.
  if (byte_value >= 0x01 && byte_value <= 0x0c) {
    this->last_preset_byte_ = byte_value;
  }
  // Track whether the most recent display-changing byte was Return.
  // Used by the light entity's write_state to skip the
  // last_preset replay after a Return — see the colorsplash_light
  // implementation. Lock (0x0d) preserves the flag because Lock
  // doesn't change what's currently displayed.
  if (byte_value == 0x0e) {
    this->last_send_was_return_ = true;
  } else if (byte_value != 0x0d) {
    this->last_send_was_return_ = false;
  }
  this->try_drain_pending_();
}

void ColorSplashXG::try_drain_pending_() {
  if (!this->cccd_armed_)
    return;
  if (this->write_in_flight_)
    return;
  if (this->pending_writes_.empty())
    return;

  uint8_t byte_value = this->pending_writes_.front();
  this->pending_writes_.pop_front();

  esp_err_t err = esp_ble_gattc_write_char(
      this->get_gattc_if(), this->get_conn_id(),
      this->cmd_char_handle_, 1, &byte_value,
      ESP_GATT_WRITE_TYPE_RSP, ESP_GATT_AUTH_REQ_NONE);
  if (err != ESP_OK) {
    ESP_LOGE(TAG,
             "esp_ble_gattc_write_char(0x%02x) failed err=%d",
             byte_value, err);
    return;
  }
  this->write_in_flight_ = true;
  this->total_commands_++;
  const char *name = decode_byte(byte_value);
  char formatted[48];
  std::snprintf(formatted, sizeof(formatted), "%s (0x%02x)",
                name ? name : "raw", byte_value);
  this->last_command_name_ = formatted;
  ESP_LOGI(TAG, "sent byte 0x%02x (%s)",
           byte_value, name ? name : "raw");
}

// Phase 4b show-scrub picker. Searches the embedded LUT for the
// (start_byte, wait_ms) whose observed RGB is closest to the target,
// preferring solids when distances are similar.
ColorSplashXG::PickRecipe ColorSplashXG::find_recipe(
    uint8_t r, uint8_t g, uint8_t b,
    float solid_preference_bias,
    uint32_t lock_comp_ms) const {
  // Solid name lookup keyed by start byte. Order matches generate_show_lut.py.
  static const char *const SOLID_NAMES_BY_BYTE[] = {
      // Sparse — only the 5 solid bytes are populated; others are
      // returned as nullptr so the lookup falls through to "unknown".
      // Indexed by start_byte (1 to 0x0e covers all show + solid + control).
      nullptr,                                  // 0x00 = Standby
      "Peruvian Paradise", "Super Nova",        // 0x01, 0x02
      "Northern Lights", "Tidal Wave",          // 0x03, 0x04
      "Patriot Dream", "Desert Skies",          // 0x05, 0x06
      "Nova",                                   // 0x07
      "Parisian Blue", "New Zealand Green",     // 0x08, 0x09
      "Brazilian Red", "Arctic White",          // 0x0a, 0x0b
      "Miami Pink",                             // 0x0c
      "Lock", "Return",                         // 0x0d, 0x0e
  };
  auto name_for = [&](uint8_t byte) -> const char * {
    if (byte < sizeof(SOLID_NAMES_BY_BYTE) / sizeof(*SOLID_NAMES_BY_BYTE)) {
      const char *n = SOLID_NAMES_BY_BYTE[byte];
      if (n != nullptr) return n;
    }
    return "(unknown)";
  };

  auto sq_dist = [&](uint8_t sr, uint8_t sg, uint8_t sb) -> float {
    const float dr = (float) r - (float) sr;
    const float dg = (float) g - (float) sg;
    const float db = (float) b - (float) sb;
    return dr * dr + dg * dg + db * db;
  };

  // Best across solids (with bias).
  float best_eff = 1e30f;
  PickRecipe best{};
  bool found = false;
  for (size_t i = 0; i < SOLID_LUT_LEN; i++) {
    const auto &s = SOLID_LUT[i];
    float d = std::sqrt(sq_dist(s.r, s.g, s.b));
    float eff = d - solid_preference_bias;
    if (eff < 0) eff = 0;
    if (eff < best_eff) {
      best_eff = eff;
      best = PickRecipe{
          .start_byte = s.start_byte,
          .wait_ms = 0,
          .is_solid = true,
          .r = s.r,
          .g = s.g,
          .b = s.b,
          .distance = d,
          .name = name_for(s.start_byte),
      };
      found = true;
    }
  }

  // Best across show samples (no bias).
  for (size_t i = 0; i < SHOW_LUT_LEN; i++) {
    const auto &s = SHOW_LUT[i];
    float d = std::sqrt(sq_dist(s.r, s.g, s.b));
    if (d < best_eff) {
      best_eff = d;
      // Apply lock compensation to the wait_ms.
      uint32_t wait = s.wait_ms;
      if (wait > lock_comp_ms) wait -= lock_comp_ms;
      else wait = 0;
      best = PickRecipe{
          .start_byte = s.start_byte,
          .wait_ms = wait,
          .is_solid = false,
          .r = s.r,
          .g = s.g,
          .b = s.b,
          .distance = d,
          .name = name_for(s.start_byte),
      };
      found = true;
    }
  }

  if (!found) {
    // Empty LUT — caller should ignore this; return a safe sentinel.
    best = PickRecipe{
        .start_byte = 0x00, .wait_ms = 0, .is_solid = true,
        .r = 0, .g = 0, .b = 0, .distance = 9999.0f,
        .name = "(empty LUT)",
    };
  }
  return best;
}

ColorSplashXG::PickRecipe ColorSplashXG::pick_color(
    uint8_t r, uint8_t g, uint8_t b) {
  PickRecipe rec = this->find_recipe(r, g, b);
  ESP_LOGI(TAG,
           "pick_color: target=(%u,%u,%u) → %s (0x%02x) "
           "%s wait_ms=%u observed=(%u,%u,%u) dist=%.1f",
           r, g, b, rec.name, rec.start_byte,
           rec.is_solid ? "(solid)" : "(show-scrub)",
           rec.wait_ms, rec.r, rec.g, rec.b, rec.distance);
  this->last_picked_recipe_ = rec;
  this->send_effect_byte(rec.start_byte);
  if (!rec.is_solid && rec.wait_ms > 0) {
    // Schedule the Lock byte after wait_ms. Use ESPHome's scheduler
    // so the wait is non-blocking.
    this->set_timeout("pick_lock", rec.wait_ms, [this]() {
      ESP_LOGI(TAG, "pick_color: firing Lock (0x0d)");
      this->send_effect_byte(0x0d);
    });
  }
  return rec;
}

// ─── Color preset table (issue #53) ────────────────────────────

namespace {
bool is_valid_preset_slug(const std::string &s) {
  if (s.empty() || s.size() >= sizeof(ColorPreset::slug)) return false;
  for (char c : s) {
    if (!((c >= 'a' && c <= 'z')
          || (c >= '0' && c <= '9')
          || c == '_'
          || c == '-')) {
      return false;
    }
  }
  return true;
}

bool is_valid_preset_name(const std::string &s) {
  if (s.empty() || s.size() >= sizeof(ColorPreset::name)) return false;
  for (char c : s) {
    // Printable ASCII excluding JSON-unsafe characters.
    if (c < 0x20 || c >= 0x7F) return false;
    if (c == '"' || c == '\\') return false;
  }
  return true;
}
}  // anonymous namespace

void ColorSplashXG::load_color_presets_() {
  this->preset_pref_ =
      global_preferences->make_preference<ColorPresetStore>(0xC9101753);
  if (this->preset_pref_.load(&this->preset_store_)
      && this->preset_store_.magic == COLOR_PRESET_MAGIC) {
    if (this->preset_store_.count > MAX_COLOR_PRESETS) {
      this->preset_store_.count = MAX_COLOR_PRESETS;
    }
    ESP_LOGI(TAG, "color_presets: loaded %u from NVS",
             (unsigned) this->preset_store_.count);
    return;
  }
  ESP_LOGI(TAG, "color_presets: initializing empty store "
                "(no NVS data or schema mismatch)");
  this->preset_store_.magic = COLOR_PRESET_MAGIC;
  this->preset_store_.count = 0;
  std::memset(this->preset_store_.entries, 0,
              sizeof(this->preset_store_.entries));
}

void ColorSplashXG::save_color_presets_() {
  this->preset_store_.magic = COLOR_PRESET_MAGIC;
  this->preset_pref_.save(&this->preset_store_);
  global_preferences->sync();
}

bool ColorSplashXG::color_preset_save(
    const std::string &slug, const std::string &name,
    uint8_t r, uint8_t g, uint8_t b,
    uint8_t start_byte, uint32_t wait_ms) {
  if (!is_valid_preset_slug(slug)) {
    ESP_LOGW(TAG, "color_preset_save: invalid slug '%s' "
                  "(allowed [a-z0-9_], up to %u chars)",
             slug.c_str(),
             (unsigned)(sizeof(ColorPreset::slug) - 1));
    return false;
  }
  if (!is_valid_preset_name(name)) {
    ESP_LOGW(TAG, "color_preset_save: invalid name '%s' "
                  "(printable ASCII only, no quotes/backslash, "
                  "up to %u chars)",
             name.c_str(),
             (unsigned)(sizeof(ColorPreset::name) - 1));
    return false;
  }

  // Find existing slot with this slug, or first empty slot.
  int slot_index = -1;
  for (size_t i = 0; i < this->preset_store_.count; i++) {
    if (std::strcmp(this->preset_store_.entries[i].slug,
                    slug.c_str()) == 0) {
      slot_index = (int) i;
      break;
    }
  }
  bool is_new = (slot_index < 0);
  if (is_new) {
    if (this->preset_store_.count >= MAX_COLOR_PRESETS) {
      ESP_LOGW(TAG, "color_preset_save: storage full (max %u)",
               (unsigned) MAX_COLOR_PRESETS);
      return false;
    }
    slot_index = (int) this->preset_store_.count;
    this->preset_store_.count++;
  }
  ColorPreset &slot = this->preset_store_.entries[slot_index];
  std::strncpy(slot.slug, slug.c_str(), sizeof(slot.slug) - 1);
  slot.slug[sizeof(slot.slug) - 1] = '\0';
  std::strncpy(slot.name, name.c_str(), sizeof(slot.name) - 1);
  slot.name[sizeof(slot.name) - 1] = '\0';
  slot.r = r;
  slot.g = g;
  slot.b = b;
  slot.start_byte = start_byte;
  slot.wait_ms = wait_ms;
  this->save_color_presets_();
  ESP_LOGI(TAG, "color_preset_save: %s slot=%d slug='%s' name='%s' "
                "rgb=#%02x%02x%02x start_byte=0x%02x wait_ms=%u",
           is_new ? "added" : "updated",
           slot_index, slug.c_str(), name.c_str(),
           r, g, b, start_byte, (unsigned) wait_ms);
  return true;
}

bool ColorSplashXG::color_preset_recall(const std::string &slug) {
  for (size_t i = 0; i < this->preset_store_.count; i++) {
    const ColorPreset &slot = this->preset_store_.entries[i];
    if (std::strcmp(slot.slug, slug.c_str()) == 0) {
      ESP_LOGI(TAG, "color_preset_recall: '%s' (%s) "
                    "start_byte=0x%02x wait_ms=%u",
               slot.slug, slot.name, slot.start_byte,
               (unsigned) slot.wait_ms);
      this->send_effect_byte(slot.start_byte);
      if (slot.wait_ms > 0) {
        const uint32_t wait_ms = slot.wait_ms;
        this->set_timeout("preset_lock", wait_ms, [this]() {
          this->send_effect_byte(0x0d);
        });
      }
      // Republish the saved RGB on the light entity so the JS
      // card's wheel cursor + bulb tint + RGB label reflect the
      // recalled color. Deferred ~50ms so it doesn't race the
      // BLE dispatch sequence above. Only runs if setup_state
      // captured the LightState pointer.
      //
      // Important: also force color_mode=RGB and state=on. In
      // write_state's republish path the LightCall machinery had
      // already set those before our lambda fires, but here we're
      // outside any LightCall — remote_values still carries
      // whatever the previous interaction left, which may be
      // ON_OFF mode (in which case publish_state omits rgb_color
      // from the pushed state and HA's attribute never updates).
      if (this->light_state_ != nullptr) {
        light::LightState *light = this->light_state_;
        const uint8_t pr = slot.r, pg = slot.g, pb = slot.b;
        ESP_LOGI(TAG, "preset_republish: scheduling rgb=(%u,%u,%u) "
                      "on LightState* %p",
                 pr, pg, pb, static_cast<const void *>(light));
        App.scheduler.set_timeout(light, "preset_republish_rgb",
            50, [light, pr, pg, pb]() {
          ESP_LOGI("colorsplash_xg",
                   "preset_republish: firing rgb=(%u,%u,%u)",
                   pr, pg, pb);
          light->remote_values.set_state(true);
          light->remote_values.set_color_mode(light::ColorMode::RGB);
          light->remote_values.set_red(pr / 255.0f);
          light->remote_values.set_green(pg / 255.0f);
          light->remote_values.set_blue(pb / 255.0f);
          light->publish_state();
        });
      } else {
        ESP_LOGW(TAG, "preset_republish: light_state_ is null, "
                      "UI will not auto-update");
      }
      return true;
    }
  }
  ESP_LOGW(TAG, "color_preset_recall: slug '%s' not found",
           slug.c_str());
  return false;
}

bool ColorSplashXG::color_preset_delete(const std::string &slug) {
  for (size_t i = 0; i < this->preset_store_.count; i++) {
    if (std::strcmp(this->preset_store_.entries[i].slug,
                    slug.c_str()) == 0) {
      // Shift remaining entries down to keep the active prefix
      // contiguous.
      for (size_t j = i; j + 1 < this->preset_store_.count; j++) {
        this->preset_store_.entries[j] =
            this->preset_store_.entries[j + 1];
      }
      this->preset_store_.count--;
      std::memset(&this->preset_store_.entries[this->preset_store_.count],
                  0, sizeof(ColorPreset));
      this->save_color_presets_();
      ESP_LOGI(TAG, "color_preset_delete: '%s'", slug.c_str());
      return true;
    }
  }
  ESP_LOGW(TAG, "color_preset_delete: slug '%s' not found",
           slug.c_str());
  return false;
}

std::string ColorSplashXG::preset_at_json(size_t idx) const {
  if (idx >= this->preset_store_.count) return std::string();
  const ColorPreset &slot = this->preset_store_.entries[idx];
  char buf[160];
  std::snprintf(buf, sizeof(buf),
                "{\"slug\":\"%s\",\"name\":\"%s\","
                "\"hex\":\"#%02x%02x%02x\","
                "\"start_byte\":%u,\"wait_ms\":%u}",
                slot.slug, slot.name,
                slot.r, slot.g, slot.b,
                (unsigned) slot.start_byte,
                (unsigned) slot.wait_ms);
  return std::string(buf);
}

}  // namespace colorsplash_xg
}  // namespace esphome

#endif  // USE_ESP32
