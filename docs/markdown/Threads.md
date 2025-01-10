---
short-description: Enabling thread support
...

# Threads

Meson has a very simple notational shorthand for enabling thread
support on your build targets. First you obtain the thread dependency
object like this:

```meson
thread_dep = dependency('threads')
```

And then you just use it in a target like this:

```meson
executable('threadedprogram', ...
  dependencies : thread_dep)
```

On Windows, `dependency('threads')` does nothing on MSVC and links with
winpthreads on MinGW.  If your code uses native Win32 thread primitives
instead of pthreads, `dependency('threads')` will therefore add a spurious
winpthreads dependency when building with MinGW.  To prevent this, avoid
`dependency('threads')` on Windows:

```meson
if host_machine.system() == 'windows'
  thread_dep = dependency('', required: false)
else
  thread_dep = dependency('threads')
endif
```
