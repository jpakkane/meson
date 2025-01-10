project('swift sdk include dir test', 'swift')

bar_dep = declare_dependency(
  # Simulates including 'libffi' from brew as a dep via pkg-config
  # Without a workaround that replaces all SDK paths with the most recent one,
  # a compile error will occur due to conflicting definitions of the FFI module.
  compile_args: '-I/Library/Developer/CommandLineTools/SDKs/MacOSX12.sdk/usr/include/ffi',
)

foo = static_library('foo', 'foo.swift',
  dependencies: [bar_dep],
)
