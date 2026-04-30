#include "colorsplash_select.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"

#include "../colorsplash_xg.h"

namespace esphome {
namespace colorsplash_xg {

static const char *const TAG = "colorsplash_xg.select";

void ColorSplashSelect::setup() {
  this->refresh_options_();
  this->publish_state(kSelectNoneOption);
}

void ColorSplashSelect::update() {
  if (this->parent_ == nullptr) return;
  this->refresh_options_();
  this->sync_state_();
}

void ColorSplashSelect::dump_config() {
  ESP_LOGCONFIG(TAG, "ColorSplash Active Preset Select:");
  ESP_LOGCONFIG(TAG, "  Options: %u",
                static_cast<unsigned>(
                    this->traits.get_options().size()));
}

void ColorSplashSelect::control(const std::string &value) {
  // The (none) sentinel doesn't trigger a recall — it just clears
  // any leftover "active preset" state. Useful for scenes that
  // want to set the fixture to a hardware effect without leaving
  // a stale preset selected.
  if (value == kSelectNoneOption) {
    this->publish_state(value);
    return;
  }
  if (this->parent_ == nullptr) return;
  bool ok = this->parent_->color_preset_recall(value);
  if (ok) {
    this->publish_state(value);
  } else {
    ESP_LOGW(TAG, "select_option: slug '%s' not found in NVS",
             value.c_str());
  }
}

void ColorSplashSelect::refresh_options_() {
  // Cheap signature: count + every slug joined by '|'. Used both
  // as a change detector AND to skip the traits.set_options()
  // call when nothing changed.
  std::string sig = std::to_string(this->parent_->preset_count());
  for (size_t i = 0; i < this->parent_->preset_count(); i++) {
    sig += "|";
    sig += this->parent_->preset_slug_at(i);
  }
  if (sig == this->last_signature_) return;
  this->last_signature_ = sig;

  // Build the new authoritative string vector (sentinel + slugs).
  std::vector<std::string> new_strings;
  new_strings.reserve(this->parent_->preset_count() + 1);
  new_strings.emplace_back(kSelectNoneOption);
  for (size_t i = 0; i < this->parent_->preset_count(); i++) {
    new_strings.push_back(this->parent_->preset_slug_at(i));
  }

  // SelectTraits stores raw const char* pointers into our strings,
  // so the strings must outlive the pointers. Stash the old
  // string vector so its pointers (currently in traits.options_)
  // stay valid until we overwrite them via set_options below; only
  // then can stash be safely destroyed.
  auto stash = std::move(this->option_strings_);
  this->option_strings_ = std::move(new_strings);

  FixedVector<const char *> ptrs;
  ptrs.init(this->option_strings_.size());
  for (auto &s : this->option_strings_) {
    ptrs.push_back(s.c_str());
  }
  this->traits.set_options(ptrs);

  ESP_LOGI(TAG, "options refreshed (%u entries)",
           static_cast<unsigned>(this->option_strings_.size()));
  // stash destroyed here — safe, traits no longer references it.
}

void ColorSplashSelect::sync_state_() {
  const std::string &recalled = this->parent_->last_recalled_slug();
  const std::string desired = recalled.empty() ? kSelectNoneOption
                                               : recalled;
  if (desired != this->current_option()) {
    this->publish_state(desired);
  }
}

}  // namespace colorsplash_xg
}  // namespace esphome
