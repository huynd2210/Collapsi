#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <set>
#include <string>
#include <vector>
#include <chrono>
#include <filesystem>

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

static uint64_t truncate_to_multiple_and_count(const std::filesystem::path& path, uint64_t recordSize) {
  std::error_code ec;
  if (!std::filesystem::exists(path, ec)) return 0;
  uint64_t size = static_cast<uint64_t>(std::filesystem::file_size(path, ec));
  if (ec) return 0;
  if (recordSize == 0) return 0;
  uint64_t remainder = size % recordSize;
  if (remainder != 0) {
    uint64_t newSize = size - remainder;
    std::filesystem::resize_file(path, newSize, ec);
  }
  std::error_code ec2;
  uint64_t finalSize = static_cast<uint64_t>(std::filesystem::file_size(path, ec2));
  return (recordSize ? (finalSize / recordSize) : 0);
}

static uint64_t count_tree_records(const std::filesystem::path& treePath) {
  std::ifstream f(treePath, std::ios::binary);
  if (!f.good()) return 0;
  uint64_t count = 0;
  while (true) {
    uint64_t key64 = 0; uint8_t t = 0; uint32_t sz = 0;
    if (!f.read(reinterpret_cast<char*>(&key64), sizeof(key64))) break;
    if (!f.read(reinterpret_cast<char*>(&t), sizeof(t))) break;
    if (!f.read(reinterpret_cast<char*>(&sz), sizeof(sz))) break;
    if (sz > 0) f.seekg(static_cast<std::streamoff>(sz), std::ios::cur);
    ++count;
  }
  return count;
}

int main(int argc, char** argv) {
  // Args: [--out FILE] [--stride N] [--offset K] [--limit M] [--batch B] [--index-only] [--no-index] [--tree-out FILE] [--trees-only]
  std::filesystem::path exeDir = std::filesystem::absolute(std::filesystem::path(argv[0])).parent_path();
  std::filesystem::path out = exeDir / ".." / ".." / ".." / "data" / "solved_norm.db";
  std::filesystem::path indexPath = exeDir / ".." / ".." / ".." / "data" / "norm_index.db";
  std::filesystem::path treeOut; // optional tree DB (aggregate)
  std::filesystem::path treeDir; // optional tree directory (per-root .bin)
  int treeTurnOnly = -1; // -1 = both, 0 = X-to-move only, 1 = O-to-move only
  int solveTurnOnly = -1; // -1 = both, 0 = X-only (skip O-start), 1 = O-only
  int stride = 1;
  int offset = 0;
  long long limit = 10'000'000; // default 10M
  size_t batch = 1'000'000;     // batch flush size
  bool indexOnly = false;
  bool noIndex = false;
  bool treesOnly = false;
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "--out" && i + 1 < argc) { out = std::filesystem::path(argv[++i]); }
    else if (a == "--stride" && i + 1 < argc) { stride = std::max(1, std::atoi(argv[++i])); }
    else if (a == "--offset" && i + 1 < argc) { offset = std::max(0, std::atoi(argv[++i])); }
    else if (a == "--limit" && i + 1 < argc) { limit = std::atoll(argv[++i]); }
    else if (a == "--batch" && i + 1 < argc) { batch = static_cast<size_t>(std::atoll(argv[++i])); }
    else if (a == "--index-only") { indexOnly = true; }
    else if (a == "--no-index") { noIndex = true; }
    else if (a == "--tree-out" && i + 1 < argc) { treeOut = std::filesystem::path(argv[++i]); }
    else if (a == "--tree-dir" && i + 1 < argc) { treeDir = std::filesystem::path(argv[++i]); }
    else if (a == "--tree-turn-only" && i + 1 < argc) { treeTurnOnly = std::atoi(argv[++i]); }
    else if (a == "--turn-only" && i + 1 < argc) { solveTurnOnly = std::atoi(argv[++i]); }
    else if (a == "--trees-only") { treesOnly = true; }
  }
  std::filesystem::create_directories(out.parent_path());
  std::filesystem::create_directories(indexPath.parent_path());
  if (!treeOut.empty()) std::filesystem::create_directories(treeOut.parent_path());
  if (!treeDir.empty()) std::filesystem::create_directories(treeDir);

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
  solver.set_collect_root_metrics(true);

  // Resume support: truncate files to full records and compute existing counts
  const uint64_t recSize = static_cast<uint64_t>(sizeof(Record));
  const uint64_t idxSize = static_cast<uint64_t>(sizeof(IdxRec));
  uint64_t existingSolvedCount = truncate_to_multiple_and_count(out, recSize);
  uint64_t existingIndexCount  = noIndex ? 0 : truncate_to_multiple_and_count(indexPath, idxSize);
  std::cout << "resume solved_count=" << existingSolvedCount
            << " index_count=" << existingIndexCount
            << " recSize=" << recSize << " idxSize=" << idxSize << "\n";

  // Backfill mode: generate only trees from existing index
  if (treesOnly) {
    if (treeOut.empty()) {
      // allow trees-only with --tree-dir instead of --tree-out
      if (treeDir.empty()) {
        std::cerr << "trees-only requires --tree-out FILE or --tree-dir DIR" << "\n";
        return 2;
      }
    }
    std::ifstream findex(indexPath, std::ios::binary);
    if (!findex.good()) {
      std::cerr << "Cannot open index: " << indexPath.string() << "\n";
      return 3;
    }
    uint64_t existingTrees = 0;
    if (!treeOut.empty()) {
      existingTrees = count_tree_records(treeOut);
      // Skip existingTrees records in index to resume
      uint64_t skipped = 0;
      while (skipped < existingTrees) {
        IdxRec tmp{};
        if (!findex.read(reinterpret_cast<char*>(&tmp), sizeof(tmp))) break;
        ++skipped;
      }
    }
    std::cout << "trees-only existing_trees=" << existingTrees << "\n";
    Solver tsolver;
    tsolver.set_capture_edges(true);
    tsolver.set_collect_root_metrics(false);
    uint64_t processed = 0;
    auto t0b = std::chrono::high_resolution_clock::now();
    while (true) {
      IdxRec rec{};
      if (!findex.read(reinterpret_cast<char*>(&rec), sizeof(rec))) break;
      if (treeTurnOnly >= 0 && static_cast<int>(rec.turn) != treeTurnOnly) {
        continue;
      }
      BitState s{rec.a, rec.b2, rec.b3, rec.b4, rec.x, rec.o, rec.c, rec.turn};
      (void)tsolver.solve(s);
      std::vector<uint8_t> blob; blob.reserve(2048);
      tsolver.dump_tree_binary_to_vector(blob);
      uint64_t key64 = rec.key; uint8_t t = rec.turn; uint32_t sz = static_cast<uint32_t>(blob.size());
      if (!treeOut.empty()) {
        std::ofstream ft(treeOut, std::ios::binary | std::ios::app);
        ft.write(reinterpret_cast<const char*>(&key64), sizeof(uint64_t));
        ft.write(reinterpret_cast<const char*>(&t), sizeof(uint8_t));
        ft.write(reinterpret_cast<const char*>(&sz), sizeof(uint32_t));
        if (sz) ft.write(reinterpret_cast<const char*>(blob.data()), sz);
      }
      if (!treeDir.empty()) {
        // Determine winner for filename tag
        Answer a = tsolver.solve(s);
        char winChar = a.win ? (rec.turn == 0 ? 'X' : 'O') : (rec.turn == 0 ? 'O' : 'X');
        char name[64];
        if (treeTurnOnly == 0) {
          std::snprintf(name, sizeof(name), "%016llx-%c.bin", static_cast<unsigned long long>(key64), winChar);
        } else {
          std::snprintf(name, sizeof(name), "%016llx-%u-%c.bin", static_cast<unsigned long long>(key64), static_cast<unsigned>(t), winChar);
        }
        auto path = treeDir / name;
        tsolver.dump_tree_binary(path.string(), key64);
      }
      // reset between roots to cap RAM
      tsolver = Solver();
      tsolver.set_capture_edges(true);
      tsolver.set_collect_root_metrics(false);
      ++processed;
      if (limit > 0 && processed >= static_cast<uint64_t>(limit)) break;
      auto nowb = std::chrono::high_resolution_clock::now();
      auto msb = std::chrono::duration_cast<std::chrono::milliseconds>(nowb - t0b).count();
      if ((processed % 1000ull) == 0ull) {
        std::cout << "trees progress processed=" << processed << " elapsed_ms=" << msb
                  << " rate_per_s=" << (msb > 0 ? (processed * 1000.0 / msb) : 0.0) << "\n";
      }
    }
    auto t1b = std::chrono::high_resolution_clock::now();
    auto msb = std::chrono::duration_cast<std::chrono::milliseconds>(t1b - t0b).count();
    std::cout << "trees-only DONE processed=" << processed << " out=" << std::filesystem::absolute(treeOut).string()
              << " elapsed_ms=" << msb << "\n";
    return 0;
  }

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
            if (solveTurnOnly >= 0 && static_cast<int>(turn) != solveTurnOnly) {
              // Skip counting for non-selected turn – does not consume limit
              continue;
            }
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
              // If tree capture requested, isolate per-root cache
              if (!treeOut.empty() || !treeDir.empty()) {
                solver = Solver();
                solver.set_capture_edges(true);
                solver.set_collect_root_metrics(true);
              } else {
                solver.set_capture_edges(false);
              }
              Answer ans = solver.solve(s);
              Record r{};
              r.key = key;
              r.turn = turn;
              r.win = ans.win ? 1 : 0;
              r.best = ans.best_move;
              r.plies = ans.plies;
              buf.push_back(r);
              ++writtenSolved;
              // Optional tree persistence for this root
              if (!treeOut.empty() && (treeTurnOnly < 0 || static_cast<int>(turn) == treeTurnOnly)) {
                std::vector<uint8_t> blob; blob.reserve(1024);
                solver.dump_tree_binary_to_vector(blob);
                std::ofstream ft(treeOut, std::ios::binary | std::ios::app);
                uint64_t key64 = key; uint8_t t = turn; uint32_t sz = static_cast<uint32_t>(blob.size());
                ft.write(reinterpret_cast<const char*>(&key64), sizeof(uint64_t));
                ft.write(reinterpret_cast<const char*>(&t), sizeof(uint8_t));
                ft.write(reinterpret_cast<const char*>(&sz), sizeof(uint32_t));
                if (sz) ft.write(reinterpret_cast<const char*>(blob.data()), sz);
              }
              if (!treeDir.empty() && (treeTurnOnly < 0 || static_cast<int>(turn) == treeTurnOnly)) {
                char name[64];
                char winChar = ans.win ? (turn == 0 ? 'X' : 'O') : (turn == 0 ? 'O' : 'X');
                if (treeTurnOnly == 0) {
                  std::snprintf(name, sizeof(name), "%016llx-%c.bin", static_cast<unsigned long long>(key), winChar);
                } else {
                  std::snprintf(name, sizeof(name), "%016llx-%u-%c.bin", static_cast<unsigned long long>(key), static_cast<unsigned>(turn), winChar);
                }
                auto path = treeDir / name;
                solver.dump_tree_binary(path.string(), key);
              }
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
                        << " elapsed_ms=" << ms << " rate_solved_per_s=" << (ms > 0 ? (writtenSolved * 1000.0 / ms) : 0.0) << "\n";
            }
            // periodic progress
            auto now = std::chrono::high_resolution_clock::now();
            auto since = std::chrono::duration_cast<std::chrono::milliseconds>(now - last).count();
            if (since >= 2000) {
              auto msTotal = std::chrono::duration_cast<std::chrono::milliseconds>(now - t0).count();
              double rate = (msTotal > 0 ? (writtenSolved * 1000.0 / msTotal) : 0.0);
              double pct = 0.0;
              if (limit > 0) {
                pct = (solveTurnOnly >= 0) ? (100.0 * (writtenSolved / static_cast<double>(limit)))
                                           : (100.0 * (produced / static_cast<double>(limit)));
              }
              std::cout << "progress produced=" << produced << " (" << pct << "%)"
                        << " wrote_solved=" << writtenSolved << " wrote_index=" << writtenIndex
                        << " elapsed_ms=" << msTotal << " rate_solved_per_s=" << rate << " flushes=" << flushed << "\n";
              last = now;
            }
            bool hitLimit = false;
            if (limit > 0) {
              hitLimit = (solveTurnOnly >= 0) ? (writtenSolved >= limit) : (produced >= limit);
            }
            if (hitLimit) {
              if (!indexOnly && !buf.empty()) {
                std::ofstream f(out, std::ios::binary | std::ios::app);
                f.write(reinterpret_cast<const char*>(buf.data()), static_cast<std::streamsize>(buf.size() * sizeof(Record)));
              }
              auto t1 = std::chrono::high_resolution_clock::now();
              auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
              std::cout << "DONE produced=" << produced << (indexOnly ? " (index-only)" : "")
                        << " wrote_solved=" << writtenSolved << " wrote_index=" << writtenIndex
                        << " out=" << std::filesystem::absolute(out).string() << " idx=" << std::filesystem::absolute(indexPath).string();
              if (!treeOut.empty()) std::cout << " trees=" << std::filesystem::absolute(treeOut).string();
              std::cout << " elapsed_ms=" << ms << "\n";
              return 0;
            }
          }
          // After finishing both turns for this normalized root, reset solver to cap RAM
          solver = Solver();
          solver.set_capture_edges(false);
          solver.set_collect_root_metrics(true);
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
            << " out=" << std::filesystem::absolute(out).string() << " elapsed_ms=" << ms << "\n";
  return 0;
}


