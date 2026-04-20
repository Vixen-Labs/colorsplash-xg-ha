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
    traits.set_supported_color_modes({light::ColorMode::ON_OFF});
    return traits;
  }

  // Hooks called by the LightState at boot time. We use
  // setup_state() to build and attach the preset effects once
  // parent_ is guaranteed to be set (Python codegen sets it before
  // boot) and the LightState pointer is available.
  void setup_state(light::LightState *state) override;

  void write_state(light::LightState *state) override;

  void set_parent(ColorSplashXG *parent) { this->parent_ = parent; }

  // Called once per preset at codegen time. Names + bytes come from
  // the canonical Python list in light/__init__.py — the single
  // source of truth cross-verified by
  // tests/test_esphome_light_effects.py.
  void register_preset(const std::string &name, uint8_t byte) {
    this->presets_.emplace_back(name, byte);
  }

 protected:
  ColorSplashXG *parent_{nullptr};
  std::vector<std::pair<std::string, uint8_t>> presets_;
};

}  // namespace colorsplash_xg
}  // namespace esphome

#endif  // USE_ESP32
