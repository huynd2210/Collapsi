'''#pragma once
#include <cstdint>

namespace collapsi {

// The bitboard representation is chosen for performance. Each 16-bit integer
// represents a specific property of the 4x4 board (e.g., which squares are
// occupied by 'A' cards, which are collapsed, etc.). This allows for extremely
// fast state manipulation and queries using bitwise operations, which is
// critical for the performance of the game solver.
using bb_t = uint16_t; // 16 cells → one bit per cell

constexpr int BOARD_W = 4;
constexpr int BOARD_H = 4;
constexpr int BOARD_N = BOARD_W * BOARD_H; // 16

// Precomputed neighbor indices for each cell, handling board wrap-around.
// This avoids expensive modulo operations during move generation.
extern const uint8_t NEI_UP[BOARD_N];
extern const uint8_t NEI_DOWN[BOARD_N];
extern const uint8_t NEI_LEFT[BOARD_N];
extern const uint8_t NEI_RIGHT[BOARD_N];

// Converts a (row, column) pair to a 0-15 index for the bitboard.
// The bitwise AND with 3 (0b11) ensures coordinates wrap around the 4x4 board.
inline uint8_t rc_to_idx(int r, int c) {
  return static_cast<uint8_t>((r & 3) * BOARD_W + (c & 3));
}

// Helper functions to convert a bitboard index back to a row or column.
inline int idx_r(uint8_t idx) { return idx / BOARD_W; }
inline int idx_c(uint8_t idx) { return idx % BOARD_W; }

// Creates a bitmask with a single bit set at the specified index.
inline bb_t bit(uint8_t idx) { return static_cast<bb_t>(1u) << idx; }

// A compact representation of the entire game state using bitboards.
struct BitState {
  // Each card value gets its own bitboard.
  bb_t bbA{0}, bb2{0}, bb3{0}, bb4{0};
  // Player positions (X and O).
  bb_t bbX{0}, bbO{0};
  // A bitboard to track which cells have been collapsed.
  bb_t bbCollapsed{0};
  // The current player (0 for X, 1 for O).
  uint8_t turn{0};
};

// Determines the number of steps a player can move from a given cell.
uint8_t steps_from(const BitState& s, uint8_t idx);

// Uses a recursive DFS to find all valid destination squares for a move of a given length.
// Returns a bitmask of all reachable, valid destination squares.
bb_t enumerate_destinations(const BitState& s, uint8_t startIdx, uint8_t steps, uint8_t oppIdx);

// Returns a new state after applying a move. This function is 'pure' and does not modify the input state.
BitState apply_move(const BitState& s, uint8_t startIdx, uint8_t destIdx);

}

''


