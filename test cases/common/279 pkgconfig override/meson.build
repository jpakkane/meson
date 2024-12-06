project('override pkg-config', 'c')

subproject('pkg-config')

pkgconfig = find_program('pkg-config')

# This dependency can only be found if pkg-config is overridden with our custom pkg-config.py
gobj = dependency('test-package-0.0', version : '= 0.0.0')
