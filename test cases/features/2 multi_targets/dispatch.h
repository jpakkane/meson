#ifndef DISPATCH_H_
#define DISPATCH_H_

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

#if defined( __i386__ ) || defined(i386) || defined(_M_IX86) || \
    defined(__x86_64__) || defined(__amd64__) || defined(__x86_64) || defined(_M_AMD64)
    #define TEST_X86
#elif defined(__aarch64__) || defined(_M_ARM64)
    #define TEST_ARM64
#elif defined(__arm__)
    #define TEST_ARM
#endif

enum {
    CPU_SSE = 1,
    CPU_SSE2,
    CPU_SSE3,
    CPU_SSSE3,
    CPU_SSE41,
    CPU_NEON,
    CPU_NEON_FP16,
    CPU_NEON_VFPV4,
    CPU_ASIMD
};
int cpu_has(int feature_id);
#define CPU_TEST(FEATURE_NAME) cpu_has(CPU_##FEATURE_NAME)
#define CPU_TEST_DUMMY(FEATURE_NAME)

#define EXPAND(X) X
#define CAT__(A, B) A ## B
#define CAT_(A, B) CAT__(A, B)
#define CAT(A, B) CAT_(A, B)
#define STRINGIFY(x) #x
#define TOSTRING(x) STRINGIFY(x)

#ifdef MTARGETS_CURRENT
    #define DISPATCH_CURRENT(X) CAT(CAT(X,_), MTARGETS_CURRENT)
#else
    // baseline
    #define DISPATCH_CURRENT(X) X
#endif

#define DISPATCH_DECLARE(...) \
    MTARGETS_CONF_DISPATCH(CPU_TEST_DUMMY, DISPATCH_DECLARE_CB, __VA_ARGS__) \
    MTARGETS_CONF_BASELINE(DISPATCH_DECLARE_BASE_CB, __VA_ARGS__)

// Preprocessor callbacks
#define DISPATCH_DECLARE_CB(TESTED_FEATURES_DUMMY, TARGET_NAME, LEFT, ...) \
    CAT(CAT(LEFT, _), TARGET_NAME) __VA_ARGS__;
#define DISPATCH_DECLARE_BASE_CB(LEFT, ...) \
    LEFT __VA_ARGS__;

#define DISPATCH_CALL(NAME) \
    ( \
        MTARGETS_CONF_DISPATCH(CPU_TEST, DISPATCH_CALL_CB, NAME) \
        MTARGETS_CONF_BASELINE(DISPATCH_CALL_BASE_CB, NAME) \
        NULL \
    )
// Preprocessor callbacks
#define DISPATCH_CALL_CB(TESTED_FEATURES, TARGET_NAME, LEFT) \
    (TESTED_FEATURES) ? CAT(CAT(LEFT, _), TARGET_NAME) :
#define DISPATCH_CALL_BASE_CB(LEFT) \
    (1) ? LEFT :

#include "dispatch1.conf.h"
DISPATCH_DECLARE(const char *dispatch1, ())

#include "dispatch2.conf.h"
DISPATCH_DECLARE(const char *dispatch2, ())

#endif // DISPATCH_H_
