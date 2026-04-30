#pragma once

#include "esphome/components/select/select.h"
#include "esphome/core/component.h"

#include <string>
#include <vector>

namespace esphome {
namespace colorsplash_xg {

class ColorSplashXG;  // forward-declared to avoid header cycle

// Sentinel value published when no user preset is currently
// active (after Standby, a hardware effect, or a manual RGB
// pick). Must match select/__init__.py's NONE_OPTION.
inline constexpr const char *kSelectNoneOption = "(none)";

class ColorSplashSelect : public select::Select,
                          public PollingComponent {
 public:
  ColorSplashSelect() : PollingComponent(1000) {}
  void setup() override;
  void update() override;     // poll for option-list / state drift
  void dump_config() override;
  void set_parent(ColorSplashXG *parent) { this->parent_ = parent; }

 protected:
  // HA called select.select_option(value). Reach into the parent
  // and recall the preset by slug; publish_state on success.
  void control(const std::string &value) override;

  // Read the parent's preset table; if it differs from the
  // current options list, push the new list via traits.
  void refresh_options_();

  // Read the parent's last_recalled_slug() and publish_state if
  // it differs from the current select state.
  void sync_state_();

  ColorSplashXG *parent_{nullptr};
  std::string last_signature_;
  // Owns the strings whose c_str() pointers live in
  // SelectTraits::options_ — must outlive the traits-side
  // references between refreshes.
  std::vector<std::string> option_strings_;
};

}  // namespace colorsplash_xg
}  // namespace esphome
