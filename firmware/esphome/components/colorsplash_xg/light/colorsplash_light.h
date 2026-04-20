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

struct SolidPreset {
  const char *name;
  uint8_t byte;
  float r;  // 0..1
  float g;
  float b;
};

class ColorSplashLightOutput : public light::LightOutput {
 public:
  light::LightTraits get_traits() override {
    light::LightTraits traits;
    // RGB + ON_OFF: HA's color picker drives the 5 solid presets
    // via nearest-neighbor snap; plain on/off still works.
    traits.set_supported_color_modes(
        {light::ColorMode::ON_OFF, light::ColorMode::RGB});
    return traits;
  }

  void write_state(light::LightState *state) override;

  void set_parent(ColorSplashXG *parent) { this->parent_ = parent; }

  // Called from Python codegen, once per solid color in SOLID_COLORS.
  // r, g, b arrive as uint8 0..255; we store as 0..1 floats to
  // match ESPHome's internal LightColorValues format.
  void register_solid(const char *name, uint8_t byte,
                      uint8_t r, uint8_t g, uint8_t b) {
    this->solids_.push_back(SolidPreset{
        name,
        byte,
        r / 255.0f,
        g / 255.0f,
        b / 255.0f,
    });
  }

 protected:
  // Return the solid preset byte whose RGB is closest to (r,g,b)
  // in plain Euclidean color space. Returns empty if the preset
  // table was never populated (should not happen after codegen).
  optional<uint8_t> nearest_solid_byte_(float r, float g, float b) const;

  ColorSplashXG *parent_{nullptr};
  std::vector<SolidPreset> solids_;
};

}  // namespace colorsplash_xg
}  // namespace esphome

#endif  // USE_ESP32
