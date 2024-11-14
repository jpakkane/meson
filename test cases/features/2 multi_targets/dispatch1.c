#include "dispatch.h"

const char *DISPATCH_CURRENT(dispatch1)()
{
#ifdef HAVE_SSSE3
    #ifndef HAVE_SSE3
        #error "expected a defention for implied features"
    #endif
    #ifndef HAVE_SSE2
        #error "expected a defention for implied features"
    #endif
    #ifndef HAVE_SSE
        #error "expected a defention for implied features"
    #endif
#endif
#ifdef HAVE_ASIMD
    #ifndef HAVE_NEON
        #error "expected a defention for implied features"
    #endif
    #ifndef HAVE_NEON_FP16
        #error "expected a defention for implied features"
    #endif
    #ifndef HAVE_NEON_VFPV4
        #error "expected a defention for implied features"
    #endif
#endif
    return TOSTRING(DISPATCH_CURRENT(dispatch1));
}
