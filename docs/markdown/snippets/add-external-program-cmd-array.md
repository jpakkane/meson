## Added an `ExternalProgram.cmd_array()` method

External program objects now have a `cmd_array()` method which returns an array
of arguments needed to run the program. This serves a similar purpose to
the same method on compiler objects.

```meson
prog = find_program('prog')
cmd = prog.cmd_array()
```
