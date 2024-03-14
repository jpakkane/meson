extern crate common;
extern crate libothername;

extern "C" {
    fn extra_func() -> i32;
}

#[cfg(feature = "foo")]
#[no_mangle]
pub extern "C" fn rust_func() -> i32 {
    #[cfg(unix)]
    {
        extern crate unixdep;
        assert!(unixdep::only_on_unix() == 0);
    }
    assert!(common::common_func() == 0);
    assert!(libothername::stuff() == 42);
    let v: i32;
    unsafe {
         v = extra_func();
    };
    mybar::VALUE + v
}
