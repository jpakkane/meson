## Meson can run "clippy" on Rust projects

Meson now defines a `clippy` target if the project uses the Rust programming
language.  The target runs clippy on all Rust sources, using the `clippy-driver`
program from the same Rust toolchain as the `rustc` compiler.

Using `clippy-driver` as the Rust compiler will now emit a warning, as it
is not meant to be a general-purpose compiler front-end.
