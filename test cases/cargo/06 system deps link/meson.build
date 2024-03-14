project('cargo system-deps', 'rust')

rust = import('unstable-rust')

sub = rust.cargo('sub')

exe = executable('main', 'main.rs', dependencies : sub.get_variable('dep'))

test('main', exe)

