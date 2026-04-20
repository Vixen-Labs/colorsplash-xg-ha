#pragma once

// Pure-logic name↔byte codec for the ColorSplash XG BLE protocol.
// Mirrors tools/cli.py's EFFECT_TABLE. Cross-verified by
// tests/test_esphome_effect_codec.py. Zero BLE dependencies so this
// file can compile standalone on the host for unit tests.
//
// See docs/PROTOCOL.md §Effect opcode table for the authoritative
// list. The 15 entries here cover the full 0x00..0x0e opcode space.

#include <cstdint>
#include <optional>
#include <string_view>

namespace esphome {
namespace colorsplash_xg {

struct EffectEntry {
  const char *name;
  uint8_t byte;
};

// Source of truth for the C++ side. Keep in sync with tools/cli.py.
inline constexpr EffectEntry kEffectTable[] = {
    // Controls
    {"standby",           0x00},
    // Shows
    {"peruvian paradise", 0x01},
    {"super nova",        0x02},
    {"northern lights",   0x03},
    {"tidal wave",        0x04},
    {"patriot dream",     0x05},
    {"desert skies",      0x06},
    {"nova",              0x07},
    // Solid colors
    {"parisian blue",     0x08},
    {"new zealand green", 0x09},
    {"brazilian red",     0x0A},
    {"arctic white",      0x0B},
    {"miami pink",        0x0C},
    // More controls
    {"lock",              0x0D},
    {"return",            0x0E},
};

// Lookup an effect by its canonical name (lowercase, words separated
// by single spaces). Returns the on-wire byte, or std::nullopt if the
// name isn't recognized. Accepts case-insensitive input and treats
// '-' as a word separator, matching cli.py's parse_effect.
std::optional<uint8_t> encode_effect(std::string_view name);

// Return the canonical name for a byte, or nullptr if the byte is
// outside the 0x00..0x0e opcode space.
const char *decode_byte(uint8_t byte);

}  // namespace colorsplash_xg
}  // namespace esphome
