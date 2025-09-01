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
#include <cmath>

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

struct KeyTurn {
  uint64_t key;
  uint8_t turn;
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

// duplicate, keep single definition above

static std::string format_hms(long long ms) {
  long long total_s = ms / 1000;
  long long h = total_s / 3600;
  long long m = (total_s % 3600) / 60;
  long long s = total_s % 60;
  char buf[32];
  std::snprintf(buf, sizeof(buf), "%02lld:%02lld:%02lld", h, m, s);
  return std::string(buf);
}

struct BatchMetrics {
  size_t count;
  size_t zero_keys;
  size_t bad_move;
  size_t plies_anom;
  size_t wins1;
  size_t wins0;
  size_t turn0;
  size_t turn1;
  long long plies_sum;
  uint16_t min_plies;
  uint16_t max_plies;
};

static inline bool best_ok(uint8_t b) {
  if (b == 0xFF) return true;
  uint8_t f = (b >> 4) & 0x0F;
  uint8_t t = b & 0x0F;
  return f < 16 && t < 16;
}

static BatchMetrics analyze_batch(const std::vector<Record>& v) {
  BatchMetrics m{};
  m.count = v.size();
  m.zero_keys = 0;
  m.bad_move = 0;
  m.plies_anom = 0;
  m.wins1 = 0;
  m.wins0 = 0;
  m.turn0 = 0;
  m.turn1 = 0;
  m.plies_sum = 0;
  m.min_plies = std::numeric_limits<uint16_t>::max();
  m.max_plies = 0;
  for (const auto& r : v) {
    if (r.key == 0) ++m.zero_keys;
    if (!best_ok(r.best)) ++m.bad_move;
    if (!(r.plies <= 50)) ++m.plies_anom; // 0..50 expected for 4x4
    if (r.win == 1 && r.plies < 1) ++m.plies_anom;
    if (r.win == 0 && r.plies < 0) ++m.plies_anom; // defensive; plies is unsigned anyway
    if (r.turn == 0) ++m.turn0; else if (r.turn == 1) ++m.turn1;
    if (r.win == 1) ++m.wins1; else if (r.win == 0) ++m.wins0;
    m.plies_sum += r.plies;
    if (r.plies < m.min_plies) m.min_plies = r.plies;
    if (r.plies > m.max_plies) m.max_plies = r.plies;
  }
  if (m.count == 0) {
    m.min_plies = 0;
    m.max_plies = 0;
  }
  return m;
}

static int dedup_database(const fs::path& dbPath) {
  const uint64_t recSize = static_cast<uint64_t>(sizeof(Record));
  if (!fs::exists(dbPath)) {
    std::cerr << "dedup: missing file: " << dbPath.string() << "\n";
    return 1;
  }
  fs::path tmpPath = dbPath; tmpPath += ".dedup";
  fs::path bakPath = dbPath; bakPath += ".bak";
  std::unordered_set<KeyTurn, KeyTurnHash> seen;
  std::ifstream in(dbPath, std::ios::binary);
  std::ofstream out(tmpPath, std::ios::binary | std::ios::trunc);
  if (!in.good() || !out.good()) {
    std::cerr << "dedup: cannot open files\n";
    return 2;
  }
  uint64_t read = 0, written = 0, dups = 0;
  while (true) {
    Record r{};
    if (!in.read(reinterpret_cast<char*>(&r), sizeof(r))) break;
    ++read;
    KeyTurn kt{r.key, r.turn};
    if (!seen.insert(kt).second) { ++dups; continue; }
    out.write(reinterpret_cast<const char*>(&r), sizeof(r));
    ++written;
  }
  in.close(); out.close();
  std::error_code ec;
  fs::rename(dbPath, bakPath, ec);
  if (ec) {
    std::cerr << "dedup: rename to .bak failed: " << ec.message() << "\n";
    return 3;
  }
  fs::rename(tmpPath, dbPath, ec);
  if (ec) {
    std::cerr << "dedup: rename dedup -> db failed: " << ec.message() << "\n";
    return 4;
  }
  std::cout << "dedup DONE read=" << read << " wrote=" << written << " duplicates=" << dups
            << " out=" << fs::absolute(dbPath).string() << " bak=" << fs::absolute(bakPath).string() << "\n";
  return 0;
}

static uint64_t load_seen_from_db(const fs::path& dbPath, std::unordered_set<KeyTurn, KeyTurnHash>& seen) {
  std::ifstream f(dbPath, std::ios::binary);
  if (!f.good()) return 0;
  uint64_t loaded = 0;
  while (true) {
    Record r{};
    if (!f.read(reinterpret_cast<char*>(&r), sizeof(r))) break;
    seen.insert(KeyTurn{r.key, r.turn});
    ++loaded;
  }
  return loaded;
}

static uint64_t load_seen_from_index(const fs::path& idxPath, std::unordered_set<KeyTurn, KeyTurnHash>& seen) {
  std::ifstream f(idxPath, std::ios::binary);
  if (!f.good()) return 0;
  uint64_t loaded = 0;
  while (true) {
    KeyTurn kt{0, 0};
    if (!f.read(reinterpret_cast<char*>(&kt.key), sizeof(uint64_t))) break;
    if (!f.read(reinterpret_cast<char*>(&kt.turn), sizeof(uint8_t))) break;
    seen.insert(kt);
    ++loaded;
  }
  return loaded;
}

static void append_seen_index(const fs::path& idxPath, const std::vector<KeyTurn>& newSeen) {
  if (newSeen.empty()) return;
  std::ofstream f(idxPath, std::ios::binary | std::ios::app);
  for (const auto& kt : newSeen) {
    f.write(reinterpret_cast<const char*>(&kt.key), sizeof(uint64_t));
    f.write(reinterpret_cast<const char*>(&kt.turn), sizeof(uint8_t));
  }
}

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

int main(int argc, char** argv) {
  // Args: [--out FILE] [--stride N] [--offset K] [--limit M] [--batch B] [--dumpdir DIR]
  fs::path exeDir = fs::absolute(fs::path(argv[0])).parent_path();
  fs::path out = exeDir / ".." / ".." / ".." / "data" / "solved_norm.db";
  fs::path dumpdir; // empty means no dumps
  std::vector<fs::path> seenPaths; // additional DBs to preload seen from
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
    else if (a == "--seen" && i + 1 < argc) { seenPaths.push_back(fs::path(argv[++i])); }
  }
  if (argc >= 2 && std::string(argv[1]) == "--dedup") {
    fs::path target = (argc >= 3 ? fs::path(argv[2]) : out);
    target = fs::absolute(target);
    return dedup_database(target);
  }
  // Canonicalize output path to avoid accidental writes to a different DB due to CWD
  out = fs::absolute(out);
  fs::create_directories(out.parent_path());
  if (!dumpdir.empty()) fs::create_directories(dumpdir);

  auto t0 = std::chrono::high_resolution_clock::now();
  auto last = t0;
  std::vector<Record> buf; buf.reserve(batch);
  const uint64_t recSize = static_cast<uint64_t>(sizeof(Record));
  const uint64_t existingCount = truncate_to_multiple_and_count(out, recSize);
  std::cout << "resume existing_records=" << existingCount << "\n";
  std::unordered_set<KeyTurn, KeyTurnHash> seen;
  uint64_t preloaded = 0;
  preloaded += load_seen_from_db(out, seen);
  for (const auto& sp : seenPaths) {
    preloaded += load_seen_from_db(fs::absolute(sp), seen);
  }
  std::cout << "loaded_seen=" << preloaded << "\n";
  long long produced = 0; // number of newly written records this run
  long long flushed = 0;
  long long cum_wins1 = 0;      // cumulative wins across flushed batches
  long long cum_plies_sum = 0;  // cumulative plies sum across flushed batches

  Solver solver;
  solver.set_capture_edges(!dumpdir.empty()); // capture edges only if dumping trees
  solver.set_collect_root_metrics(true);

  // Enumerate canonical normalized grids: X at 0; O at any 1..15; choose positions for A,2,3; remaining are 4
  for (int oIdx = 1; oIdx < 16; ++oIdx) {
    std::cout << "oIdx=" << oIdx << "/15 produced=" << produced << "\n";
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
            Key64 key = hash_state(aMask, twoMask, threeMask, fourMask, xMask, oMask, collMask, turn);
            if (stride > 1 && (key % static_cast<uint64_t>(stride)) != static_cast<uint64_t>(offset)) {
              continue; // key-based sharding to avoid cross-shard duplicates
            }
            KeyTurn kt{key, turn};
            if (seen.find(kt) != seen.end()) {
              continue; // already have this record
            }
            BitState s{aMask, twoMask, threeMask, fourMask, xMask, oMask, collMask, turn};
            Answer ans = solver.solve(s);
            Record r{};
            r.key = key;
            r.turn = turn;
            r.win = ans.win ? 1 : 0;
            r.best = ans.best_move;
            r.plies = ans.plies;
            buf.push_back(r);
            ++produced;
            seen.insert(kt);
            // Optionally dump full solved tree for this root, then clear caches
            if (!dumpdir.empty()) {
              char name[64];
              std::snprintf(name, sizeof(name), "%016llx-%u.bin", static_cast<unsigned long long>(key), static_cast<unsigned>(turn));
              fs::path binpath = dumpdir / name;
              solver.dump_tree_binary(binpath.string(), key);
            }
            solver.clear_cache();
            if (buf.size() >= batch) {
              // Analyze current batch before flushing to disk
              BatchMetrics bm = analyze_batch(buf);
              long long prior = produced - static_cast<long long>(bm.count);
              double baseline_win = (prior > 0 ? (static_cast<double>(cum_wins1) / static_cast<double>(prior)) : -1.0);
              double batch_win = (bm.count > 0 ? (static_cast<double>(bm.wins1) / static_cast<double>(bm.count)) : 0.0);
              double drift = (baseline_win >= 0.0 ? std::fabs(batch_win - baseline_win) : 0.0);
              bool anomaly = (bm.zero_keys > 0) || (bm.bad_move > 0) || (bm.plies_anom > 0) || ((prior >= 10000) && (drift > 0.2));

              // Flush to disk
              std::ofstream f(out, std::ios::binary | std::ios::app);
              f.write(reinterpret_cast<const char*>(buf.data()), static_cast<std::streamsize>(buf.size() * sizeof(Record)));
              f.flush();

              // Update cumulative stats
              cum_wins1 += static_cast<long long>(bm.wins1);
              cum_plies_sum += static_cast<long long>(bm.plies_sum);

              // Clear buffer and report
              buf.clear();
              auto t1 = std::chrono::high_resolution_clock::now();
              auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
              ++flushed;
              long long made = produced;
              double rate = (ms > 0 ? (made * 1000.0 / ms) : 0.0);
              double pct = (limit > 0 ? (100.0 * made / limit) : 0.0);
              double eta_s = (rate > 0.0 && limit > 0 ? (limit - made) / rate : -1.0);
              long long eta_ms = (eta_s >= 0 ? static_cast<long long>(eta_s * 1000.0) : -1);

              std::cout << "flush flushes=" << flushed
                        << " produced=" << made
                        << " elapsed=" << format_hms(ms)
                        << " rate_per_s=" << rate
                        << " pct=" << pct
                        << (eta_ms >= 0 ? (std::string(" eta=") + format_hms(eta_ms)) : std::string(""))
                        << "\n";

              std::cout << "health produced=" << made
                        << " batch_n=" << bm.count
                        << " win_rate=" << batch_win
                        << " avg_plies=" << (bm.count ? (static_cast<double>(bm.plies_sum) / static_cast<double>(bm.count)) : 0.0)
                        << " min_plies=" << bm.min_plies
                        << " max_plies=" << bm.max_plies
                        << " t0=" << bm.turn0
                        << " t1=" << bm.turn1
                        << " zero_keys=" << bm.zero_keys
                        << " bad_move=" << bm.bad_move
                        << " plies_anom=" << bm.plies_anom
                        << " drift_win_rate=" << drift
                        << " status=" << (anomaly ? "ANOMALY" : "OK")
                        << "\n";
            }
            // periodic progress
            auto now = std::chrono::high_resolution_clock::now();
            auto since = std::chrono::duration_cast<std::chrono::milliseconds>(now - last).count();
            if (since >= 2000) {
              auto msTotal = std::chrono::duration_cast<std::chrono::milliseconds>(now - t0).count();
              long long made = produced;
              double rate = (msTotal > 0 ? (made * 1000.0 / msTotal) : 0.0);
              double pct = (limit > 0 ? (100.0 * made / limit) : 0.0);
              double eta_s = (rate > 0.0 && limit > 0 ? (limit - made) / rate : -1.0);
              long long eta_ms = (eta_s >= 0 ? static_cast<long long>(eta_s * 1000.0) : -1);
              std::cout << "progress produced=" << made
                        << " (" << pct << "%)"
                        << " elapsed=" << format_hms(msTotal)
                        << " rate_per_s=" << rate
                        << (eta_ms >= 0 ? (std::string(" eta=") + format_hms(eta_ms)) : std::string(""))
                        << " flushes=" << flushed << "\n";
              last = now;
            }
            if (limit > 0 && produced >= limit) {
              if (!buf.empty()) {
                BatchMetrics bm = analyze_batch(buf);
                long long prior = produced - static_cast<long long>(bm.count);
                double baseline_win = (prior > 0 ? (static_cast<double>(cum_wins1) / static_cast<double>(prior)) : -1.0);
                double batch_win = (bm.count > 0 ? (static_cast<double>(bm.wins1) / static_cast<double>(bm.count)) : 0.0);
                double drift = (baseline_win >= 0.0 ? std::fabs(batch_win - baseline_win) : 0.0);
                bool anomaly = (bm.zero_keys > 0) || (bm.bad_move > 0) || (bm.plies_anom > 0) || ((prior >= 10000) && (drift > 0.2));

                std::ofstream f(out, std::ios::binary | std::ios::app);
                f.write(reinterpret_cast<const char*>(buf.data()), static_cast<std::streamsize>(buf.size() * sizeof(Record)));

                // Update cumulative stats for the final partial batch
                cum_wins1 += static_cast<long long>(bm.wins1);
                cum_plies_sum += static_cast<long long>(bm.plies_sum);

                std::cout << "health produced=" << produced
                          << " batch_n=" << bm.count
                          << " win_rate=" << batch_win
                          << " avg_plies=" << (bm.count ? (static_cast<double>(bm.plies_sum) / static_cast<double>(bm.count)) : 0.0)
                          << " min_plies=" << bm.min_plies
                          << " max_plies=" << bm.max_plies
                          << " t0=" << bm.turn0
                          << " t1=" << bm.turn1
                          << " zero_keys=" << bm.zero_keys
                          << " bad_move=" << bm.bad_move
                          << " plies_anom=" << bm.plies_anom
                          << " drift_win_rate=" << drift
                          << " status=" << (anomaly ? "ANOMALY" : "OK")
                          << "\n";
              }
              auto t1 = std::chrono::high_resolution_clock::now();
              auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
              long long made = produced;
              double rate = (ms > 0 ? (made * 1000.0 / ms) : 0.0);
              std::cout << "DONE produced=" << made << " out=" << fs::absolute(out).string() << " elapsed=" << format_hms(ms) << " rate_per_s=" << rate << "\n";
              return 0;
            }
          }
        }
      }
    }
  }
  if (!buf.empty()) {
    BatchMetrics bm = analyze_batch(buf);
    long long prior = produced - static_cast<long long>(bm.count);
    double baseline_win = (prior > 0 ? (static_cast<double>(cum_wins1) / static_cast<double>(prior)) : -1.0);
    double batch_win = (bm.count > 0 ? (static_cast<double>(bm.wins1) / static_cast<double>(bm.count)) : 0.0);
    double drift = (baseline_win >= 0.0 ? std::fabs(batch_win - baseline_win) : 0.0);
    bool anomaly = (bm.zero_keys > 0) || (bm.bad_move > 0) || (bm.plies_anom > 0) || ((prior >= 10000) && (drift > 0.2));

    std::ofstream f(out, std::ios::binary | std::ios::app);
    f.write(reinterpret_cast<const char*>(buf.data()), static_cast<std::streamsize>(buf.size() * sizeof(Record)));
    f.flush();

    cum_wins1 += static_cast<long long>(bm.wins1);
    cum_plies_sum += static_cast<long long>(bm.plies_sum);

    std::cout << "health produced=" << produced
              << " batch_n=" << bm.count
              << " win_rate=" << batch_win
              << " avg_plies=" << (bm.count ? (static_cast<double>(bm.plies_sum) / static_cast<double>(bm.count)) : 0.0)
              << " min_plies=" << bm.min_plies
              << " max_plies=" << bm.max_plies
              << " t0=" << bm.turn0
              << " t1=" << bm.turn1
              << " zero_keys=" << bm.zero_keys
              << " bad_move=" << bm.bad_move
              << " plies_anom=" << bm.plies_anom
              << " drift_win_rate=" << drift
              << " status=" << (anomaly ? "ANOMALY" : "OK")
              << "\n";
  }
  auto t1 = std::chrono::high_resolution_clock::now();
  auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
  long long made = produced;
  double rate = (ms > 0 ? (made * 1000.0 / ms) : 0.0);
  std::cout << "DONE produced=" << made << " out=" << fs::absolute(out).string() << " elapsed=" << format_hms(ms) << " rate_per_s=" << rate << "\n";
  return 0;
}


