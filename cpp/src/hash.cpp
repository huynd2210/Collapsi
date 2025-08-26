#include "../include/hash.hpp"

namespace collapsi {

Key64 hash_state(bb_t aMask, bb_t twoMask, bb_t threeMask, bb_t fourMask, bb_t xMask, bb_t oMask, bb_t collapsedMask, uint8_t turnValue) {
  uint64_t hashValue = 0;
  uint64_t values[8] = {aMask, twoMask, threeMask, fourMask, xMask, oMask, collapsedMask, static_cast<uint64_t>(turnValue)};
  for (int i = 0; i < 8; ++i) {
    hashValue = pair64(hashValue, values[i]);
  }
  return mix64(hashValue);
}

}


