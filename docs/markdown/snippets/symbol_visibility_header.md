## New method to handle GNU and Windows symbol visibility

Defining public API of a cross platform C/C++ library is often painful and
require to copy macros snippets into every projects, typically using
`__declspec(dllexport)`, `__declspec(dllimport)` or
`__attribute__((visibility("default")))`.

Meson can now generate a header file that defines exactly what's needed for
all supported platforms:
[`snippets.symbol_visibility_header()`](Snippets-module.md#symbol_visibility_header).
