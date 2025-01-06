#include <string.h>
#include <config10.h>

int main(void) {
    return strcmp(MESSAGE1, "foo")
        || strcmp(MESSAGE2, "foo");
}
