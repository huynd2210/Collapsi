#include <chrono>
#include <iostream>
#include <random>
#include <string>
#include "../include/bitboard.hpp"
#include "../include/solver.hpp"

using namespace collapsi;

static BitState random_deal(uint32_t randomSeed) {
  std::mt19937 rng(randomSeed);
  // Build a 4x4 with 2xJ implied as A (1), 4xA, 4x2, 4x3, 2x4
  // Here we ignore Js specifically; treat all A-like cells as A.
  int remainingCardCounts[4] = {4, 4, 4, 2}; // A,2,3,4
  BitState state;
  for (int i = 0; i < BOARD_N; ++i) {
    int totalRemainingCards = 0; for (int count : remainingCardCounts) totalRemainingCards += count;
    int randomPick = rng() % totalRemainingCards;
    int accumulated = 0; int selected = 0;
    for (; selected < 4; ++selected) { accumulated += remainingCardCounts[selected]; if (randomPick < accumulated) break; }
    if (selected == 0) state.bbA |= bit(i);
    else if (selected == 1) state.bb2 |= bit(i);
    else if (selected == 2) state.bb3 |= bit(i);
    else state.bb4 |= bit(i);
    remainingCardCounts[selected]--;
  }
  // Place X and O on random cells that are not equal
  uint8_t xIndex = rng() % BOARD_N; uint8_t oIndex = rng() % BOARD_N; while (oIndex == xIndex) oIndex = rng() % BOARD_N;
  state.bbX = bit(xIndex); state.bbO = bit(oIndex);
  state.turn = 0; // X to move
  state.bbCollapsed = 0;
  return state;
}

static bool parse_hex16(const std::string& text, uint16_t& outValue) {
  try {
    size_t endIndex = 0;
    unsigned long parsedValue = std::stoul(text, &endIndex, 16);
    if (endIndex != text.size() || parsedValue > 0xFFFFUL) return false;
    outValue = static_cast<uint16_t>(parsedValue);
    return true;
  } catch(...) { return false; }
}

static bool parse_state_arg(const std::string& arg, BitState& outState) {
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
  uint16_t aMask, twoMask, threeMask, fourMask, xMask, oMask, collapsedMask; uint16_t turnValue;
  if (!parse_hex16(parts[0], aMask)) return false;
  if (!parse_hex16(parts[1], twoMask)) return false;
  if (!parse_hex16(parts[2], threeMask)) return false;
  if (!parse_hex16(parts[3], fourMask)) return false;
  if (!parse_hex16(parts[4], xMask)) return false;
  if (!parse_hex16(parts[5], oMask)) return false;
  if (!parse_hex16(parts[6], collapsedMask)) return false;
  if (!parse_hex16(parts[7], turnValue)) return false;
  outState.bbA = aMask; outState.bb2 = twoMask; outState.bb3 = threeMask; outState.bb4 = fourMask; outState.bbX = xMask; outState.bbO = oMask; outState.bbCollapsed = collapsedMask; outState.turn = static_cast<uint8_t>(turnValue & 1);
  return true;
}

int main(int argc, char** argv) {
  uint32_t seed = static_cast<uint32_t>(std::random_device{}());
  BitState state{};
  if (argc >= 3 && std::string(argv[1]) == "--seed") {
    seed = static_cast<uint32_t>(std::stoul(argv[2]));
    state = random_deal(seed);
  } else if (argc >= 3 && std::string(argv[1]) == "--state") {
    if (!parse_state_arg(argv[2], state)) {
      std::cerr << "Bad --state format. Expect a,2,3,4,x,o,c,turn hex values\n";
      return 2;
    }
  } else {
    state = random_deal(seed);
  }
  Solver solver;
  auto t0 = std::chrono::high_resolution_clock::now();
  Answer answer = solver.solve(state);
  auto t1 = std::chrono::high_resolution_clock::now();
  auto ms = std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0).count();
  // Output: win best_move plies timeus | then list of top-move plies for legal moves
  std::cout << (answer.win ? 1 : 0) << " " << int(answer.best_move) << " " << int(answer.plies) << " " << ms << "us";
  const auto& topMoves = solver.last_top_moves();
  const auto& topPlies = solver.last_top_move_plies();
  const auto& topWins = solver.last_top_move_wins();
  if (!topMoves.empty() && topMoves.size() == topPlies.size() && topWins.size() == topMoves.size()) {
    std::cout << " |";
    for (size_t i = 0; i < topMoves.size(); ++i) {
      std::cout << " " << int(topMoves[i]) << ":" << topPlies[i] << ":" << int(topWins[i]);
    }
  }
  std::cout << std::endl;
  return 0;
}



