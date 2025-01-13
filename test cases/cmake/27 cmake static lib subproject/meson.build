project('cmake-static-lib-subproject', 'cpp')

libc = import('cmake').subproject('liba').dependency('libc')
executable('main', 'main.cc', dependencies: [libc])
