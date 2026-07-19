#ifndef AS11_VARS_H
#define AS11_VARS_H

#if defined(APPX_VER_8_0_1)
#include "vars_8_0_1.h"
#elif defined(APPX_VER_8_3_0)
#include "vars_8_3_0.h"
#elif defined(APPX_VER_8_4_0)
#include "vars_8_4_0.h"
#elif defined(APPX_VER_8_5_0)
#include "vars_8_5_0.h"
#else
#error "Unsupported Air11 APPX version"
#endif

#endif
