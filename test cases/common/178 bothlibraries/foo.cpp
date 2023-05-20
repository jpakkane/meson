#include <memory>
#include "mylib.h"
#include "libfile.h"


int foo(void) {
    auto bptr = std::make_shared<int>(0);
    return *bptr;
}
