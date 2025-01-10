#include "stdio.h"
#include "zlib.h"

int main(void) {
    const char * const v = zlibVersion();
    printf("%s\n", v ? v : "<NULL>");
    return !v;
}
