use std::env;

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rustc-cfg=foo");
    println!("cargo:rustc-cfg=bar=\"val\"");
    assert!(env::var("CARGO_FEATURE_DEFAULT").is_ok());
}
