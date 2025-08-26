//#include remains the same
#include "../include/solver.hpp"
#include <vector>
#include <algorithm>

namespace collapsi {

static uint8_t piece_idx(bb_t bitboard) {
  // Return index 0..15 of single-bit bitboard; undefined if none/multi
  for (uint8_t cellIndex = 0; cellIndex < BOARD_N; ++cellIndex) if (bitboard & bit(cellIndex)) return cellIndex;
  return 0;
}

Answer Solver::solve(const BitState& state) {
  return solve_rec(state);
}

Answer Solver::solve_rec(const BitState& state) {
  Key64 stateKey = hash_state(state.bbA, state.bb2, state.bb3, state.bb4, state.bbX, state.bbO, state.bbCollapsed, state.turn);
  if (auto cacheIterator = cache_.find(stateKey); cacheIterator != cache_.end()) return cacheIterator->second;

  const uint8_t currentPlayerIndex = (state.turn == 0) ? piece_idx(state.bbX) : piece_idx(state.bbO);
  const uint8_t opponentIndex = (state.turn == 0) ? piece_idx(state.bbO) : piece_idx(state.bbX);
  const uint8_t stepCount = steps_from(state, currentPlayerIndex);
  bb_t destinationsMask = enumerate_destinations(state, currentPlayerIndex, stepCount, opponentIndex);
  if (destinationsMask == 0) {
    Answer answer{false, 0xFF};
    cache_.emplace(stateKey, answer);
    return answer;
  }

  // Heuristic: order by opponent replies ascending, with 1 first
  struct Item { uint8_t move; int opponentRepliesCount; };
  std::vector<Item> orderedMoves;
  for (uint8_t destinationIndex = 0; destinationIndex < BOARD_N; ++destinationIndex) if (destinationsMask & bit(destinationIndex)) {
    BitState nextState = apply_move(state, currentPlayerIndex, destinationIndex);
    const uint8_t nextCurrentPlayerIndex = (nextState.turn == 0) ? piece_idx(nextState.bbX) : piece_idx(nextState.bbO);
    const uint8_t nextOpponentIndex = (nextState.turn == 0) ? piece_idx(nextState.bbO) : piece_idx(nextState.bbX);
    const uint8_t nextStepCount = steps_from(nextState, nextCurrentPlayerIndex);
    bb_t opponentDestinationsMask = enumerate_destinations(nextState, nextCurrentPlayerIndex, nextStepCount, nextOpponentIndex);
    int replyCount = 0; for (uint8_t destinationIndex2 = 0; destinationIndex2 < BOARD_N; ++destinationIndex2) if (opponentDestinationsMask & bit(destinationIndex2)) ++replyCount;
    orderedMoves.push_back({encode_move(currentPlayerIndex, destinationIndex), replyCount});
  }
  // Move with exactly 1 opp reply goes to front
  std::stable_sort(orderedMoves.begin(), orderedMoves.end(), [](const Item& a, const Item& b){
    if (a.opponentRepliesCount == 1 && b.opponentRepliesCount != 1) return true;
    if (a.opponentRepliesCount != 1 && b.opponentRepliesCount == 1) return false;
    return a.opponentRepliesCount < b.opponentRepliesCount;
  });

  for (const Item& moveEntry : orderedMoves) {
    uint8_t toIndex = move_to(moveEntry.move);
    BitState nextState = apply_move(state, currentPlayerIndex, toIndex);
    // AND over opponent replies: if any reply leads to our loss, this move fails
    const uint8_t nextCurrentPlayerIndex = (nextState.turn == 0) ? piece_idx(nextState.bbX) : piece_idx(nextState.bbO);
    const uint8_t nextOpponentIndex = (nextState.turn == 0) ? piece_idx(nextState.bbO) : piece_idx(nextState.bbX);
    const uint8_t nextStepCount = steps_from(nextState, nextCurrentPlayerIndex);
    bb_t opponentDestinationsMask = enumerate_destinations(nextState, nextCurrentPlayerIndex, nextStepCount, nextOpponentIndex);
    bool allOpponentRepliesLeadToOurWin = true;
    if (opponentDestinationsMask != 0) {
      for (uint8_t destinationIndex2 = 0; destinationIndex2 < BOARD_N; ++destinationIndex2) if (opponentDestinationsMask & bit(destinationIndex2)) {
        BitState replyState = apply_move(nextState, nextCurrentPlayerIndex, destinationIndex2);
        Answer replyAnswer = solve_rec(replyState);
        // If after opponent's reply we (next to move) cannot force a win,
        // then opponent has a refutation and our move fails.
        if (!replyAnswer.win) { allOpponentRepliesLeadToOurWin = false; break; }
      }
    }
    if (allOpponentRepliesLeadToOurWin) {
      Answer answer{true, moveEntry.move};
      cache_.emplace(stateKey, answer);
      return answer;
    }
  }

  Answer answer{false, 0xFF};
  cache_.emplace(stateKey, answer);
  return answer;
}

}


