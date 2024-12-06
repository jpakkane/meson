extern "C" {
    fn g_get_tmp_dir() -> *mut std::ffi::c_void;
}

#[cfg(system_deps_have_glib)]
#[cfg(not(system_deps_have_gobject))]
pub fn func() {
    unsafe {
        g_get_tmp_dir();
    }
}

pub fn func1() {
    func()
}
