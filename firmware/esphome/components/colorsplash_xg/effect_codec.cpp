#include "effect_codec.h"

#include <cctype>
#include <string>

namespace esphome {
namespace colorsplash_xg {

namespace {

// Lowercase, trim, replace '-' with ' ', collapse internal whitespace.
// Mirrors tools/cli.py::parse_effect normalization.
std::string normalize(std::string_view in) {
  std::string out;
  out.reserve(in.size());
  bool last_was_space = true;  // skip leading whitespace
  for (char c : in) {
    if (c == '-')
      c = ' ';
    if (std::isspace(static_cast<unsigned char>(c))) {
      if (last_was_space)
        continue;
      out.push_back(' ');
      last_was_space = true;
    } else {
      out.push_back(static_cast<char>(
          std::tolower(static_cast<unsigned char>(c))));
      last_was_space = false;
    }
  }
  while (!out.empty() && out.back() == ' ')
    out.pop_back();
  return out;
}

}  // namespace

std::optional<uint8_t> encode_effect(std::string_view name) {
  const std::string norm = normalize(name);
  if (norm.empty())
    return std::nullopt;
  for (const auto &entry : kEffectTable) {
    if (norm == entry.name)
      return entry.byte;
  }
  return std::nullopt;
}

const char *decode_byte(uint8_t byte) {
  for (const auto &entry : kEffectTable) {
    if (entry.byte == byte)
      return entry.name;
  }
  return nullptr;
}

}  // namespace colorsplash_xg
}  // namespace esphome
