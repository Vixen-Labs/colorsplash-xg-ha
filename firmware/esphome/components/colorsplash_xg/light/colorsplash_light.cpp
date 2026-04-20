#include "colorsplash_light.h"

#ifdef USE_ESP32

#include "esphome/core/log.h"

namespace esphome {
namespace colorsplash_xg {

static const char *const TAG = "colorsplash_xg.light";

void ColorSplashLightOutput::write_state(light::LightState *state) {
  bool on;
  state->current_values_as_binary(&on);
  if (!on) {
    // HA asked for OFF → fixture goes into Standby.
    this->parent_->send_effect_byte(0x00);
    return;
  }

  // HA asked for ON. Two resolvers, in order:
  //
  // 1. A show effect is selected. Look up its byte by name. Also
  //    handles NVS restore — LightState restores the effect index
  //    without firing effect.start(), so doing the lookup here
  //    guarantees the fixture comes up in the expected state.
  //
  // 2. Bare ON (toggle, no effect): resume the most recent visible
  //    preset byte (either a solid pressed via button entity or
  //    the last show that ran). Falls back to Arctic White (0x0B)
  //    on a cold first-boot where no preset has been applied yet.

  if (state->get_current_effect_index() != 0) {
    auto name = state->get_effect_name();
    auto byte = encode_effect(std::string_view(name.c_str(), name.size()));
    if (byte.has_value()) {
      this->parent_->send_effect_byte(*byte);
      return;
    }
    ESP_LOGW(TAG,
             "unknown effect name '%.*s', falling through to default",
             static_cast<int>(name.size()), name.c_str());
  }

  const auto last_preset = this->parent_->last_preset_byte();
  uint8_t byte_to_send = last_preset.value_or(0x0b);  // Arctic White
  this->parent_->send_effect_byte(byte_to_send);
}

}  // namespace colorsplash_xg
}  // namespace esphome

#endif  // USE_ESP32
