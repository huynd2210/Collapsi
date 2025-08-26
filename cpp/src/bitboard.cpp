#include "../include/bitboard.hpp"

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

uint8_t steps_from(const BitState& state, uint8_t cellIndex) {
  bb_t cellMask = bit(cellIndex);
  if (state.bbA & cellMask) return 1;
  if (state.bb2 & cellMask) return 2;
  if (state.bb3 & cellMask) return 3;
  if (state.bb4 & cellMask) return 4;
  // If no card bitboard has this index, default to 1 (treat as A)
  return 1;
}

static void dfs_paths(const BitState& state, uint8_t currentIndex, uint8_t startIndex,
                      uint8_t opponentIndex, uint8_t remainingSteps,
                      bb_t blockedMask, bb_t visitedMask, bb_t& outDestinationsMask) {
  if (remainingSteps == 0) {
    if (currentIndex != startIndex && currentIndex != opponentIndex) outDestinationsMask |= bit(currentIndex);
    return;
  }
  auto tryStep = [&](uint8_t nextIndex) {
    bb_t nextBitMask = bit(nextIndex);
    if (blockedMask & nextBitMask) return;
    if (visitedMask & nextBitMask) return;
    dfs_paths(state, nextIndex, startIndex, opponentIndex, static_cast<uint8_t>(remainingSteps - 1), blockedMask, static_cast<bb_t>(visitedMask | nextBitMask), outDestinationsMask);
  };
  tryStep(NEI_UP[currentIndex]);
  tryStep(NEI_DOWN[currentIndex]);
  tryStep(NEI_LEFT[currentIndex]);
  tryStep(NEI_RIGHT[currentIndex]);
}

bb_t enumerate_destinations(const BitState& state, uint8_t startIndex, uint8_t stepCount, uint8_t opponentIndex) {
  bb_t destinationsMask = 0;
  bb_t blockedMask = state.bbCollapsed;
  bb_t visitedMask = bit(startIndex);
  dfs_paths(state, startIndex, startIndex, opponentIndex, stepCount, blockedMask, visitedMask, destinationsMask);
  return destinationsMask;
}

BitState apply_move(const BitState& state, uint8_t startIndex, uint8_t destIndex) {
  BitState nextState = state;
  // collapse start cell
  nextState.bbCollapsed = static_cast<bb_t>(nextState.bbCollapsed | bit(startIndex));
  if (state.turn == 0) {
    // move X
    nextState.bbX &= static_cast<bb_t>(~bit(startIndex));
    nextState.bbX |= bit(destIndex);
    nextState.turn = 1;
  } else {
    nextState.bbO &= static_cast<bb_t>(~bit(startIndex));
    nextState.bbO |= bit(destIndex);
    nextState.turn = 0;
  }
  return nextState;
}

}


