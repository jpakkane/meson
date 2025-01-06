project('gir both libraries', 'c')

gir = dependency('gobject-introspection-1.0', required: false)
if not gir.found()
  error('MESON_SKIP_TEST gobject-introspection not found.')
endif

if host_machine.system() == 'cygwin'
  # FIXME: g-ir-scanner seems broken on cygwin:
  # ERROR: can't resolve libraries to shared libraries: foo++
  error('MESON_SKIP_TEST g-ir-scanner is broken on cygwin.')
endif

gnome = import('gnome')

# Regression test simulating how GStreamer generate its GIRs.
# Generated gobject-introspection binaries for every GStreamer libraries must
# first call gst_init() defined in the main libgstreamer, which means they need
# to link on that lib.
# A regression caused by https://github.com/mesonbuild/meson/pull/12632 made
# Meson not link the binary generated for bar with libfoo in the case it uses
# both_libraries().

libfoo = both_libraries('foo', 'foo.c')
foo_gir = gnome.generate_gir(libfoo,
  namespace: 'foo',
  nsversion: '1.0',
  sources: ['foo.c', 'foo.h'],
)
foo_dep = declare_dependency(
  link_with: libfoo,
  sources: foo_gir,
)

libbar = both_libraries('bar', 'bar.c', dependencies: foo_dep)
gnome.generate_gir(libbar,
  namespace: 'bar',
  nsversion: '1.0',
  sources: ['bar.c', 'bar.h'],
  extra_args: '--add-init-section=extern void foo_func(void);foo_func();',
  dependencies: foo_dep,
)
