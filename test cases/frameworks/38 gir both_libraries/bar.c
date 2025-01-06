#include "bar.h"
#include "foo.h"

int bar_func(void)
{
    return foo_func() + 42;
}
