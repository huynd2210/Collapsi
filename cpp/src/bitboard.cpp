#include "bitboard.hpp"

namespace collapsi {

const uint8_t NEI_UP[BOARD_N] = {
  12, 13, 14, 15,
   0,  1,  2,  3,
   4,  5,  6,  7,
   8,  9, 10, 11
};

const uint8_t NEI_DOWN[BOARD_N] = {
   4,  5,  6,  7,
   8,  9, 10, 11,
  12, 13, 14, 15,
   0,  1,  2,  3
};

const uint8_t NEI_LEFT[BOARD_N] = {
   3,  0,  1,  2,
   7,  4,  5,  6,
  11,  8,  9, 10,
  15, 12, 13, 14
};

const uint8_t NEI_RIGHT[BOARD_N] = {
   1,  2,  3,  0,
   5,  6,  7,  4,
   9, 10, 11,  8,
  13, 14, 15, 12
};

uint8_t steps_from(const BitState& s, uint8_t idx) {
  bb_t m = bit(idx);
  if (s.bbA & m) return 1;
  if (s.bb2 & m) return 2;
  if (s.bb3 & m) return 3;
  if (s.bb4 & m) return 4;
  // If no card bitboard has this index, default to 1 (treat as A)
  return 1;
}

static void dfs_paths(const BitState& s, uint8_t cur, uint8_t start,
                      uint8_t opp, uint8_t remaining,
                      bb_t blocked, bb_t visited, bb_t& outMask) {
  if (remaining == 0) {
    if (cur != start && cur != opp) outMask |= bit(cur);
    return;
  }
  auto try_step = [&](uint8_t nxt) {
    bb_t b = bit(nxt);
    if (blocked & b) return;
    if (visited & b) return;
    dfs_paths(s, nxt, start, opp, remaining - 1, blocked, static_cast<bb_t>(visited | b), outMask);
  };
  try_step(NEI_UP[cur]);
  try_step(NEI_DOWN[cur]);
  try_step(NEI_LEFT[cur]);
  try_step(NEI_RIGHT[cur]);
}

bb_t enumerate_destinations(const BitState& s, uint8_t startIdx, uint8_t steps, uint8_t oppIdx) {
  bb_t out = 0;
  bb_t blocked = s.bbCollapsed;
  bb_t visited = bit(startIdx);
  dfs_paths(s, startIdx, startIdx, oppIdx, steps, blocked, visited, out);
  return out;
}

BitState apply_move(const BitState& s, uint8_t startIdx, uint8_t destIdx) {
  BitState t = s;
  // collapse start cell
  t.bbCollapsed = static_cast<bb_t>(t.bbCollapsed | bit(startIdx));
  if (s.turn == 0) {
    // move X
    t.bbX &= static_cast<bb_t>(~bit(startIdx));
    t.bbX |= bit(destIdx);
    t.turn = 1;
  } else {
    t.bbO &= static_cast<bb_t>(~bit(startIdx));
    t.bbO |= bit(destIdx);
    t.turn = 0;
  }
  return t;
}

}


