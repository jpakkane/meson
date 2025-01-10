project('staticlib group', 'c', 'rust')

ld_bfd = find_program('ld.bfd')
if not ld_bfd.found()
  error('MESON_SKIP_TEST ld.bfd not found')
endif

lib1 = static_library('lib1', 'lib1.c')
lib2 = static_library('lib2', 'lib2.c')
executable('lib1first', 'main.rs', link_with : [lib1, lib2],
  rust_args: ['-C', 'lto=n', '-C', 'linker-plugin-lto=n', '-Clink-arg=-fuse-ld=bfd'])
executable('lib2first', 'main.rs', link_with : [lib2, lib1],
  rust_args: ['-C', 'lto=n', '-C', 'linker-plugin-lto=n', '-Clink-arg=-fuse-ld=bfd'])
