const std = @import("std");

const cHello = @cImport({
    @cInclude("test.h");
});

pub fn main() !void {
    std.debug.print("Hello from {s}!", .{cHello.hello()});
}
