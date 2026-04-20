#include "colorsplash_light.h"

#ifdef USE_ESP32

#include "esphome/core/log.h"

#include <limits>

namespace esphome {
namespace colorsplash_xg {

static const char *const TAG = "colorsplash_xg.light";

optional<uint8_t> ColorSplashLightOutput::nearest_solid_byte_(
    float r, float g, float b) const {
  if (this->solids_.empty())
    return {};
  const SolidPreset *best = &this->solids_.front();
  float best_d2 = std::numeric_limits<float>::max();
  for (const auto &s : this->solids_) {
    const float dr = s.r - r;
    const float dg = s.g - g;
    const float db = s.b - b;
    const float d2 = dr * dr + dg * dg + db * db;
    if (d2 < best_d2) {
      best_d2 = d2;
      best = &s;
    }
  }
  return best->byte;
}

void ColorSplashLightOutput::write_state(light::LightState *state) {
  bool on;
  state->current_values_as_binary(&on);
  if (!on) {
    // HA asked for OFF → fixture goes into Standby.
    this->parent_->send_effect_byte(0x00);
    return;
  }

  // HA asked for ON. Three resolvers, in order:
  //
  // 1. A show effect (from SHOW_EFFECTS) is selected. Look up its
  //    byte by name. Handles NVS restore too — LightState restores
  //    the effect index without calling effect.start(), so the
  //    lookup here guarantees the fixture comes up correctly.
  //
  // 2. An RGB color-mode call. Snap to the nearest of the 5 solid
  //    presets by Euclidean distance in RGB space, send that byte.
  //    HA's color picker maps any user-selected color to one of
  //    our 5 solids this way.
  //
  // 3. Bare ON with no effect / no RGB pick (e.g. the user hit the
  //    toggle). Resume the most recent visible preset, or Arctic
  //    White as a neutral default. This matches the app's "light
  //    comes back on in the last state" behavior.

  if (state->get_current_effect_index() != 0) {
    auto name = state->get_effect_name();
    // StringRef isn't guaranteed null-terminated — pass the (base,
    // length) pair explicitly to encode_effect's string_view param.
    auto byte = encode_effect(std::string_view(name.c_str(), name.size()));
    if (byte.has_value()) {
      this->parent_->send_effect_byte(*byte);
      return;
    }
    ESP_LOGW(TAG,
             "unknown effect name '%.*s', falling through to color/default",
             static_cast<int>(name.size()), name.c_str());
  }

  if (state->current_values.get_color_mode() == light::ColorMode::RGB) {
    float r, g, b;
    state->current_values_as_rgb(&r, &g, &b);
    if (auto snapped = this->nearest_solid_byte_(r, g, b)) {
      this->parent_->send_effect_byte(*snapped);
      return;
    }
  }

  const auto last_preset = this->parent_->last_preset_byte();
  uint8_t byte_to_send = last_preset.value_or(0x0b);  // Arctic White
  this->parent_->send_effect_byte(byte_to_send);
}

}  // namespace colorsplash_xg
}  // namespace esphome

#endif  // USE_ESP32
