## `fs.configure_file_list()`

This function produces, at build time, a file containing the list of files given
as argument. It is used when a command uses, as argument, a file containing the
list of files to process. One usecase is to provide `xgettext` with the list of
files to process, from the list of source files, when this list is too long to
be provided to the command line as individual files.
