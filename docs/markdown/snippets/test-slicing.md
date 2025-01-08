## New option to execute a slice of tests

When tests take a long time to run a common strategy is to slice up the tests
into multiple sets, where each set is executed on a separate machine. You can
now use the `--slice i/n` argument for `meson test` to create `n` slices and
execute the `ith` slice.
