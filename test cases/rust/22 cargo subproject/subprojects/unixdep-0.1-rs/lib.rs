pub fn only_on_unix() -> i32 {
    0
}

#[cfg(not(unix))]
pub fn broken() -> i32 {
    plop
}
