#include "common_code.h"
#include "stubs.h"

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



typedef struct {
  unsigned magic;
  void** pointers;
} magic_ptr_t;

// NSTUB defines magic_ptr as an absolute symbol at the RAM address.
extern magic_ptr_t magic_ptr __attribute__((section(".absolute")));
#define magic_ptr_p (&magic_ptr)
const unsigned MAGIC = 0x07E49001;

void *get_pointer(ptr_index index, int size, void (*init_fn)(void*)) {
  const int max_pointers = __PTR_LAST;
  if (magic_ptr_p->magic != MAGIC) {
    magic_ptr_p->pointers = malloc(sizeof(void*) * max_pointers);
    magic_ptr_p->magic = MAGIC;
    for(int i=0; i<max_pointers; i++) {
      magic_ptr_p->pointers[i] = 0;
    }
  }
  if (magic_ptr_p->pointers[index] == 0) {
    magic_ptr_p->pointers[index] = malloc(size);
    init_fn(magic_ptr_p->pointers[index]);
  }
  return magic_ptr_p->pointers[index];
}
