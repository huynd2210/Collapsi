#pragma once
#include <cstdint>

namespace collapsi {

using bb_t = uint16_t; // 16 cells → one bit per cell

constexpr int BOARD_W = 4;
constexpr int BOARD_H = 4;
constexpr int BOARD_N = BOARD_W * BOARD_H; // 16

// Precomputed neighbor indices with wrap
extern const uint8_t NEI_UP[BOARD_N];
extern const uint8_t NEI_DOWN[BOARD_N];
extern const uint8_t NEI_LEFT[BOARD_N];
extern const uint8_t NEI_RIGHT[BOARD_N];

inline uint8_t rc_to_idx(int r, int c) {
  return static_cast<uint8_t>((r & 3) * BOARD_W + (c & 3));
}

inline int idx_r(uint8_t idx) { return idx / BOARD_W; }
inline int idx_c(uint8_t idx) { return idx % BOARD_W; }

inline bb_t bit(uint8_t idx) { return static_cast<bb_t>(1u) << idx; }

struct BitState {
  bb_t bbA{0}, bb2{0}, bb3{0}, bb4{0};
  bb_t bbX{0}, bbO{0};
  bb_t bbCollapsed{0};
  uint8_t turn{0}; // 0 = X, 1 = O
};

// Steps for the starting cell under current player
uint8_t steps_from(const BitState& s, uint8_t idx);

// Enumerate destinations for exact steps, respecting constraints
// Returns a bitmask of destination squares
bb_t enumerate_destinations(const BitState& s, uint8_t startIdx, uint8_t steps, uint8_t oppIdx);

// Apply move (from startIdx to destIdx) and return new state
BitState apply_move(const BitState& s, uint8_t startIdx, uint8_t destIdx);

}


