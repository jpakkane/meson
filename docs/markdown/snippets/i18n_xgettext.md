## i18n module xgettext

There is a new `xgettext` function in `i18n` module that acts as a
wrapper around `xgettext`. It allows to extract strings to translate from
source files.

This function is convenient, because:
- It can find the sources files from a build target;
- It will use an intermediate file when the number of source files is too
  big to be handled directly from the command line;
- It is able to get strings to translate from the dependencies of the given
  targets.
