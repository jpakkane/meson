mod ffi {
    extern "C" {
        pub fn func() -> i32;
    }
}

pub fn func() -> i32 {
    unsafe {
        ffi::func()
    }
}

