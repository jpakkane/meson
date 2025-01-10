## Add a `error_if:` keyword-argument to `warning()` similar to `required:`

You can now use `warning('some-msg', error_if: true)` or `warning('some-msg',
error_if: option)` to convert a warning into an error. The purpose of this is to
either warn or error out during system detection/configuration and cater to the
following common use-case:

```meson
asm_option = get_option('asm')
cpu_family = host_machine.cpu_family()
if cpu_family in ['x86', 'x86_64']
  ...
elif cpu_family == 'aarch64'
  ...
else
  msg = f'CPU family @cpu_family@ is currently unsupported'
  if asm_option.enabled()
    error(msg)
  else
    warning(msg)
  endif
endif
```

This can now be written as:

```meson
...
else
  warning(f'CPU family @cpu_family@ is currently unsupported', error_if: asm_option)
endif
```
