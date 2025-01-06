## Control the number of child processes with an environment variable

Previously, `meson test` checked the `MESON_TESTTHREADS` variable to control
the amount of parallel jobs to run; this was useful when `meson test` is
invoked through `ninja test` for example.  With this version, a new variable
`MESON_NUM_PROCESSES` is supported with a broader scope: in addition to
`meson test`, it is also used by the `external_project` module and by
Ninja targets that invoke `clang-tidy`, `clang-format` and `clippy`.
