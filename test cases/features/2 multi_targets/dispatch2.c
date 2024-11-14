#include "dispatch.h"

const char *DISPATCH_CURRENT(dispatch2)()
{
#ifdef HAVE_SSE41
    #ifndef HAVE_SSSE3
        #error "expected a defention for implied features"
    #endif
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
    return TOSTRING(DISPATCH_CURRENT(dispatch2));
}

