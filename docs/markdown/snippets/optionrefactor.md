## Per project subproject options rewrite

You can now define per-subproject values for all shared configuration
options. As an example you might want to enable optimizations on only
one subproject:

    meson configure -Dnumbercruncher:optimization=3

Subproject specific values can be removed with -U

    meson configure -Unumbercruncher:optimization

This is a major change in how options are handled. Current
per-subproject options are converted to augments on the fly. It is
expected that the logic might be changed in the next few releases as
logic errors are discovered.

We have tried to keep backwards compatibility as much as possible, but
this may lead to some build breakage.
