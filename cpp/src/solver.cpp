#include "solver.hpp"
#include <vector>
#include <algorithm>

namespace collapsi {

static uint8_t piece_idx(bb_t bb) {
  // Return index 0..15 of single-bit bitboard; undefined if none/multi
  for (uint8_t i = 0; i < BOARD_N; ++i) if (bb & bit(i)) return i;
  return 0;
}

Answer Solver::solve(const BitState& s) {
  return solve_rec(s);
}

Answer Solver::solve_rec(const BitState& s) {
  Key64 k = hash_state(s.bbA, s.bb2, s.bb3, s.bb4, s.bbX, s.bbO, s.bbCollapsed, s.turn);
  if (auto it = cache_.find(k); it != cache_.end()) return it->second;

  const uint8_t meIdx = (s.turn == 0) ? piece_idx(s.bbX) : piece_idx(s.bbO);
  const uint8_t oppIdx = (s.turn == 0) ? piece_idx(s.bbO) : piece_idx(s.bbX);
  const uint8_t steps = steps_from(s, meIdx);
  bb_t dests = enumerate_destinations(s, meIdx, steps, oppIdx);
  if (dests == 0) {
    Answer a{false, 0xFF};
    cache_.emplace(k, a);
    return a;
  }

  // Heuristic: order by opponent replies ascending, with 1 first
  struct Item { uint8_t move; int oppReplies; };
  std::vector<Item> items;
  for (uint8_t to = 0; to < BOARD_N; ++to) if (dests & bit(to)) {
    BitState t = apply_move(s, meIdx, to);
    const uint8_t tMeIdx = (t.turn == 0) ? piece_idx(t.bbX) : piece_idx(t.bbO);
    const uint8_t tOppIdx = (t.turn == 0) ? piece_idx(t.bbO) : piece_idx(t.bbX);
    const uint8_t tSteps = steps_from(t, tMeIdx);
    bb_t oppDests = enumerate_destinations(t, tMeIdx, tSteps, tOppIdx);
    int cnt = 0; for (uint8_t j = 0; j < BOARD_N; ++j) if (oppDests & bit(j)) ++cnt;
    items.push_back({encode_move(meIdx, to), cnt});
  }
  // Move with exactly 1 opp reply goes to front
  std::stable_sort(items.begin(), items.end(), [](const Item& a, const Item& b){
    if (a.oppReplies == 1 && b.oppReplies != 1) return true;
    if (a.oppReplies != 1 && b.oppReplies == 1) return false;
    return a.oppReplies < b.oppReplies;
  });

  for (const Item& it : items) {
    uint8_t to = move_to(it.move);
    BitState t = apply_move(s, meIdx, to);
    // AND over opponent replies: if any reply leads to our loss, this move fails
    const uint8_t tMeIdx = (t.turn == 0) ? piece_idx(t.bbX) : piece_idx(t.bbO);
    const uint8_t tOppIdx = (t.turn == 0) ? piece_idx(t.bbO) : piece_idx(t.bbX);
    const uint8_t tSteps = steps_from(t, tMeIdx);
    bb_t oppDests = enumerate_destinations(t, tMeIdx, tSteps, tOppIdx);
    bool allFail = true;
    if (oppDests != 0) {
      for (uint8_t j = 0; j < BOARD_N; ++j) if (oppDests & bit(j)) {
        BitState tt = apply_move(t, tMeIdx, j);
        Answer sub = solve_rec(tt);
        // If after opponent's reply we (next to move) cannot force a win,
        // then opponent has a refutation and our move fails.
        if (!sub.win) { allFail = false; break; }
      }
    }
    if (allFail) {
      Answer a{true, it.move};
      cache_.emplace(k, a);
      return a;
    }
  }

  Answer a{false, 0xFF};
  cache_.emplace(k, a);
  return a;
}

}


