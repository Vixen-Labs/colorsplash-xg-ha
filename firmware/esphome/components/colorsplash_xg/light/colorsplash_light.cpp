#include "colorsplash_light.h"

#ifdef USE_ESP32

#include "esphome/core/log.h"

namespace esphome {
namespace colorsplash_xg {

static const char *const TAG = "colorsplash_xg.light";

void ColorSplashLightOutput::setup_state(light::LightState *state) {
  // LightState::add_effects only takes an initializer_list, so we
  // feed it one preset at a time. The effect holds a const char *
  // into presets_[i].first, so presets_ must stay alive for the
  // lifetime of the process — we do not clear it.
  for (auto &preset : this->presets_) {
    auto *fx = new ColorSplashPresetEffect(  // NOLINT
        preset.first.c_str(), preset.second, this->parent_);
    state->add_effects({fx});
  }
  ESP_LOGCONFIG(TAG, "registered %u preset effects",
                static_cast<unsigned>(this->presets_.size()));
}

void ColorSplashLightOutput::write_state(light::LightState *state) {
  bool on;
  state->current_values_as_binary(&on);
  if (!on) {
    // HA asked for OFF → fixture goes into Standby.
    this->parent_->send_effect_byte(0x00);
    return;
  }

  // HA asked for ON. Figure out what byte represents the requested
  // state:
  //
  // 1. If HA has an effect selected, look it up by name and send
  //    that byte. Also handles the NVS-restore path — LightState
  //    restores the effect index without calling effect.start(),
  //    so doing the lookup here guarantees the fixture actually
  //    comes up in the expected state.
  // 2. Otherwise (effect == None), resume the most recent visible
  //    preset we've seen. This covers the "toggle off, toggle on"
  //    flow where the user expects the fixture to return to what
  //    it was last showing.
  // 3. Otherwise, pick Arctic White as a neutral default — better
  //    than silently doing nothing.

  if (state->get_current_effect_index() != 0) {
    auto name = state->get_effect_name();
    // StringRef isn't guaranteed null-terminated — pass the (base,
    // length) pair explicitly to encode_effect's string_view param.
    auto byte = encode_effect(std::string_view(name.c_str(), name.size()));
    if (byte.has_value()) {
      this->parent_->send_effect_byte(*byte);
      return;
    }
    // Effect name didn't resolve — fall through to the default
    // path. This should never happen for effects we registered.
    ESP_LOGW(TAG,
             "unknown effect name '%.*s', falling back to default",
             static_cast<int>(name.size()), name.c_str());
  }

  const auto last_preset = this->parent_->last_preset_byte();
  uint8_t byte_to_send = last_preset.value_or(0x0b);  // Arctic White
  this->parent_->send_effect_byte(byte_to_send);
}

}  // namespace colorsplash_xg
}  // namespace esphome

#endif  // USE_ESP32
