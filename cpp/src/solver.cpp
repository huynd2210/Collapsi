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
  top_moves_.clear();
  top_move_plies_.clear();
  top_move_wins_.clear();
  return solve_rec(state, /*depth=*/0);
}

Answer Solver::solve_rec(const BitState& state, int depth) {
  Key64 stateKey = hash_state(state.bbA, state.bb2, state.bb3, state.bb4, state.bbX, state.bbO, state.bbCollapsed, state.turn);
  if (auto cacheIterator = cache_.find(stateKey); cacheIterator != cache_.end()) return cacheIterator->second;

  const uint8_t currentPlayerIndex = (state.turn == 0) ? piece_idx(state.bbX) : piece_idx(state.bbO);
  const uint8_t opponentIndex = (state.turn == 0) ? piece_idx(state.bbO) : piece_idx(state.bbX);
  const uint8_t stepCount = steps_from(state, currentPlayerIndex);
  bb_t destinationsMask = enumerate_destinations(state, currentPlayerIndex, stepCount, opponentIndex);
  if (destinationsMask == 0) {
    Answer answer{false, 0xFF, static_cast<uint16_t>(0)};
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

  int bestLossPlies = -1; // maximize delay if losing
  uint8_t bestLossMove = 0xFF;
  int bestWinPlies = 1 << 29; // minimize plies if winning
  uint8_t bestWinMove = 0xFF;
  for (const Item& moveEntry : orderedMoves) {
    uint8_t toIndex = move_to(moveEntry.move);
    BitState nextState = apply_move(state, currentPlayerIndex, toIndex);
    // AND over opponent replies: if any reply leads to our loss, this move fails
    const uint8_t nextCurrentPlayerIndex = (nextState.turn == 0) ? piece_idx(nextState.bbX) : piece_idx(nextState.bbO);
    const uint8_t nextOpponentIndex = (nextState.turn == 0) ? piece_idx(nextState.bbO) : piece_idx(nextState.bbX);
    const uint8_t nextStepCount = steps_from(nextState, nextCurrentPlayerIndex);
    bb_t opponentDestinationsMask = enumerate_destinations(nextState, nextCurrentPlayerIndex, nextStepCount, nextOpponentIndex);
    bool allOpponentRepliesLeadToOurWin = true;
    int worstWinPlies = 0;  // opponent delays our win
    int bestLossPliesForThis = 1 << 29; // opponent accelerates our loss
    if (opponentDestinationsMask != 0) {
      for (uint8_t destinationIndex2 = 0; destinationIndex2 < BOARD_N; ++destinationIndex2) if (opponentDestinationsMask & bit(destinationIndex2)) {
        BitState replyState = apply_move(nextState, nextCurrentPlayerIndex, destinationIndex2);
        Answer replyAnswer = solve_rec(replyState, depth + 2);
        // If after opponent's reply we (next to move) cannot force a win,
        // then opponent has a refutation and our move fails.
        if (!replyAnswer.win) {
          allOpponentRepliesLeadToOurWin = false;
          // fastest loss path (opponent picks this)
          if (replyAnswer.plies + 2 < bestLossPliesForThis) bestLossPliesForThis = replyAnswer.plies + 2;
        } else {
          // slowest win path (opponent delays)
          if (replyAnswer.plies + 2 > worstWinPlies) worstWinPlies = replyAnswer.plies + 2;
        }
      }
    }
    if (allOpponentRepliesLeadToOurWin) {
      if (worstWinPlies < bestWinPlies) { bestWinPlies = worstWinPlies; bestWinMove = moveEntry.move; }
    } else {
      if (bestLossPliesForThis == (1 << 29)) bestLossPliesForThis = 2; // at least 1 move each
      if (bestLossPliesForThis > bestLossPlies) { bestLossPlies = bestLossPliesForThis; bestLossMove = moveEntry.move; }
    }
  }
  Answer answer;
  if (bestWinMove != 0xFF) {
    answer = {true, bestWinMove, static_cast<uint16_t>(bestWinPlies == (1 << 29) ? 1 : bestWinPlies)};
  } else {
    answer = {false, bestLossMove, static_cast<uint16_t>(bestLossPlies < 0 ? 0 : bestLossPlies)};
  }
  if (depth == 0) {
    // Collect top-level moves info for UI overlay
    top_moves_.clear(); top_move_plies_.clear(); top_move_wins_.clear();
    for (const Item& moveEntry : orderedMoves) {
      uint8_t toIndex = move_to(moveEntry.move);
      BitState nextState = apply_move(state, currentPlayerIndex, toIndex);
      const uint8_t nextCurrentPlayerIndex = (nextState.turn == 0) ? piece_idx(nextState.bbX) : piece_idx(nextState.bbO);
      const uint8_t nextOpponentIndex = (nextState.turn == 0) ? piece_idx(nextState.bbO) : piece_idx(nextState.bbX);
      const uint8_t nextStepCount = steps_from(nextState, nextCurrentPlayerIndex);
      bb_t opponentDestinationsMask = enumerate_destinations(nextState, nextCurrentPlayerIndex, nextStepCount, nextOpponentIndex);
      bool allOpponentRepliesLeadToOurWin2 = true;
      int worstWinPlies2 = 0;
      int bestLossPlies2 = 1 << 29;
      if (opponentDestinationsMask != 0) {
        for (uint8_t d2 = 0; d2 < BOARD_N; ++d2) if (opponentDestinationsMask & bit(d2)) {
          BitState rs = apply_move(nextState, nextCurrentPlayerIndex, d2);
          Answer ra = solve_rec(rs, 2);
          if (!ra.win) { allOpponentRepliesLeadToOurWin2 = false; if (ra.plies + 2 < bestLossPlies2) bestLossPlies2 = ra.plies + 2; }
          else { if (ra.plies + 2 > worstWinPlies2) worstWinPlies2 = ra.plies + 2; }
        }
      }
      int pl = allOpponentRepliesLeadToOurWin2 ? worstWinPlies2 : (bestLossPlies2 == (1 << 29) ? 2 : bestLossPlies2);
      top_moves_.push_back(moveEntry.move);
      top_move_plies_.push_back(pl);
      top_move_wins_.push_back(static_cast<uint8_t>(allOpponentRepliesLeadToOurWin2 ? 1 : 0));
    }
  }
  cache_.emplace(stateKey, answer);
  return answer;
}

}


