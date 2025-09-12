#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <string>
#include <tuple>
#include <vector>
#include <chrono>
#include <unordered_set>
#include <limits>

#include "../include/bitboard.hpp"
#include "../include/hash.hpp"

using namespace collapsi;
namespace fs = std::filesystem;

static inline uint8_t rc_to_idx4(uint8_t r, uint8_t c) { return static_cast<uint8_t>((r & 3u) * 4u + (c & 3u)); }

#pragma pack(push, 1)
struct IdxRec {
  uint64_t key;   // normalized key
  uint8_t  turn;  // 0 X, 1 O
  uint16_t a;
  uint16_t b2;
  uint16_t b3;
  uint16_t b4;
  uint16_t x;
  uint16_t o;
  uint16_t c;
  uint8_t  pad;   // keep alignment at 24 bytes
};
#pragma pack(pop)

struct DBRec16 {
  uint64_t key;
  uint8_t  turn;
  uint8_t  win;
  uint8_t  best;
  uint16_t plies;
  uint8_t  pad[4];
};

struct KeyTurn {
  uint64_t key;
  uint8_t  turn;
  bool operator==(const KeyTurn& other) const noexcept { return key == other.key && turn == other.turn; }
};
struct KeyTurnHash {
  size_t operator()(const KeyTurn& kt) const noexcept {
    uint64_t x = kt.key ^ (static_cast<uint64_t>(kt.turn) * 0x9e3779b97f4a7c15ULL);
    // SplitMix64
    x ^= x >> 30; x *= 0xbf58476d1ce4e5b9ULL;
    x ^= x >> 27; x *= 0x94d049bb133111ebULL;
    x ^= x >> 31;
    return static_cast<size_t>(x);
  }
};

static uint64_t truncate_to_multiple_and_count(const fs::path& path, uint64_t recordSize) {
  std::error_code ec;
  if (!fs::exists(path, ec)) return 0;
  uint64_t size = static_cast<uint64_t>(fs::file_size(path, ec));
  if (ec || recordSize == 0) return 0;
  uint64_t remainder = size % recordSize;
  if (remainder != 0) {
    uint64_t newSize = size - remainder;
    fs::resize_file(path, newSize, ec);
  }
  std::error_code ec2;
  uint64_t finalSize = static_cast<uint64_t>(fs::file_size(path, ec2));
  return (recordSize ? (finalSize / recordSize) : 0);
}

static int detect_rec_size(const fs::path& dbPath) {
  std::error_code ec;
  if (!fs::exists(dbPath, ec)) return 24;
  uint64_t size = static_cast<uint64_t>(fs::file_size(dbPath, ec));
  if (ec) return 24;
  // Prefer 24-byte layout when both divide evenly; it is the common shipped format
  if (size % 24 == 0) return 24;
  if (size % 16 == 0) return 16;
  // Fallback to 24 to be tolerant with mixed packs (we'll tolerate by reading only key+turn)
  return 24;
}

static void load_solved_keys(const fs::path& dbPath, std::unordered_set<KeyTurn, KeyTurnHash>& out) {
  int recSize = detect_rec_size(dbPath);
  std::ifstream f(dbPath, std::ios::binary);
  if (!f.good()) {
    std::cerr << "gen_index: cannot open solved db: " << dbPath.string() << "\n";
    return;
  }
  if (recSize == 16) {
    while (true) {
      DBRec16 r{};
      if (!f.read(reinterpret_cast<char*>(&r), sizeof(r))) break;
      if (r.key == 0) continue;
      if (r.turn > 1) continue; // drop implausible
      out.insert(KeyTurn{r.key, r.turn});
    }
  } else {
    // 24-byte tolerant: read 8+1 then skip
    while (true) {
      uint64_t key = 0;
      uint8_t turn = 0;
      if (!f.read(reinterpret_cast<char*>(&key), sizeof(key))) break;
      if (!f.read(reinterpret_cast<char*>(&turn), sizeof(turn))) break;
      // Skip remaining bytes in record
      f.seekg(recSize - (sizeof(key) + sizeof(turn)), std::ios::cur);
      if (key == 0) continue;
      if (turn > 1) continue; // drop implausible
      out.insert(KeyTurn{key, turn});
    }
  }
}

static inline char card_char(uint16_t a, uint16_t b2, uint16_t b3, uint16_t b4, uint8_t idx) {
  uint16_t bit = static_cast<uint16_t>(1) << idx;
  if (a  & bit) return 'A';
  if (b2 & bit) return '2';
  if (b3 & bit) return '3';
  if (b4 & bit) return '4';
  return '.';
}

static std::string format_hms(long long ms) {
  long long total_s = ms / 1000;
  long long h = total_s / 3600;
  long long m = (total_s % 3600) / 60;
  long long s = total_s % 60;
  char buf[32];
  std::snprintf(buf, sizeof(buf), "%02lld:%02lld:%02lld", h, m, s);
  return std::string(buf);
}

int main(int argc, char** argv) {
  // Args: --db FILE --out FILE [--stride N] [--offset K]
  fs::path exeDir = fs::absolute(fs::path(argv[0])).parent_path();
  fs::path dbPath = exeDir / ".." / ".." / ".." / "data" / "solved_norm.db";
  fs::path outPath = exeDir / ".." / ".." / ".." / "data" / "norm_index.db";
  int stride = 1;
  int offset = 0;

  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "--db" && i + 1 < argc) dbPath = fs::path(argv[++i]);
    else if (a == "--out" && i + 1 < argc) outPath = fs::path(argv[++i]);
    else if (a == "--stride" && i + 1 < argc) stride = std::max(1, std::atoi(argv[++i]));
    else if (a == "--offset" && i + 1 < argc) offset = std::max(0, std::atoi(argv[++i]));
  }

  dbPath = fs::absolute(dbPath);
  outPath = fs::absolute(outPath);
  fs::create_directories(outPath.parent_path());

  // Build "wanted" set from solved DB and subtract already indexed from index file (resume)
  std::unordered_set<KeyTurn, KeyTurnHash> wanted;
  load_solved_keys(dbPath, wanted);
  if (wanted.empty()) {
    std::cerr << "gen_index: no keys loaded from " << dbPath.string() << "\n";
    return 0;
  }

  // Remove already present entries (resume-safe)
  {
    std::ifstream idxIn(outPath, std::ios::binary);
    if (idxIn.good()) {
      while (true) {
        IdxRec rec{};
        if (!idxIn.read(reinterpret_cast<char*>(&rec), sizeof(rec))) break;
        wanted.erase(KeyTurn{rec.key, rec.turn});
      }
    }
  }
  if (wanted.empty()) {
    std::cout << "gen_index: nothing to do; index already covers DB\n";
    return 0;
  }

  std::ofstream out(outPath, std::ios::binary | std::ios::app);
  if (!out.good()) {
    std::cerr << "gen_index: cannot open index for append: " << outPath.string() << "\n";
    return 2;
  }

  auto t0 = std::chrono::high_resolution_clock::now();
  auto last = t0;
  uint64_t written = 0;
  uint64_t checked = 0;

  // Enumerate canonical normalized grids: X at 0; O at any 1..15; choose positions for A,2,3; remaining are 4
  // Note: This is a large enumeration (canonical state space). We short-circuit writing only when key exists in DB.
  std::vector<int> allIdx(16); for (int i = 0; i < 16; ++i) allIdx[i] = i;

  int j2count = 0;
  for (int oIdx = 1; oIdx < 16; ++oIdx) {
    // choose A=4 positions
    for (int a0 = 0; a0 < 16; ++a0)
    for (int a1 = a0 + 1; a1 < 16; ++a1)
    for (int a2 = a1 + 1; a2 < 16; ++a2)
    for (int a3 = a2 + 1; a3 < 16; ++a3) {
      std::set<int> A{a0, a1, a2, a3};
      // choose 2s
      std::vector<int> rem2; rem2.reserve(12);
      for (int i : allIdx) if (!A.count(i)) rem2.push_back(i);
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
          // remaining 4 are 4's
          uint16_t aMask = 0, twoMask = 0, threeMask = 0, fourMask = 0;
          for (int i : A) aMask |= static_cast<uint16_t>(1) << i;
          for (int i : B2) twoMask |= static_cast<uint16_t>(1) << i;
          for (int i : B3) threeMask |= static_cast<uint16_t>(1) << i;
          for (int i = 0; i < 16; ++i) if (!A.count(i) && !B2.count(i) && !B3.count(i)) fourMask |= static_cast<uint16_t>(1) << i;

          uint16_t xMask = static_cast<uint16_t>(1) << 0;
          uint16_t oMask = static_cast<uint16_t>(1) << oIdx;
          uint16_t collMask = 0;

          // compute for both turns
          for (uint8_t turn = 0; turn <= 1; ++turn) {
            Key64 key = hash_state(aMask, twoMask, threeMask, fourMask, xMask, oMask, collMask, turn);
            ++checked;
            if (stride > 1) {
              if ((key % static_cast<uint64_t>(stride)) != static_cast<uint64_t>(offset)) continue;
            }
            KeyTurn kt{static_cast<uint64_t>(key), turn};
            if (wanted.find(kt) != wanted.end()) {
              IdxRec rec{};
              rec.key = static_cast<uint64_t>(key);
              rec.turn = turn;
              rec.a = aMask;
              rec.b2 = twoMask;
              rec.b3 = threeMask;
              rec.b4 = fourMask;
              rec.x = xMask;
              rec.o = oMask;
              rec.c = collMask;
              rec.pad = 0;
              out.write(reinterpret_cast<const char*>(&rec), sizeof(rec));
              wanted.erase(kt);
              ++written;
              if (written % 100000 == 0) out.flush();
            }
          }

          // Progress log every so often
          auto now = std::chrono::high_resolution_clock::now();
          auto since = std::chrono::duration_cast<std::chrono::milliseconds>(now - last).count();
          if (since >= 5000) {
            auto msTotal = std::chrono::duration_cast<std::chrono::milliseconds>(now - t0).count();
            std::cout << "gen_index progress written=" << written
                      << " remaining=" << wanted.size()
                      << " elapsed=" << format_hms(msTotal)
                      << " out=" << fs::absolute(outPath).string()
                      << "\n";
            last = now;
          }

          if (wanted.empty()) {
            out.flush();
            auto msTotal = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::high_resolution_clock::now() - t0).count();
            std::cout << "gen_index DONE written=" << written << " elapsed=" << format_hms(msTotal)
                      << " out=" << fs::absolute(outPath).string() << "\n";
            return 0;
          }
        }
      }
    }
  }

  out.flush();
  auto msTotal = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::high_resolution_clock::now() - t0).count();
  std::cout << "gen_index FINISHED written=" << written << " still_missing=" << wanted.size()
            << " elapsed=" << format_hms(msTotal)
            << " out=" << fs::absolute(outPath).string() << "\n";
  return 0;
}