#include "colorsplash_light.h"

#ifdef USE_ESP32

#include "esphome/core/log.h"

#include <cmath>

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

  // HA asked for ON. Three resolvers, in priority order:
  //
  // 1. A show effect is selected. Look up its byte by name. Also
  //    handles NVS restore — LightState restores the effect index
  //    without firing effect.start(), so doing the lookup here
  //    guarantees the fixture comes up in the expected state.
  //    Effect wins over RGB because users who pick a named effect
  //    from the dropdown want that effect, not whatever colour
  //    happens to be on the wheel.
  //
  // 2. RGB colour mode is active. Run the embedded picker
  //    (find_recipe + dispatch) — finds the closest reachable
  //    sample in the show LUT and either sends a single solid
  //    byte or starts a show + schedules a Lock at the matched
  //    offset. Phase 4b production path.
  //
  // 3. Bare ON (toggle, no effect, no colour): resume the most
  //    recent visible preset byte (either a solid pressed via
  //    button entity or the last show that ran). Falls back to
  //    Arctic White (0x0B) on a cold first-boot where no preset
  //    has been applied yet.

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

  if (this->rgb_mode_ &&
      state->current_values.get_color_mode() == light::ColorMode::RGB) {
    const auto &v = state->current_values;
    uint8_t r = (uint8_t) std::round(v.get_red() * 255.0f);
    uint8_t g = (uint8_t) std::round(v.get_green() * 255.0f);
    uint8_t b = (uint8_t) std::round(v.get_blue() * 255.0f);
    ESP_LOGI(TAG, "light RGB write: target=(%u,%u,%u) → pick_color",
             r, g, b);
    this->parent_->pick_color(r, g, b);
    return;
  }

  const auto last_preset = this->parent_->last_preset_byte();
  uint8_t byte_to_send = last_preset.value_or(0x0b);  // Arctic White
  this->parent_->send_effect_byte(byte_to_send);
}

}  // namespace colorsplash_xg
}  // namespace esphome

#endif  // USE_ESP32
