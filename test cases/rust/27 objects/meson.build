project('staticlib group', 'c', 'rust', meson_version: '>=1.7.0')

lib1 = static_library('lib1', 'lib1.c')
lib2 = static_library('lib2', 'lib2.c')
executable('lib1objs', 'main.rs',
  objects: lib1.extract_all_objects(recursive: false),
  link_with: lib2)
executable('lib2objs', 'main.rs',
  objects: lib2.extract_all_objects(recursive: false),
  link_with: lib1)
executable('lib1objs_as_dep', 'main.rs',
  dependencies: declare_dependency(objects: lib1.extract_all_objects(recursive: false)),
  link_with: lib2)
executable('lib2objs_as_dep', 'main.rs',
  dependencies: declare_dependency(objects: lib2.extract_all_objects(recursive: false)),
  link_with: lib1)
