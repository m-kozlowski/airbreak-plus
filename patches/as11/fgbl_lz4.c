/* Freestanding memory primitives used by the vendored LZ4 block codec. */

typedef unsigned int usize;
typedef unsigned long uptr;

void *service_lz4_memcpy(void *destination, const void *source, usize length)
{
    unsigned char *dst = destination;
    const unsigned char *src = source;

    while (length-- != 0u) {
        *dst++ = *src++;
    }
    return destination;
}

void *service_lz4_memset(void *destination, int value, usize length)
{
    unsigned char *dst = destination;

    while (length-- != 0u) {
        *dst++ = (unsigned char)value;
    }
    return destination;
}

void *service_lz4_memmove(void *destination, const void *source, usize length)
{
    unsigned char *dst = destination;
    const unsigned char *src = source;

    if ((uptr)dst <= (uptr)src || (uptr)dst >= (uptr)src + length) {
        return service_lz4_memcpy(destination, source, length);
    }
    while (length-- != 0u) {
        dst[length] = src[length];
    }
    return destination;
}

#include "lz4/lz4.c"
