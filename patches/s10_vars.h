#ifndef S10_VARS_H
#define S10_VARS_H

#if defined(CDX_VER_0302)
#include "s10_vars_0302.h"
#elif defined(CDX_VER_0305)
#include "s10_vars_0305.h"
#elif defined(CDX_VER_0306)
#include "s10_vars_0306.h"
#elif defined(CDX_VER_0401)
#include "s10_vars_0401.h"
#elif defined(CDX_VER_0402)
#include "s10_vars_0402.h"
#else
#error "Unsupported S10 CDX version"
#endif

#endif
