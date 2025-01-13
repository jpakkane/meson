#[cfg(foo)]
#[cfg(bar="val")]
pub fn func1() -> i32 {
    42
}

pub fn func2() -> i32 {
    func1()
}
