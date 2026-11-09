#include "common_code.h"

float remap(float s, float start, float end, float new_start, float new_end) {
  return new_start + remap01(s, start, end) * (new_end - new_start);
}

float remapc(float s, float start, float end, float new_start, float new_end) {
  return new_start + remap01c(s, start, end) * (new_end - new_start);
}

float remap01(float s, float start, float end) {
   return (s - start)/(end-start);
}

float remap01c(float s, float start, float end) {
   return clamp( remap01(s, start, end), 0.0f, 1.0f );
}

float lerp(float from, float to, float coeff) {
   return from + (to - from) * coeff;
}
