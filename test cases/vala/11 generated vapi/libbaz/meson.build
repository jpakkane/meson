libbaz_sources = [
  'baz.c',
  'baz.h',
]

libbaz = shared_library('baz', libbaz_sources,
  install: true,
)

libbaz_api_ver = '1.0'

libbaz_gir = gnome.generate_gir(libbaz,
  sources: libbaz_sources,
  namespace: 'Baz',
  nsversion: libbaz_api_ver,
  symbol_prefix: 'baz',
  extra_args: [
    '--c-include=baz.h',
  ],
)

libbaz_vapi = gnome.generate_vapi('baz-' + libbaz_api_ver,
  sources: libbaz_gir[0],
  packages: meson.get_compiler('vala').find_library('posix'),
  install: true,
)
