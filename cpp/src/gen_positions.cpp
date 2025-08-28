#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <set>
#include <string>
#include <tuple>
#include <vector>

#include "../include/bitboard.hpp"
#include "../include/hash.hpp"

using namespace collapsi;
namespace fs = std::filesystem;

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

static std::string key_string(Key64 k, uint8_t turn) {
  char buf[32];
  std::snprintf(buf, sizeof(buf), "%016llx|%u", static_cast<unsigned long long>(k), static_cast<unsigned>(turn));
  return std::string(buf);
}

static std::string sanitize_filename(const std::string& key) {
  std::string s = key;
  std::replace(s.begin(), s.end(), '|', '-');
  return s + ".txt";
}

int main(int argc, char** argv) {
  // Args: [--outdir DIR] [--stride N] [--offset K] [--limit M]
  // Default outdir: Collapsi/data relative to this executable (../../.. from build/Release)
  fs::path exe = fs::absolute(fs::path(argv[0])).parent_path();
  fs::path outdir = exe / ".." / ".." / ".." / "data";
  int stride = 1;
  int offset = 0;
  long long limit = -1;
  auto t0 = std::chrono::high_resolution_clock::now();
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "--outdir" && i + 1 < argc) { outdir = fs::path(argv[++i]); }
    else if (a == "--stride" && i + 1 < argc) { stride = std::max(1, std::atoi(argv[++i])); }
    else if (a == "--offset" && i + 1 < argc) { offset = std::max(0, std::atoi(argv[++i])); }
    else if (a == "--limit" && i + 1 < argc) { limit = std::atoll(argv[++i]); }
  }
  fs::path normDir = outdir / "norm2raw";
  fs::path rawDir = outdir / "raw2norm";
  fs::create_directories(normDir);
  fs::create_directories(rawDir);

  // Precompute all index lists
  std::vector<int> allIdx(16); for (int i = 0; i < 16; ++i) allIdx[i] = i;

  long long processed = 0;
  int j2count = 0;
  for (int oIdx = 1; oIdx < 16; ++oIdx) {
    if ((j2count % stride) != offset) { ++j2count; continue; }
    ++j2count;

    // Choose 4 positions for A among all 16
    std::vector<int> combA;
    combA.reserve(4);
    for (int a0 = 0; a0 < 16; ++a0) for (int a1 = a0 + 1; a1 < 16; ++a1) for (int a2 = a1 + 1; a2 < 16; ++a2) for (int a3 = a2 + 1; a3 < 16; ++a3) {
      std::set<int> A{a0, a1, a2, a3};
      // Choose 4 positions for 2 from remaining
      std::vector<int> rem2; rem2.reserve(12);
      for (int i : allIdx) if (!A.count(i)) rem2.push_back(i);
      for (int i0 = 0; i0 < static_cast<int>(rem2.size()); ++i0)
      for (int i1 = i0 + 1; i1 < static_cast<int>(rem2.size()); ++i1)
      for (int i2 = i1 + 1; i2 < static_cast<int>(rem2.size()); ++i2)
      for (int i3 = i2 + 1; i3 < static_cast<int>(rem2.size()); ++i3) {
        std::set<int> B2{rem2[i0], rem2[i1], rem2[i2], rem2[i3]};
        // Choose 4 positions for 3 from remaining
        std::vector<int> rem3; rem3.reserve(8);
        for (int i : rem2) if (!B2.count(i)) rem3.push_back(i);
        for (int j0 = 0; j0 < static_cast<int>(rem3.size()); ++j0)
        for (int j1 = j0 + 1; j1 < static_cast<int>(rem3.size()); ++j1)
        for (int j2 = j1 + 1; j2 < static_cast<int>(rem3.size()); ++j2)
        for (int j3 = j2 + 1; j3 < static_cast<int>(rem3.size()); ++j3) {
          std::set<int> B3{rem3[j0], rem3[j1], rem3[j2], rem3[j3]};
          // Remaining 4 are 4's
          std::set<int> Four;
          for (int i : allIdx) if (!A.count(i) && !B2.count(i) && !B3.count(i)) Four.insert(i);

          // Build bitboards for raw state with X at 0 and O at oIdx
          bb_t aMask = 0, twoMask = 0, threeMask = 0, fourMask = 0, xMask = 0, oMask = 0, collMask = 0;
          for (int i : A) aMask |= static_cast<bb_t>(1) << i;
          for (int i : B2) twoMask |= static_cast<bb_t>(1) << i;
          for (int i : B3) threeMask |= static_cast<bb_t>(1) << i;
          for (int i : Four) fourMask |= static_cast<bb_t>(1) << i;
          xMask = static_cast<bb_t>(1) << 0;
          oMask = static_cast<bb_t>(1) << oIdx;
          // raw keys for both turns
          Key64 rawKeyT0 = hash_state(aMask, twoMask, threeMask, fourMask, xMask, oMask, collMask, /*turn*/0);
          Key64 rawKeyT1 = hash_state(aMask, twoMask, threeMask, fourMask, xMask, oMask, collMask, /*turn*/1);

          // Normalized by shifting X to (0,0): here X already at 0,0, so canonical norm is identity
          // But we also want to gather all 16 torus shifts mapping to same norm
          std::vector<std::pair<std::string, std::string>> pairs; // raw->norm for both turns
          std::string normKeyT0 = key_string(hash_state(aMask, twoMask, threeMask, fourMask, xMask, oMask, collMask, 0), 0);
          std::string normKeyT1 = key_string(hash_state(aMask, twoMask, threeMask, fourMask, xMask, oMask, collMask, 1), 1);

          // Generate all 16 shifts (dr,dc) to produce raw variants mapping back to these normalized keys
          for (int dr = 0; dr < 4; ++dr) for (int dc = 0; dc < 4; ++dc) {
            bb_t aS = shift_mask(aMask, dr, dc);
            bb_t b2S = shift_mask(twoMask, dr, dc);
            bb_t b3S = shift_mask(threeMask, dr, dc);
            bb_t b4S = shift_mask(fourMask, dr, dc);
            bb_t xS = shift_mask(xMask, dr, dc);
            bb_t oS = shift_mask(oMask, dr, dc);
            Key64 rk0 = hash_state(aS, b2S, b3S, b4S, xS, oS, collMask, 0);
            Key64 rk1 = hash_state(aS, b2S, b3S, b4S, xS, oS, collMask, 1);
            pairs.emplace_back(key_string(rk0, 0), normKeyT0);
            pairs.emplace_back(key_string(rk1, 1), normKeyT1);
          }

          // Write mapping files
          std::string normFile0 = sanitize_filename(normKeyT0);
          std::string normFile1 = sanitize_filename(normKeyT1);
          std::ofstream nf0((normDir / normFile0).string(), std::ios::app);
          std::ofstream nf1((normDir / normFile1).string(), std::ios::app);
          for (const auto& pr : pairs) {
            const std::string& rawK = pr.first;
            const std::string& nK = pr.second;
            // Append raw to norm list
            if (nK == normKeyT0 && nf0.good()) nf0 << rawK << "\n";
            if (nK == normKeyT1 && nf1.good()) nf1 << rawK << "\n";
            // Write raw->norm
            std::ofstream rf((rawDir / sanitize_filename(rawK)).string(), std::ios::trunc);
            if (rf.good()) rf << nK;
          }

          ++processed;
          if (limit > 0 && processed >= limit) {
            std::cout << "Processed=" << processed << "\n";
            return 0;
          }
        }
      }
    }
  }
  auto t1 = std::chrono::high_resolution_clock::now();
  auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
  std::cout << "Processed=" << processed << " outdir=" << fs::absolute(outdir).string() << " elapsed_ms=" << ms << " rate_per_s=" << (ms > 0 ? (processed * 1000.0 / ms) : 0.0) << "\n";
  return 0;
}


