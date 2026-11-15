#ifndef _therapy_worker_h_
#define _therapy_worker_h_

typedef struct therapy_worker therapy_worker;
typedef void (*therapy_worker_method)(therapy_worker *);

// Stock worker prefix: vtable, next pointer and one-byte enable flag.
struct therapy_worker {
  const therapy_worker_method *methods;
  therapy_worker *next;
  unsigned char enabled;
};

extern void *therapy_manager_get(void);
extern void therapy_worker_append(therapy_worker *, int group);

// The manager holds three list heads at +0x08 and three event words at +0x18.
static inline therapy_worker *therapy_worker_first(unsigned group) {
  return ((therapy_worker **)therapy_manager_get())[group + 2];
}

static inline therapy_worker *therapy_worker_find(unsigned group,
                                                 const therapy_worker_method *methods) {
  therapy_worker *node = therapy_worker_first(group);
  while (node && node->methods != methods) { node = node->next; }
  return node;
}

static inline unsigned therapy_worker_events(unsigned group) {
  return ((unsigned *)therapy_manager_get())[group + 6];
}

#endif
