#include "lib2.h"

#include <lib1.h>

#include <stdio.h>

#define tr(STRING) (STRING)

void say_something_else(void)
{
    say_something();
    printf("%s\n", tr("Something else!"));
}
