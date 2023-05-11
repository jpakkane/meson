## `c_legal_code` option introduced

The new `c_legal_code` option is enabled by default. It bans
dangerous C constructs in C99 or later to emulate newer C compiler
defaults.

For GCC, it sets the following:
* `-Werror=implicit` (-> `-Werror=implicit-int,implicit-function-declaration`)
* `-Werror=int-conversion`
* `-Werror=incompatible-pointer-types`

For Clang, it sets the following:
* `-Werror=implicit` (-> `-Werror=implicit-int,implicit-function-declaration`)
* `-Werror=int-conversion`
* `-Werror=incompatible-pointer-types`
* `-Wno-error=incompatible-pointer-types-discards-qualifiers` (to emulate GCC's behavior)
