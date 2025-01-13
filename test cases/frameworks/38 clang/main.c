/*
 * SPDX-License-Identifier: Apache-2.0
 * Copyright © 2024 Intel Corporation
 */

#include <clang-c/Index.h>

#include <stdio.h>

int main(int argc, char * argv[]) {
    if (argc < 2) {
        fprintf(stderr, "At least one argument is required!\n");
        return 1;
    }

    const char * file = argv[1];

    CXIndex index = clang_createIndex(0, 0);
    CXTranslationUnit unit = clang_parseTranslationUnit(
        index,
        file, NULL, 0,
        NULL, 0,
        CXTranslationUnit_None);

    if (unit == NULL) {
        return 1;
    }

    clang_disposeTranslationUnit(unit);
    clang_disposeIndex(index);

    return 0;
}
