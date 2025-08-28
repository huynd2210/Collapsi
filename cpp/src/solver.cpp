//#include remains the same
#include "../include/solver.hpp"
#include <vector>
#include <algorithm>
#include <bit>

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
  Answer ans = solve_rec(state, /*depth=*/0);
  // Ensure root move metrics are available even when we short-circuit early
  if (collect_root_metrics_ && top_moves_.empty()) {
    compute_root_move_metrics(state);
  }
  return ans;
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
    int replyCount = std::popcount(opponentDestinationsMask);
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
  std::vector<uint8_t> ui_moves;
  std::vector<int> ui_plies;
  std::vector<uint8_t> ui_wins;
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
    // Record edge for optional tree dump
    if (capture_edges_) {
      Key64 childKey = hash_state(nextState.bbA, nextState.bb2, nextState.bb3, nextState.bb4, nextState.bbX, nextState.bbO, nextState.bbCollapsed, nextState.turn);
      edges_[stateKey].push_back(childKey);
    }
    if (allOpponentRepliesLeadToOurWin) {
      // Short-circuit: first winning line is enough
      int pl = (worstWinPlies == 0 ? 1 : worstWinPlies);
      if (depth == 0) {
        ui_moves.push_back(moveEntry.move);
        ui_plies.push_back(pl);
        ui_wins.push_back(1);
        top_moves_.swap(ui_moves);
        top_move_plies_.swap(ui_plies);
        top_move_wins_.swap(ui_wins);
      }
      Answer answer{true, moveEntry.move, static_cast<uint16_t>(pl)};
      cache_.emplace(stateKey, answer);
      return answer;
    } else {
      if (bestLossPliesForThis == (1 << 29)) bestLossPliesForThis = 2; // at least 1 move each
      if (bestLossPliesForThis > bestLossPlies) { bestLossPlies = bestLossPliesForThis; bestLossMove = moveEntry.move; }
    }
    if (depth == 0) {
      int pl = allOpponentRepliesLeadToOurWin ? worstWinPlies : bestLossPliesForThis;
      if (!allOpponentRepliesLeadToOurWin && pl == (1 << 29)) pl = 2;
      ui_moves.push_back(moveEntry.move);
      ui_plies.push_back(pl);
      ui_wins.push_back(static_cast<uint8_t>(allOpponentRepliesLeadToOurWin ? 1 : 0));
    }
  }
  Answer answer;
  if (bestWinMove != 0xFF) {
    answer = {true, bestWinMove, static_cast<uint16_t>(bestWinPlies == (1 << 29) ? 1 : bestWinPlies)};
  } else {
    answer = {false, bestLossMove, static_cast<uint16_t>(bestLossPlies < 0 ? 0 : bestLossPlies)};
  }
  if (depth == 0) {
    top_moves_.swap(ui_moves);
    top_move_plies_.swap(ui_plies);
    top_move_wins_.swap(ui_wins);
  }
  cache_.emplace(stateKey, answer);
  return answer;
}

void Solver::compute_root_move_metrics(const BitState& state) {
  top_moves_.clear(); top_move_plies_.clear(); top_move_wins_.clear();
  const uint8_t currentPlayerIndex = (state.turn == 0) ? piece_idx(state.bbX) : piece_idx(state.bbO);
  const uint8_t opponentIndex = (state.turn == 0) ? piece_idx(state.bbO) : piece_idx(state.bbX);
  const uint8_t stepCount = steps_from(state, currentPlayerIndex);
  bb_t destinationsMask = enumerate_destinations(state, currentPlayerIndex, stepCount, opponentIndex);
  if (destinationsMask == 0) return;
  struct Item { uint8_t move; int opponentRepliesCount; };
  std::vector<Item> orderedMoves;
  for (uint8_t destinationIndex = 0; destinationIndex < BOARD_N; ++destinationIndex) if (destinationsMask & bit(destinationIndex)) {
    BitState nextState = apply_move(state, currentPlayerIndex, destinationIndex);
    const uint8_t nextCurrentPlayerIndex = (nextState.turn == 0) ? piece_idx(nextState.bbX) : piece_idx(nextState.bbO);
    const uint8_t nextOpponentIndex = (nextState.turn == 0) ? piece_idx(nextState.bbO) : piece_idx(nextState.bbX);
    const uint8_t nextStepCount = steps_from(nextState, nextCurrentPlayerIndex);
    bb_t opponentDestinationsMask = enumerate_destinations(nextState, nextCurrentPlayerIndex, nextStepCount, nextOpponentIndex);
    int replyCount = std::popcount(opponentDestinationsMask);
    orderedMoves.push_back({encode_move(currentPlayerIndex, destinationIndex), replyCount});
  }
  std::stable_sort(orderedMoves.begin(), orderedMoves.end(), [](const Item& a, const Item& b){
    if (a.opponentRepliesCount == 1 && b.opponentRepliesCount != 1) return true;
    if (a.opponentRepliesCount != 1 && b.opponentRepliesCount == 1) return false;
    return a.opponentRepliesCount < b.opponentRepliesCount;
  });
  for (const Item& moveEntry : orderedMoves) {
    uint8_t toIndex = move_to(moveEntry.move);
    BitState nextState = apply_move(state, currentPlayerIndex, toIndex);
    const uint8_t nextCurrentPlayerIndex = (nextState.turn == 0) ? piece_idx(nextState.bbX) : piece_idx(nextState.bbO);
    const uint8_t nextOpponentIndex = (nextState.turn == 0) ? piece_idx(nextState.bbO) : piece_idx(nextState.bbX);
    const uint8_t nextStepCount = steps_from(nextState, nextCurrentPlayerIndex);
    bb_t opponentDestinationsMask = enumerate_destinations(nextState, nextCurrentPlayerIndex, nextStepCount, nextOpponentIndex);
    bool allOpponentRepliesLeadToOurWin = true;
    int worstWinPlies = 0;
    int bestLossPliesForThis = 1 << 29;
    if (opponentDestinationsMask != 0) {
      for (uint8_t d2 = 0; d2 < BOARD_N; ++d2) if (opponentDestinationsMask & bit(d2)) {
        BitState rs = apply_move(nextState, nextCurrentPlayerIndex, d2);
        Answer ra = solve_rec(rs, 2);
        if (!ra.win) { allOpponentRepliesLeadToOurWin = false; if (ra.plies + 2 < bestLossPliesForThis) bestLossPliesForThis = ra.plies + 2; }
        else { if (ra.plies + 2 > worstWinPlies) worstWinPlies = ra.plies + 2; }
      }
    }
    int pl = allOpponentRepliesLeadToOurWin ? (worstWinPlies == 0 ? 1 : worstWinPlies) : (bestLossPliesForThis == (1 << 29) ? 2 : bestLossPliesForThis);
    top_moves_.push_back(moveEntry.move);
    top_move_plies_.push_back(pl);
    top_move_wins_.push_back(static_cast<uint8_t>(allOpponentRepliesLeadToOurWin ? 1 : 0));
  }
}

void Solver::dump_tree_binary(const std::string& path, Key64 rootKey) const {
  // Simple binary format:
  // [u64 node_count]
  // For each node: [u64 key][u8 win][u8 best_move][u16 plies][u32 edge_count][u64 edge_key]*
  std::unordered_map<Key64, int, Key64Hasher> index;
  std::vector<Key64> keys;
  keys.reserve(cache_.size());
  for (const auto& [k, _] : cache_) { index[k] = static_cast<int>(keys.size()); keys.push_back(k); }
  FILE* f = fopen(path.c_str(), "wb");
  if (!f) return;
  uint64_t n = static_cast<uint64_t>(keys.size());
  fwrite(&n, sizeof(uint64_t), 1, f);
  for (Key64 k : keys) {
    const Answer& a = cache_.at(k);
    uint64_t key64 = k;
    uint8_t win = a.win ? 1 : 0;
    uint8_t best = a.best_move;
    uint16_t pl = a.plies;
    fwrite(&key64, sizeof(uint64_t), 1, f);
    fwrite(&win, sizeof(uint8_t), 1, f);
    fwrite(&best, sizeof(uint8_t), 1, f);
    fwrite(&pl, sizeof(uint16_t), 1, f);
    auto it = edges_.find(k);
    uint32_t m = (it == edges_.end()) ? 0u : static_cast<uint32_t>(it->second.size());
    fwrite(&m, sizeof(uint32_t), 1, f);
    if (m) {
      for (Key64 ek : it->second) {
        uint64_t ek64 = ek;
        fwrite(&ek64, sizeof(uint64_t), 1, f);
      }
    }
  }
  fclose(f);
}

void Solver::dump_tree_binary_to_vector(std::vector<uint8_t>& out) const {
  std::unordered_map<Key64, int, Key64Hasher> index;
  std::vector<Key64> keys;
  keys.reserve(cache_.size());
  for (const auto& [k, _] : cache_) { index[k] = static_cast<int>(keys.size()); keys.push_back(k); }
  auto append = [&](const void* ptr, size_t sz){
    const uint8_t* p = static_cast<const uint8_t*>(ptr);
    out.insert(out.end(), p, p + sz);
  };
  uint64_t n = static_cast<uint64_t>(keys.size());
  append(&n, sizeof(uint64_t));
  for (Key64 k : keys) {
    const Answer& a = cache_.at(k);
    uint64_t key64 = k;
    uint8_t win = a.win ? 1 : 0;
    uint8_t best = a.best_move;
    uint16_t pl = a.plies;
    append(&key64, sizeof(uint64_t));
    append(&win, sizeof(uint8_t));
    append(&best, sizeof(uint8_t));
    append(&pl, sizeof(uint16_t));
    auto it = edges_.find(k);
    uint32_t m = (it == edges_.end()) ? 0u : static_cast<uint32_t>(it->second.size());
    append(&m, sizeof(uint32_t));
    if (m) {
      for (Key64 ek : it->second) {
        uint64_t ek64 = ek;
        append(&ek64, sizeof(uint64_t));
      }
    }
  }
}

void Solver::clear_cache() {
  cache_.clear();
  edges_.clear();
  top_moves_.clear();
  top_move_plies_.clear();
  top_move_wins_.clear();
}

}


