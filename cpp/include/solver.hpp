#pragma once
#include <cstdint>
#include <unordered_map>
#include <vector>
#include "bitboard.hpp"
#include "hash.hpp"

namespace collapsi {

struct Answer { bool win; uint8_t best_move; uint16_t plies; }; // 0xFF none, plies to terminal

class Solver {
public:
  Answer solve(const BitState& s);
  const std::vector<uint8_t>& last_top_moves() const { return top_moves_; }
  const std::vector<int>& last_top_move_plies() const { return top_move_plies_; }
  const std::vector<uint8_t>& last_top_move_wins() const { return top_move_wins_; }

private:
  std::unordered_map<Key64, Answer, Key64Hasher> cache_;
  Answer solve_rec(const BitState& s, int depth);
  std::vector<uint8_t> top_moves_;
  std::vector<int> top_move_plies_;
  std::vector<uint8_t> top_move_wins_;
};

// Heuristic: fewest opponent replies, prefer count==1 first
inline uint8_t encode_move(uint8_t fromIndex, uint8_t toIndex) { return static_cast<uint8_t>(((fromIndex & 0xF) << 4) | (toIndex & 0xF)); }
inline uint8_t move_from(uint8_t encodedMove) { return (encodedMove >> 4) & 0xF; }
inline uint8_t move_to(uint8_t encodedMove) { return encodedMove & 0xF; }

}


