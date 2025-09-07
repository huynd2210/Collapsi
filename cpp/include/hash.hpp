#pragma once
#include <cstdint>
#include <cstddef> // for size_t

namespace collapsi {

using bb_t = uint16_t;

using Key64 = uint64_t;

// Szudzik pairing (mod 2^64). Inputs are 64-bit non-negative; we rely on wraparound.
inline uint64_t pair64(uint64_t left, uint64_t right) {
  // (left>=right) ? left*left + left + right : left + right*right
  if (left >= right) {
    return left * left + left + right; // wraps intentionally
  } else {
    return left + right * right;
  }
}

inline uint64_t mix64(uint64_t value) { // SplitMix64
  value += 0x9e3779b97f4a7c15ULL;
  value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9ULL;
  value = (value ^ (value >> 27)) * 0x94d049bb133111ebULL;
  value = value ^ (value >> 31);
  return value;
}

Key64 hash_state(bb_t aMask, bb_t twoMask, bb_t threeMask, bb_t fourMask, bb_t xMask, bb_t oMask, bb_t collapsedMask, uint8_t turnValue);

struct Key64Hasher {
  size_t operator()(const Key64& key) const noexcept {
    return static_cast<size_t>(mix64(key));
  }
};

}


