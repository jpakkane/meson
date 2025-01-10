# It's a shame configure_file(..., copy: true) has been deprecated.
# It was simpler for this use-case and would do the copying at setup/configure-time rather than at build-time,
# which better fits our usage.

fs = import('fs')
build_only_h = fs.copyfile('build_only._h','build_only.h')
build_only_h_dep = declare_dependency(sources: build_only_h)