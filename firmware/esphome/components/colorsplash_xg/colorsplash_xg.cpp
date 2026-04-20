#include "colorsplash_xg.h"

#ifdef USE_ESP32

#include "esphome/components/esp32_ble_client/ble_characteristic.h"
#include "esphome/components/esp32_ble_client/ble_descriptor.h"
#include "esphome/core/log.h"

namespace esphome {
namespace colorsplash_xg {

static const char *const TAG = "colorsplash_xg";

void ColorSplashXG::setup() {
  // auto_connect_=true tells the tracker to drive us into CONNECTING
  // once parse_device() claims a match and returns true.
  this->set_auto_connect(true);
  BLEClientBase::setup();
  ESP_LOGCONFIG(TAG,
                "colorsplash_xg: scanning for '%s' advertiser%s",
                CONTROLLER_LOCAL_NAME,
                this->mac_override_ ? " (MAC override active)" : "");
}

void ColorSplashXG::loop() {
  BLEClientBase::loop();
  this->try_drain_pending_();
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
        for (auto &cb : this->on_echo_callbacks_)
          cb(echo);
      }
      break;
    }
    case ESP_GATTC_DISCONNECT_EVT: {
      this->cccd_armed_ = false;
      this->write_in_flight_ = false;
      this->cmd_char_handle_ = 0;
      this->cmd_cccd_handle_ = 0;
      // The tracker will start scanning again — parse_device() will
      // pick the peripheral back up.
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
  const char *name = decode_byte(byte_value);
  ESP_LOGI(TAG, "sent byte 0x%02x (%s)",
           byte_value, name ? name : "raw");
}

}  // namespace colorsplash_xg
}  // namespace esphome

#endif  // USE_ESP32
