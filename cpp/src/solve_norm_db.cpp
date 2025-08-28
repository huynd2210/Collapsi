#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <string>
#include <tuple>
#include <vector>
#include <chrono>

#include "../include/bitboard.hpp"
#include "../include/hash.hpp"
#include "../include/solver.hpp"

using namespace collapsi;
namespace fs = std::filesystem;

static inline uint8_t rc_to_idx4(uint8_t r, uint8_t c) { return static_cast<uint8_t>((r & 3u) * 4u + (c & 3u)); }

struct Record {
  uint64_t key;   // 64-bit Szudzik+mix over bitboards including turn
  uint8_t turn;   // 0 X, 1 O
  uint8_t win;    // 0/1
  uint8_t best;   // encoded move (from<<4|to) or 0xFF
  uint16_t plies; // depth to terminal
  uint8_t pad[4]; // pad to 16 bytes
};

int main(int argc, char** argv) {
  // Args: [--out FILE] [--stride N] [--offset K] [--limit M] [--batch B] [--dumpdir DIR]
  fs::path exeDir = fs::absolute(fs::path(argv[0])).parent_path();
  fs::path out = exeDir / ".." / ".." / ".." / "data" / "solved_norm.db";
  fs::path dumpdir; // empty means no dumps
  int stride = 1;
  int offset = 0;
  long long limit = 10'000'000; // default 10M
  size_t batch = 1'000'000;     // batch flush size
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "--out" && i + 1 < argc) { out = fs::path(argv[++i]); }
    else if (a == "--stride" && i + 1 < argc) { stride = std::max(1, std::atoi(argv[++i])); }
    else if (a == "--offset" && i + 1 < argc) { offset = std::max(0, std::atoi(argv[++i])); }
    else if (a == "--limit" && i + 1 < argc) { limit = std::atoll(argv[++i]); }
    else if (a == "--batch" && i + 1 < argc) { batch = static_cast<size_t>(std::atoll(argv[++i])); }
    else if (a == "--dumpdir" && i + 1 < argc) { dumpdir = fs::path(argv[++i]); }
  }
  fs::create_directories(out.parent_path());
  if (!dumpdir.empty()) fs::create_directories(dumpdir);

  auto t0 = std::chrono::high_resolution_clock::now();
  auto last = t0;
  std::vector<Record> buf; buf.reserve(batch);
  long long produced = 0;
  long long flushed = 0;
  int j2count = 0;

  Solver solver;
  solver.set_capture_edges(!dumpdir.empty()); // capture edges only if dumping trees

  // Enumerate canonical normalized grids: X at 0; O at any 1..15; choose positions for A,2,3; remaining are 4
  for (int oIdx = 1; oIdx < 16; ++oIdx) {
    if ((j2count % stride) != offset) { ++j2count; continue; }
    ++j2count;
    std::cout << "start_oIdx=" << oIdx << "/15 produced=" << produced << "\n";
    for (int a0 = 0; a0 < 16; ++a0)
    for (int a1 = a0 + 1; a1 < 16; ++a1)
    for (int a2 = a1 + 1; a2 < 16; ++a2)
    for (int a3 = a2 + 1; a3 < 16; ++a3) {
      std::set<int> A{a0, a1, a2, a3};
      // choose 2s
      std::vector<int> rem2; rem2.reserve(12);
      for (int i = 0; i < 16; ++i) if (!A.count(i)) rem2.push_back(i);
      for (int i0 = 0; i0 < static_cast<int>(rem2.size()); ++i0)
      for (int i1 = i0 + 1; i1 < static_cast<int>(rem2.size()); ++i1)
      for (int i2 = i1 + 1; i2 < static_cast<int>(rem2.size()); ++i2)
      for (int i3 = i2 + 1; i3 < static_cast<int>(rem2.size()); ++i3) {
        std::set<int> B2{rem2[i0], rem2[i1], rem2[i2], rem2[i3]};
        // choose 3s
        std::vector<int> rem3; rem3.reserve(8);
        for (int i : rem2) if (!B2.count(i)) rem3.push_back(i);
        for (int j0 = 0; j0 < static_cast<int>(rem3.size()); ++j0)
        for (int j1 = j0 + 1; j1 < static_cast<int>(rem3.size()); ++j1)
        for (int j2 = j1 + 1; j2 < static_cast<int>(rem3.size()); ++j2)
        for (int j3 = j2 + 1; j3 < static_cast<int>(rem3.size()); ++j3) {
          std::set<int> B3{rem3[j0], rem3[j1], rem3[j2], rem3[j3]};
          // build bitboards
          bb_t aMask = 0, twoMask = 0, threeMask = 0, fourMask = 0, xMask = 0, oMask = 0, collMask = 0;
          for (int i : A) aMask |= static_cast<bb_t>(1) << i;
          for (int i : B2) twoMask |= static_cast<bb_t>(1) << i;
          for (int i : B3) threeMask |= static_cast<bb_t>(1) << i;
          for (int i = 0; i < 16; ++i) if (!A.count(i) && !B2.count(i) && !B3.count(i)) fourMask |= static_cast<bb_t>(1) << i;
          xMask = static_cast<bb_t>(1) << 0;
          oMask = static_cast<bb_t>(1) << oIdx;
          // Solve both turns normalized (turn=0,1)
          for (uint8_t turn = 0; turn <= 1; ++turn) {
            BitState s{aMask, twoMask, threeMask, fourMask, xMask, oMask, collMask, turn};
            Answer ans = solver.solve(s);
            Key64 key = hash_state(aMask, twoMask, threeMask, fourMask, xMask, oMask, collMask, turn);
            Record r{};
            r.key = key;
            r.turn = turn;
            r.win = ans.win ? 1 : 0;
            r.best = ans.best_move;
            r.plies = ans.plies;
            buf.push_back(r);
            ++produced;
            // Optionally dump full solved tree for this root, then clear caches
            if (!dumpdir.empty()) {
              char name[64];
              std::snprintf(name, sizeof(name), "%016llx-%u.bin", static_cast<unsigned long long>(key), static_cast<unsigned>(turn));
              fs::path binpath = dumpdir / name;
              solver.dump_tree_binary(binpath.string(), key);
            }
            solver.clear_cache();
            if (buf.size() >= batch) {
              std::ofstream f(out, std::ios::binary | std::ios::app);
              f.write(reinterpret_cast<const char*>(buf.data()), static_cast<std::streamsize>(buf.size() * sizeof(Record)));
              buf.clear();
              auto t1 = std::chrono::high_resolution_clock::now();
              auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
              ++flushed;
              std::cout << "flushes=" << flushed << " produced=" << produced << " elapsed_ms=" << ms << " rate_per_s=" << (ms > 0 ? (produced * 1000.0 / ms) : 0.0) << "\n";
            }
            // periodic progress
            auto now = std::chrono::high_resolution_clock::now();
            auto since = std::chrono::duration_cast<std::chrono::milliseconds>(now - last).count();
            if (since >= 2000) {
              auto msTotal = std::chrono::duration_cast<std::chrono::milliseconds>(now - t0).count();
              double rate = (msTotal > 0 ? (produced * 1000.0 / msTotal) : 0.0);
              double pct = (limit > 0 ? (100.0 * produced / limit) : 0.0);
              std::cout << "progress produced=" << produced << " (" << pct << "%) elapsed_ms=" << msTotal << " rate_per_s=" << rate << " flushes=" << flushed << "\n";
              last = now;
            }
            if (limit > 0 && produced >= limit) {
              if (!buf.empty()) {
                std::ofstream f(out, std::ios::binary | std::ios::app);
                f.write(reinterpret_cast<const char*>(buf.data()), static_cast<std::streamsize>(buf.size() * sizeof(Record)));
              }
              auto t1 = std::chrono::high_resolution_clock::now();
              auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
              std::cout << "DONE produced=" << produced << " out=" << fs::absolute(out).string() << " elapsed_ms=" << ms << "\n";
              return 0;
            }
          }
        }
      }
    }
  }
  if (!buf.empty()) {
    std::ofstream f(out, std::ios::binary | std::ios::app);
    f.write(reinterpret_cast<const char*>(buf.data()), static_cast<std::streamsize>(buf.size() * sizeof(Record)));
  }
  auto t1 = std::chrono::high_resolution_clock::now();
  auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
  std::cout << "DONE produced=" << produced << " out=" << fs::absolute(out).string() << " elapsed_ms=" << ms << "\n";
  return 0;
}


