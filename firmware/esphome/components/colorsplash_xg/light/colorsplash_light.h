#pragma once

#ifdef USE_ESP32

#include "../colorsplash_xg.h"

#include "esphome/components/light/light_effect.h"
#include "esphome/components/light/light_output.h"
#include "esphome/components/light/light_state.h"
#include "esphome/core/component.h"

#include <string>
#include <utility>
#include <vector>

namespace esphome {
namespace colorsplash_xg {

// A single preset effect — "send one byte once on activation,
// nothing else." apply() is a no-op; the LightState's effect
// machinery keeps this effect flagged active until the user picks
// a different one or turns the light off.
//
// The `name` pointer passed to the LightEffect base must outlive
// this object — we rely on the ColorSplashLightOutput keeping its
// presets_ vector alive for the lifetime of the process.
class ColorSplashPresetEffect : public light::LightEffect {
 public:
  ColorSplashPresetEffect(const char *name, uint8_t byte,
                          ColorSplashXG *parent)
      : LightEffect(name), byte_(byte), parent_(parent) {}

  void start() override {
    this->parent_->send_effect_byte(this->byte_);
  }
  void apply() override {}

 protected:
  uint8_t byte_;
  ColorSplashXG *parent_;
};

class ColorSplashLightOutput : public light::LightOutput {
 public:
  light::LightTraits get_traits() override {
    light::LightTraits traits;
    // ON_OFF for the simple toggle / effect path. RGB is opt-in
    // (rgb_mode: true on the light: YAML config) — when enabled,
    // HA's standard light card exposes a color wheel that drives
    // the bridge's embedded show-scrub picker (Phase 4b). Default
    // off because the color gamut is constrained and the picker
    // is approximate (see issue #54). The fixture has no
    // brightness control, so we never advertise it.
    if (this->rgb_mode_) {
      traits.set_supported_color_modes({
          light::ColorMode::ON_OFF,
          light::ColorMode::RGB,
      });
    } else {
      traits.set_supported_color_modes({light::ColorMode::ON_OFF});
    }
    return traits;
  }

  void write_state(light::LightState *state) override;

  // Called once during light component init. Forward the
  // pointer to the parent so color_preset_recall() can republish
  // the recalled RGB on the light entity from outside the
  // write_state path.
  void setup_state(light::LightState *state) override;

  void set_parent(ColorSplashXG *parent) { this->parent_ = parent; }
  void set_rgb_mode(bool rgb_mode) { this->rgb_mode_ = rgb_mode; }

 protected:
  ColorSplashXG *parent_{nullptr};
  bool rgb_mode_{false};
};

}  // namespace colorsplash_xg
}  // namespace esphome

#endif  // USE_ESP32
