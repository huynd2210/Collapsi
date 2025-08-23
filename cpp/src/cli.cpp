#include <chrono>
#include <iostream>
#include <random>
#include "bitboard.hpp"
#include "solver.hpp"

using namespace collapsi;

static BitState random_deal(uint32_t seed) {
  std::mt19937 rng(seed);
  // Build a 4x4 with 2xJ implied as A (1), 4xA, 4x2, 4x3, 2x4
  // Here we ignore Js specifically; treat all A-like cells as A.
  int counts[4] = {4, 4, 4, 2}; // A,2,3,4
  BitState s;
  for (int i = 0; i < BOARD_N; ++i) {
    int total = 0; for (int c : counts) total += c;
    int pick = rng() % total;
    int acc = 0; int t = 0;
    for (; t < 4; ++t) { acc += counts[t]; if (pick < acc) break; }
    if (t == 0) s.bbA |= bit(i);
    else if (t == 1) s.bb2 |= bit(i);
    else if (t == 2) s.bb3 |= bit(i);
    else s.bb4 |= bit(i);
    counts[t]--;
  }
  // Place X and O on random cells that are not equal
  uint8_t x = rng() % BOARD_N; uint8_t o = rng() % BOARD_N; while (o == x) o = rng() % BOARD_N;
  s.bbX = bit(x); s.bbO = bit(o);
  s.turn = 0; // X to move
  s.bbCollapsed = 0;
  return s;
}

static bool parse_hex16(const std::string& s, uint16_t& out) {
  try {
    size_t idx = 0;
    unsigned long v = std::stoul(s, &idx, 16);
    if (idx != s.size() || v > 0xFFFFUL) return false;
    out = static_cast<uint16_t>(v);
    return true;
  } catch(...) { return false; }
}

static bool parse_state_arg(const std::string& arg, BitState& s) {
  // format: a,2,3,4,x,o,c,turn (hex values, turn is 0/1)
  std::vector<std::string> parts;
  size_t start = 0;
  for (size_t i = 0; i <= arg.size(); ++i) {
    if (i == arg.size() || arg[i] == ',') {
      parts.emplace_back(arg.substr(start, i - start));
      start = i + 1;
    }
  }
  if (parts.size() != 8) return false;
  uint16_t a, b2, b3, b4, x, o, c; uint16_t t;
  if (!parse_hex16(parts[0], a)) return false;
  if (!parse_hex16(parts[1], b2)) return false;
  if (!parse_hex16(parts[2], b3)) return false;
  if (!parse_hex16(parts[3], b4)) return false;
  if (!parse_hex16(parts[4], x)) return false;
  if (!parse_hex16(parts[5], o)) return false;
  if (!parse_hex16(parts[6], c)) return false;
  if (!parse_hex16(parts[7], t)) return false;
  s.bbA = a; s.bb2 = b2; s.bb3 = b3; s.bb4 = b4; s.bbX = x; s.bbO = o; s.bbCollapsed = c; s.turn = static_cast<uint8_t>(t & 1);
  return true;
}

int main(int argc, char** argv) {
  uint32_t seed = static_cast<uint32_t>(std::random_device{}());
  BitState s{};
  if (argc >= 3 && std::string(argv[1]) == "--seed") {
    seed = static_cast<uint32_t>(std::stoul(argv[2]));
    s = random_deal(seed);
  } else if (argc >= 3 && std::string(argv[1]) == "--state") {
    if (!parse_state_arg(argv[2], s)) {
      std::cerr << "Bad --state format. Expect a,2,3,4,x,o,c,turn hex values\n";
      return 2;
    }
  } else {
    s = random_deal(seed);
  }
  Solver solver;
  auto t0 = std::chrono::high_resolution_clock::now();
  Answer ans = solver.solve(s);
  auto t1 = std::chrono::high_resolution_clock::now();
  auto ms = std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0).count();
  std::cout << (ans.win ? 1 : 0) << " " << int(ans.best_move) << " " << ms << "us\n";
  return 0;
}


