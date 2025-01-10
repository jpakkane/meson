#pragma once

#include <stdbool.h>

/* Attempt to trigger -Wsizeof-array-div */
extern int arr1[10];
const int C1 = sizeof(arr1) / sizeof(short);
