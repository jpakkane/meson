subdir('lib1')
subdir('lib2')

main = executable('say', 'main.c', link_with: [lib2], include_directories: lib2_includes)

main_pot = i18n.xgettext('main', main, args: xgettext_args, install: true, install_dir: 'intl', install_tag: 'intl', recursive: true)
