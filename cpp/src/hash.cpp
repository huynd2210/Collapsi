#include "hash.hpp"

namespace collapsi {

Key64 hash_state(bb_t a, bb_t b2, bb_t b3, bb_t b4, bb_t x, bb_t o, bb_t collapsed, uint8_t turn) {
  uint64_t h = 0;
  uint64_t v[8] = {a, b2, b3, b4, x, o, collapsed, static_cast<uint64_t>(turn)};
  for (int i = 0; i < 8; ++i) {
    h = pair64(h, v[i]);
  }
  return mix64(h);
}

}


