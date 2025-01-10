project('install_emptydir')

install_emptydir(get_option('datadir')/'new_directory', install_mode: 'rwx------')
install_emptydir(get_option('datadir')/'new_directory/subdir', install_mode: 'rwxr-----')
install_emptydir([get_option('datadir')/'dir1',
                  get_option('datadir')/'dir2',
                  get_option('datadir')/'dir3'
                 ])
