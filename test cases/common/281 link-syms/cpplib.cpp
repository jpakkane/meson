#define BUILDING_DLL
#include "cpplib.h"

int DLL_PUBLIC cppfunc(void) {
    return 42;
}

int DLL_PUBLIC cppfunc_sym(void) {
    return 43;
}
