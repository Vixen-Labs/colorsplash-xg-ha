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
  // HA asked for ON. An effect-select path (start()) has already
  // sent the corresponding byte. If the light is being turned on
  // with no effect active (e.g. after NVS restore of a bare ON
  // state), there's nothing sensible to send — the fixture stays
  // in whatever state it was last in, and the user can pick an
  // effect to refresh. We deliberately do not fire Return (0x0e)
  // here: that would replay a "last locked" state the user may not
  // expect.
}

}  // namespace colorsplash_xg
}  // namespace esphome

#endif  // USE_ESP32
