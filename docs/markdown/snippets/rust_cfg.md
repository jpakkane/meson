## New `rust.cfg()` module method

Returns the value of a Rust compiler config. Configs can either be predefined by
the Rust compiler (see `rustc --print cfg`) or set by the user with
`--cfg name="value"` in `RUSTFLAGS` environment or `rust_args` option.

If the config is set in the form `name="value"` then `value` string is returned.
If it is set with no value, `true` is returned. If it is not set, `false` is
returned.
