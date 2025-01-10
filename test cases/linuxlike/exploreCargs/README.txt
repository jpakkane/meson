What happens when c_args come from multiple places?

Combinatorial explosion and... some documentation gaps?

I tried to find in the documentation all the places {cpp,c,ld}_args
could be set and the relationships between these places. However what I
found was scattered in the corresponding places - no single, high-level
list or overview - and seemed sometimes incomplete.

I searched github for the same topic but that didn't really help either
because most of it is or was of course "work in progress" (the
difference between "is" and "was" being not always immediately obvious)
For instance https://github.com/mesonbuild/meson/issues/4767 states "All
cross compilation arguments come from the cross file". Except for: -D,
project(default_options: c_args...), executable( c_args, native:false),...

Then I looked for some relevant test code that would be in a less
natural language but necessarily in sync with the current
implementation. I couldn't really find any, so I wrote this (long)
sample. While tedious, this helped me understand some of the situation
better.

I'm not sure exactly where to take this next. A new, "<lang>_args hub"
documentation node with an organized list of pointers would probably not
hurt. Another cool thing would be to convert some of this to fully
automated tests and it's probably not too far from it, except for the
important question of: what particular combinations should be tested?
Can't test everything due to the number of locations and the
combinatorial explosion.


Locations "under test":
- environment C/CPP/LDFLAGS
- meson setup -Dc*_args=-D...
- meson setup --cross-file c*_args
- project (default_options c*_args)
- executable (c*_args)

Any I forgot?
- CFLAGS_FOR_BUILD ?
- multiple --cross-file (https://github.com/mesonbuild/meson/issues/3878)


Results below reproduced with this test directory + meson version 9c72d0fdb287.


A. My top issue: while some c*_args of different locations append to
each other (in which order?), other combinations of c*_args overwrite
one another and it feels difficult to predict what will happen when.

1 "meson setup -D[build.]c_args=..." overrides"
2. "project(default_options: [build.]c_args)", which overrides:
3. env LD/C/CPPFLAGS and --cross-file c_args.

Either of the above _combines_ with "executable(c_args)". And with
everything else? It could work differently, for instance one could
assume "project(default_options: )" means "default when no
executable(c_args)" instead.

I would also like -Dbuild.c_args to combine with --cross-file c_args,
because why not?


B. environment CPP/C/LDFLAGS

Granted: environment variables are discouraged. Still, it would be nice
to have some clearer idea how they work right now, even if nothing's
guaranteed in the future.

When cross-compiling, the env CFLAGS and LDFLAGS affects only the build
machine. Documented?

project(build.c_args) overrides BOTH env CPPCFLAGS and CFLAGS!
project(build.cpp_args) does... nothing ever?


C. Some "unknown options: build.c_*_args, ... " are actually used by meson.

 meson setup -Dbuild.cpp_args=... -Dbuild.c_args=... -Dbuild.c_link_args=... reports:

  WARNING: Unknown options: "build.c_*_args, ...

 It does drop build.cpp_args as claimed, however it uses the other two
 anyway when native:true.


D. --cross_file cpp_args are silently ignored. It's because everything
   is free-form in a --cross-file as documented, however it's another
   example of the "ugly duckling" status of cpp_args in general.

