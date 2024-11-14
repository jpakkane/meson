#include "dispatch.h"
#include <string.h>
#include <stdio.h>

int cpu_has(int feature_id)
{
    // we assume the used features are supported by CPU
    return 1;
}

int main()
{
    #include "dispatch1.conf.h"
    const char *dispatch1_str = DISPATCH_CALL(dispatch1)();
#if defined(TEST_X86)
    const char *exp_dispatch1_str = "dispatch1_SSSE3";
#elif defined(TEST_ARM64)
    const char *exp_dispatch1_str = "dispatch1";
#elif defined(TEST_ARM)
    const char *exp_dispatch1_str = "dispatch1_ASIMD";
#else
    const char *exp_dispatch1_str = "dispatch1";
#endif
    if (strcmp(dispatch1_str, exp_dispatch1_str) != 0) {
        return 1;
    }
    #include "dispatch2.conf.h"
    const char *dispatch2_str = DISPATCH_CALL(dispatch2)();
#if defined(TEST_X86)
    const char *exp_dispatch2_str = "dispatch2_SSE41";
#elif defined(TEST_ARM64) || defined(TEST_ARM)
    const char *exp_dispatch2_str = "dispatch2_ASIMD";
#else
    const char *exp_dispatch2_str = "dispatch2";
#endif
    if (strcmp(dispatch2_str, exp_dispatch2_str) != 0) {
        return 2;
    }
    #include "dispatch3.conf.h"
    const char *dispatch3_str = DISPATCH_CALL(dispatch3);
    if (dispatch3_str != NULL) {
        return 3;
    }
    return 0;
}
