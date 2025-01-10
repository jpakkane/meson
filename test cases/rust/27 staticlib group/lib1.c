#include <stdio.h>
#include "lib1.h"
#include "lib2.h"

void from_lib2(void) {
    printf("hello world");
}

void c_func(void) {
    from_lib1();
}
