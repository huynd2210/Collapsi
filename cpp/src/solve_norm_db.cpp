#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <set>
#include <string>
#include <vector>
#include <chrono>

#include <filesystem>
namespace fs = std::filesystem;

#include "../include/bitboard.hpp"
#include "../include/hash.hpp"
#include "../include/solver.hpp"

using namespace collapsi;

static inline uint8_t rc_to_idx4(uint8_t r, uint8_t c) { return static_cast<uint8_t>((r & 3u) * 4u + (c & 3u)); }

struct Record {
  uint64_t key;   // 64-bit Szudzik+mix over bitboards including turn
  uint8_t turn;   // 0 X, 1 O
  uint8_t win;    // 0/1
  uint8_t best;   // encoded move (from<<4|to) or 0xFF
  uint16_t plies; // depth to terminal
  uint8_t pad[4]; // pad to 16 bytes
};

struct IdxRec { uint64_t key; uint8_t turn; uint16_t a; uint16_t b2; uint16_t b3; uint16_t b4; uint16_t x; uint16_t o; uint16_t c; uint8_t pad; };

static uint64_t truncate_to_multiple_and_count(const fs::path& path, uint64_t recordSize) {
  std::error_code ec;
  if (!fs::exists(path, ec)) return 0;
  uint64_t size = static_cast<uint64_t>(fs::file_size(path, ec));
  if (ec) return 0;
  if (recordSize == 0) return 0;
  uint64_t remainder = size % recordSize;
  if (remainder != 0) {
    uint64_t newSize = size - remainder;
    fs::resize_file(path, newSize, ec);
  }
  std::error_code ec2;
  uint64_t finalSize = static_cast<uint64_t>(fs::file_size(path, ec2));
  return (recordSize ? (finalSize / recordSize) : 0);
}

int main(int argc, char** argv) {
  // Args: [--out FILE] [--stride N] [--offset K] [--limit M] [--batch B] [--index-only]
  fs::path exeDir = fs::absolute(fs::path(argv[0])).parent_path();
  fs::path out = exeDir / ".." / ".." / ".." / "data" / "solved_norm.db";
  fs::path indexPath = exeDir / ".." / ".." / ".." / "data" / "norm_index.db";
  int stride = 1;
  int offset = 0;
  long long limit = 10'000'000; // default 10M
  size_t batch = 1'000'000;     // batch flush size
  bool indexOnly = false;
  bool noIndex = false;
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "--out" && i + 1 < argc) { out = fs::path(argv[++i]); }
    else if (a == "--stride" && i + 1 < argc) { stride = std::max(1, std::atoi(argv[++i])); }
    else if (a == "--offset" && i + 1 < argc) { offset = std::max(0, std::atoi(argv[++i])); }
    else if (a == "--limit" && i + 1 < argc) { limit = std::atoll(argv[++i]); }
    else if (a == "--batch" && i + 1 < argc) { batch = static_cast<size_t>(std::atoll(argv[++i])); }
    else if (a == "--index-only") { indexOnly = true; }
    else if (a == "--no-index") { noIndex = true; }
  }
  fs::create_directories(out.parent_path());
  fs::create_directories(indexPath.parent_path());
  // Open index file lazily per batch to avoid keeping handles open

  auto t0 = std::chrono::high_resolution_clock::now();
  auto last = t0;
  std::vector<Record> buf; buf.reserve(batch);
  long long produced = 0;        // total enumerated entries (turn-scoped)
  long long writtenSolved = 0;   // total solved records actually written this run
  long long writtenIndex = 0;    // total index records actually written this run
  long long flushed = 0;
  int j2count = 0;

  Solver solver;
  solver.set_capture_edges(false);
  solver.set_collect_root_metrics(false); // speed up bulk solving

  // Resume support: truncate files to full records and compute existing counts
  const uint64_t recSize = static_cast<uint64_t>(sizeof(Record));
  const uint64_t idxSize = static_cast<uint64_t>(sizeof(IdxRec));
  uint64_t existingSolvedCount = truncate_to_multiple_and_count(out, recSize);
  uint64_t existingIndexCount  = noIndex ? 0 : truncate_to_multiple_and_count(indexPath, idxSize);
  std::cout << "resume solved_count=" << existingSolvedCount
            << " index_count=" << existingIndexCount
            << " recSize=" << recSize << " idxSize=" << idxSize << "\n";

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
            Key64 key = hash_state(aMask, twoMask, threeMask, fourMask, xMask, oMask, collMask, turn);
            // Always write index record unless disabled
            IdxRec idx{};
            idx.key = key; idx.turn = turn; idx.a = aMask; idx.b2 = twoMask; idx.b3 = threeMask; idx.b4 = fourMask; idx.x = xMask; idx.o = oMask; idx.c = collMask; idx.pad = 0;
            if (!noIndex && static_cast<uint64_t>(produced) >= existingIndexCount) {
              std::ofstream fi(indexPath, std::ios::binary | std::ios::app);
              fi.write(reinterpret_cast<const char*>(&idx), static_cast<std::streamsize>(sizeof(idx)));
              ++writtenIndex;
            }
            if (!indexOnly && static_cast<uint64_t>(produced) >= existingSolvedCount) {
              Answer ans = solver.solve(s);
              Record r{};
              r.key = key;
              r.turn = turn;
              r.win = ans.win ? 1 : 0;
              r.best = ans.best_move;
              r.plies = ans.plies;
              buf.push_back(r);
              ++writtenSolved;
            }
            ++produced;
            // Flush solved DB in batches if solving
            if (!indexOnly && buf.size() >= batch) {
              std::ofstream f(out, std::ios::binary | std::ios::app);
              f.write(reinterpret_cast<const char*>(buf.data()), static_cast<std::streamsize>(buf.size() * sizeof(Record)));
              buf.clear();
              auto t1 = std::chrono::high_resolution_clock::now();
              auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
              ++flushed;
              std::cout << "flushes=" << flushed << " produced=" << produced
                        << " wrote_solved=" << writtenSolved << " wrote_index=" << writtenIndex
                        << " elapsed_ms=" << ms << " rate_per_s=" << (ms > 0 ? (produced * 1000.0 / ms) : 0.0) << "\n";
            }
            // periodic progress
            auto now = std::chrono::high_resolution_clock::now();
            auto since = std::chrono::duration_cast<std::chrono::milliseconds>(now - last).count();
            if (since >= 2000) {
              auto msTotal = std::chrono::duration_cast<std::chrono::milliseconds>(now - t0).count();
              double rate = (msTotal > 0 ? (produced * 1000.0 / msTotal) : 0.0);
              double pct = (limit > 0 ? (100.0 * produced / limit) : 0.0);
              std::cout << "progress produced=" << produced << " (" << pct << "%)"
                        << " wrote_solved=" << writtenSolved << " wrote_index=" << writtenIndex
                        << " elapsed_ms=" << msTotal << " rate_per_s=" << rate << " flushes=" << flushed << "\n";
              last = now;
            }
            // periodic cache control to limit RAM: reinitialize solver
            if ((produced % 100000) == 0) {
              solver = Solver();
              solver.set_capture_edges(false);
            }
            if (limit > 0 && produced >= limit) {
              if (!indexOnly && !buf.empty()) {
                std::ofstream f(out, std::ios::binary | std::ios::app);
                f.write(reinterpret_cast<const char*>(buf.data()), static_cast<std::streamsize>(buf.size() * sizeof(Record)));
              }
              auto t1 = std::chrono::high_resolution_clock::now();
              auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
              std::cout << "DONE produced=" << produced << (indexOnly ? " (index-only)" : "")
                        << " wrote_solved=" << writtenSolved << " wrote_index=" << writtenIndex
                        << " out=" << fs::absolute(out).string() << " idx=" << fs::absolute(indexPath).string() << " elapsed_ms=" << ms << "\n";
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
  std::cout << "DONE produced=" << produced
            << " wrote_solved=" << writtenSolved << " wrote_index=" << writtenIndex
            << " out=" << fs::absolute(out).string() << " elapsed_ms=" << ms << "\n";
  return 0;
}


