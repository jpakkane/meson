## Multiple positional arguments for `meson wrap install`

Previously `meson wrap install` only accepted a single wrap name to install.
This limitation has now been lifted, and it is now possible to specify
multiple wrap names for installation. The exit code will be non-zero
if *any* of the wraps fail to install.
