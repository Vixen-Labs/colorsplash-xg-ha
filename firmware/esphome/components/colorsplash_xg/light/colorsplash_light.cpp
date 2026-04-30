#include "colorsplash_light.h"

#ifdef USE_ESP32

#include "esphome/core/application.h"
#include "esphome/core/log.h"

#include <cmath>

namespace esphome {
namespace colorsplash_xg {

static const char *const TAG = "colorsplash_xg.light";

void ColorSplashLightOutput::setup_state(light::LightState *state) {
  ESP_LOGI(TAG, "setup_state: capturing LightState* %p for parent",
           static_cast<const void *>(state));
  if (this->parent_ != nullptr) {
    this->parent_->set_light_state(state);
  } else {
    ESP_LOGW(TAG, "setup_state: parent_ is null, can't forward");
  }
}

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
  //    from the dropdown want that effect, not whatever color
  //    happens to be on the wheel.
  //
  // 2. RGB color mode is active. Run the embedded picker
  //    (find_recipe + dispatch) — finds the closest reachable
  //    sample in the show LUT and either sends a single solid
  //    byte or starts a show + schedules a Lock at the matched
  //    offset. Phase 4b production path.
  //
  // 3. Bare ON (toggle, no effect, no color): resume the most
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
    auto rec = this->parent_->pick_color(r, g, b);

    // Republish the LUT-resolved RGB so HA reflects the color the
    // fixture actually displays, not the (often unreachable) target
    // the user picked. ESPHome's LightCall machinery sets
    // remote_values to the current_values target *after* this
    // write_state returns; deferring to a 50 ms timeout lets that
    // happen first, then we override with the resolved RGB.
    if (rec.r != r || rec.g != g || rec.b != b) {
      uint8_t pr = rec.r, pg = rec.g, pb = rec.b;
      App.scheduler.set_timeout(state, "publish_resolved_rgb", 50,
          [state, pr, pg, pb]() {
        state->remote_values.set_red(pr / 255.0f);
        state->remote_values.set_green(pg / 255.0f);
        state->remote_values.set_blue(pb / 255.0f);
        state->publish_state();
      });
    }
    return;
  }

  // Post-Return short-circuit: the fixture is currently showing
  // the color that was Locked previously, and the user just
  // tapped Return to recall it. A bare HA-side turn_on (e.g. from
  // the JS card calling light.turn_on(effect:None) right after
  // pressing the Return button so HA's light entity flips to
  // "on") would otherwise fall through below and re-fire
  // last_preset, stomping the locked color. Skip the resend in
  // that window. The flag clears the next time send_effect_byte
  // is called with any display-changing byte (a solid, show, or
  // Standby).
  if (this->parent_->was_last_send_return()) {
    ESP_LOGD(TAG,
             "post-Return turn_on: skipping last_preset replay "
             "to preserve the locked color");
    return;
  }

  // Post-user-preset short-circuit: the JS card fires
  // light.turn_on(effect:None) right after a color_preset_recall
  // so HA's effect attribute clears. That call lands here as a
  // bare ON; without this guard, last_preset_byte() (the recall's
  // start_byte) would re-fire and stomp the just-recalled preset
  // color. The flag clears via send_effect_byte the next time any
  // non-recall byte goes out.
  if (!this->parent_->last_recalled_slug().empty()) {
    ESP_LOGD(TAG,
             "post-recall turn_on: skipping last_preset replay "
             "to preserve the active user preset");
    return;
  }

  const auto last_preset = this->parent_->last_preset_byte();
  uint8_t byte_to_send = last_preset.value_or(0x0b);  // Arctic White
  this->parent_->send_effect_byte(byte_to_send);
}

}  // namespace colorsplash_xg
}  // namespace esphome

#endif  // USE_ESP32
