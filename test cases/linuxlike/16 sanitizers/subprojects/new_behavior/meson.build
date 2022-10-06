project(
  'sanitizer-new-behavior',
  'c',
  # XXX: this should be 0.62, but there's no way to test it until we actuall bump to 0.62…
  meson_version : '>= 0.61.99',
)

sanitize = get_option('b_sanitize')

assert(sanitize == ['undefined', 'address'], ','.join(sanitize))
