#include <stdio.h>
#include <mylib.h>
int main(void) {
    int x = 1;
    int y = c_lib_function(x);
    printf("%d -> %d", x, y);
    return 0;
}
