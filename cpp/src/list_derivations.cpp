#include <algorithm>
#include <cstdint>
#if __has_include(<filesystem>)
#include <filesystem>
namespace fs = std::filesystem;
#elif __has_include(<experimental/filesystem>)
#include <experimental/filesystem>
namespace fs = std::experimental::filesystem;
#else
#error "No filesystem support available"
#endif
#include <fstream>
#include <iostream>
#include <set>
#include <string>
#include <tuple>
#include <vector>

#include "../include/bitboard.hpp"
#include "../include/hash.hpp"

using namespace collapsi;

static inline uint8_t rc_to_idx4(uint8_t r, uint8_t c) { return static_cast<uint8_t>((r & 3u) * 4u + (c & 3u)); }

static bb_t shift_mask(bb_t m, int dr, int dc) {
  bb_t out = 0;
  for (uint8_t i = 0; i < 16; ++i) {
    if (m & (static_cast<bb_t>(1) << i)) {
      uint8_t r = i / 4u;
      uint8_t c = i % 4u;
      uint8_t nr = static_cast<uint8_t>((r + dr) & 3u);
      uint8_t nc = static_cast<uint8_t>((c + dc) & 3u);
      out |= static_cast<bb_t>(1) << rc_to_idx4(nr, nc);
    }
  }
  return out;
}

static inline char card_char(bb_t a, bb_t b2, bb_t b3, bb_t b4, uint8_t idx) {
  bb_t bit = static_cast<bb_t>(1) << idx;
  if (a & bit) return 'A';
  if (b2 & bit) return '2';
  if (b3 & bit) return '3';
  if (b4 & bit) return '4';
  return '.';
}

static void print_cards_grid(bb_t a, bb_t b2, bb_t b3, bb_t b4) {
  for (int r = 0; r < 4; ++r) {
    for (int c = 0; c < 4; ++c) {
      uint8_t idx = static_cast<uint8_t>(r * 4 + c);
      std::cout << card_char(a, b2, b3, b4, idx);
      if (c < 3) std::cout << ' ';
    }
    std::cout << "\n";
  }
}

static void print_players_grid(bb_t x, bb_t o, bb_t collapsed) {
  for (int r = 0; r < 4; ++r) {
    for (int c = 0; c < 4; ++c) {
      uint8_t idx = static_cast<uint8_t>(r * 4 + c);
      bb_t bit = static_cast<bb_t>(1) << idx;
      char ch = '.';
      if (collapsed & bit) ch = '#';
      if (x & bit) ch = 'X';
      if (o & bit) ch = 'O';
      std::cout << ch;
      if (c < 3) std::cout << ' ';
    }
    std::cout << "\n";
  }
}

static void print_overlay_grid(bb_t a, bb_t b2, bb_t b3, bb_t b4, bb_t x, bb_t o, bb_t collapsed) {
  for (int r = 0; r < 4; ++r) {
    for (int c = 0; c < 4; ++c) {
      uint8_t idx = static_cast<uint8_t>(r * 4 + c);
      bb_t bit = static_cast<bb_t>(1) << idx;
      char ch;
      if (x & bit) ch = 'X';
      else if (o & bit) ch = 'O';
      else if (collapsed & bit) ch = '#';
      else ch = card_char(a, b2, b3, b4, idx);
      std::cout << ch;
      if (c < 3) std::cout << ' ';
    }
    std::cout << "\n";
  }
}

static std::string key_string(uint64_t k, uint8_t turn) {
  char buf[32];
  std::snprintf(buf, sizeof(buf), "%016llx|%u", static_cast<unsigned long long>(k), static_cast<unsigned>(turn));
  return std::string(buf);
}

struct IdxRec { uint64_t key; uint8_t turn; uint16_t a; uint16_t b2; uint16_t b3; uint16_t b4; uint16_t x; uint16_t o; uint16_t c; uint8_t pad; };

int main(int argc, char** argv) {
  // Args: [--db FILE] [--index FILE] [--count N]
  fs::path exeDir = fs::absolute(fs::path(argv[0])).parent_path();
  fs::path dbPath = exeDir / ".." / ".." / ".." / "data" / "solved_norm.db";
  fs::path indexPath = exeDir / ".." / ".." / ".." / "data" / "norm_index.db";
  int count = 2;
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "--db" && i + 1 < argc) dbPath = fs::path(argv[++i]);
    else if (a == "--index" && i + 1 < argc) indexPath = fs::path(argv[++i]);
    else if (a == "--count" && i + 1 < argc) count = std::max(1, std::atoi(argv[++i]));
  }
  // Load first N records from solved_norm.db
  struct Rec { uint64_t key; uint8_t turn; uint8_t win; uint8_t best; uint16_t plies; uint8_t pad[4]; };
  std::ifstream fdb(dbPath, std::ios::binary);
  if (!fdb.good()) {
    std::cerr << "Cannot open db: " << dbPath.string() << "\n";
    return 2;
  }
  std::vector<std::pair<uint64_t,uint8_t>> roots;
  for (int i = 0; i < count; ++i) {
    Rec rec{};
    if (!fdb.read(reinterpret_cast<char*>(&rec), sizeof(rec))) break;
    roots.emplace_back(rec.key, rec.turn);
  }
  // Load index into memory
  std::ifstream findex(indexPath, std::ios::binary);
  if (!findex.good()) {
    std::cerr << "Cannot open index: " << indexPath.string() << " (rerun solver to build index)\n";
    return 3;
  }
  std::vector<IdxRec> idx;
  while (true) { IdxRec rec{}; if (!findex.read(reinterpret_cast<char*>(&rec), sizeof(rec))) break; idx.push_back(rec); }
  for (const auto& rt : roots) {
    uint64_t rootKey = rt.first; uint8_t turn = rt.second;
    // find matching index record
    const IdxRec* match = nullptr;
    for (const auto& rec : idx) { if (rec.key == rootKey && rec.turn == turn) { match = &rec; break; } }
    if (!match) { std::cout << "normalized_key=" << key_string(rootKey, turn) << " (missing index)\n"; continue; }
    std::cout << "normalized_key=" << key_string(match->key, match->turn) << "\n";
    std::cout << "Board (normalized):\n";
    print_overlay_grid(match->a, match->b2, match->b3, match->b4, match->x, match->o, match->c);
    // List all raw torus shifts (16) for both turns (2) => 32 lines
    for (int dr = 0; dr < 4; ++dr) for (int dc = 0; dc < 4; ++dc) {
      bb_t aS = shift_mask(match->a, dr, dc);
      bb_t b2S = shift_mask(match->b2, dr, dc);
      bb_t b3S = shift_mask(match->b3, dr, dc);
      bb_t b4S = shift_mask(match->b4, dr, dc);
      bb_t xS = shift_mask(match->x, dr, dc);
      bb_t oS = shift_mask(match->o, dr, dc);
      uint64_t raw0 = hash_state(aS, b2S, b3S, b4S, xS, oS, match->c, 0);
      uint64_t raw1 = hash_state(aS, b2S, b3S, b4S, xS, oS, match->c, 1);
      std::cout << "\nshift dr=" << dc << " dc=" << dr << " raw0=" << key_string(raw0, 0) << " raw1=" << key_string(raw1, 1) << "\n";
      std::cout << "Board:\n"; print_overlay_grid(aS, b2S, b3S, b4S, xS, oS, match->c);
    }
  }
  return 0;
}


