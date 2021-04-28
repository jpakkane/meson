const std = @import("std");

pub fn main() !void {
    std.debug.print("Hello from {s}!", .{"meson"});
}
