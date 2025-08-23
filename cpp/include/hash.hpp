#pragma once
#include <cstdint>

namespace collapsi {

using bb_t = uint16_t;

using Key64 = uint64_t;

// Szudzik pairing (mod 2^64). Inputs are 64-bit non-negative; we rely on wraparound.
inline uint64_t pair64(uint64_t a, uint64_t b) {
  // (a>=b) ? a*a + a + b : a + b*b
  if (a >= b) {
    return a * a + a + b; // wraps intentionally
  } else {
    return a + b * b;
  }
}

inline uint64_t mix64(uint64_t x) { // SplitMix64
  x += 0x9e3779b97f4a7c15ULL;
  x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
  x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
  x = x ^ (x >> 31);
  return x;
}

Key64 hash_state(bb_t a, bb_t b2, bb_t b3, bb_t b4, bb_t x, bb_t o, bb_t collapsed, uint8_t turn);

struct Key64Hasher {
  size_t operator()(const Key64& k) const noexcept {
    return static_cast<size_t>(mix64(k));
  }
};

}


