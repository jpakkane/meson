const std = @import("std");

const cUrl = @cImport({
    @cInclude("curl/curl.h");
});

pub fn main() !void {
    const handle: ?*cUrl.CURL = cUrl.curl_easy_init();
    std.debug.print("Hello curl {s} from {s}!", .{cUrl.curl_version(), "meson"});

    cUrl.curl_easy_cleanup(handle);
}
