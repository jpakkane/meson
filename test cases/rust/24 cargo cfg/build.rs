use std::env;

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rustc-cfg=FOO");
    println!("cargo:rustc-cfg=BAR=val");
    assert!(env::var("CARGO_FEATURE_MYFEATURE").is_ok());
}
