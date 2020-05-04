project('kconfig basic test')

k = import('unstable-kconfig')
conf = k.load('.config')

if not conf.has_key('CONFIG_VAL1')
  error('Expected CONFIG_VAL1 to be set, but it wasn\'t')
endif

if conf.has_key('CONFIG_VAL2')
  error('Expected CONFIG_VAL2 not be set, but it was')
endif

if conf.get('CONFIG_VAL_VAL').to_int() != 4
  error('Expected CONFIG_VAL_VAL to be 4')
endif

if conf.get('CONFIG_VAL_STRING1') != 'foo'
  error('Expected CONFIG_VAL_STRING1 to be foo')
endif

if conf.get('CONFIG_VAL_STRING2') != 'bar'
  error('Expected CONFIG_VAL_STRING2 to be bar')
endif
