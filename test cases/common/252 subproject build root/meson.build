project('subproject build root')

sub = subproject('foo')

message(sub.build_root())

assert(sub.build_root() == meson.global_build_root() / 'subprojects/foo')
