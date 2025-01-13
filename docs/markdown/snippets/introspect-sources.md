## Introspection: Dump ast of subdir as well

`meson introspection --full-ast meson.build` dumps AST for every meson.build
from subdirs. It returns a dict where keys are paths to meson.build files,
and values are the AST for those files. The current `--ast` option only dumps
AST for the *root* meson.build file.
