lib2 = library('mylib2', 'lib2.c', include_directories: lib1_includes, link_with: lib1)
lib2_pot = i18n.xgettext('lib2', lib2, args: xgettext_args)
lib2_includes = include_directories('.')
