// the headers files of enabled CPU features
#ifdef HAVE_SSE
    #include <xmmintrin.h>
#endif
#ifdef HAVE_SSE2
    #include <emmintrin.h>
#endif
#ifdef HAVE_SSE3
    #include <pmmintrin.h>
#endif
#ifdef HAVE_SSSE3
    #include <tmmintrin.h>
#endif
#ifdef HAVE_SSE41
    #include <smmintrin.h>
#endif
#ifdef HAVE_NEON
    #include <arm_neon.h>
#endif

int main() {
#if defined( __i386__ ) || defined(i386) || defined(_M_IX86) || \
    defined(__x86_64__) || defined(__amd64__) || defined(__x86_64) || defined(_M_AMD64)
    #ifndef HAVE_SSE
        #error "expected SSE to be enabled"
    #endif
    #ifndef HAVE_SSE2
        #error "expected SSE2 to be enabled"
    #endif
    #ifndef HAVE_SSE3
        #error "expected SSE3 to be enabled"
    #endif
#else
    #ifdef HAVE_SSE
        #error "expected SSE to be disabled"
    #endif
    #ifdef HAVE_SSE2
        #error "expected SSE2 to be disabled"
    #endif
    #ifdef HAVE_SSE3
        #error "expected SSE3 to be disabled"
    #endif
#endif

#if defined(__arm__)
    #ifndef HAVE_NEON
        #error "expected NEON to be enabled"
    #endif
#else
    #ifdef HAVE_NEON
        #error "expected NEON to be disabled"
    #endif
#endif

#if defined(__aarch64__) || defined(_M_ARM64)
    #ifndef HAVE_NEON_FP16
        #error "expected NEON_FP16 to be enabled"
    #endif
    #ifndef HAVE_NEON_VFPV4
        #error "expected NEON_VFPV4 to be enabled"
    #endif
    #ifndef HAVE_ASIMD
        #error "expected ASIMD to be enabled"
    #endif
#else
    #ifdef HAVE_NEON_FP16
        #error "expected NEON_FP16 to be disabled"
    #endif
    #ifdef HAVE_NEON_VFPV4
        #error "expected NEON_VFPV4 to be disabled"
    #endif
    #ifdef HAVE_ASIMD
        #error "expected ASIMD to be disabled"
    #endif
#endif
    return 0;
}
