root = meson.source_root()
dep = dependency('dubtestproject:test3', method: 'dub')
version = dep.version()
if version != '1.2.0'
  error(f'Expected urld version to be the one selected in "@root@/dub.selections.json" but got @version@')
endif
