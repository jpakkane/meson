project('cfg', 'rust')

rust = import('rust')
cfg = rust.cargo_cfg('myfeature')
assert(cfg['FOO'] == '')
assert(cfg['BAR'] == 'val')
