## New `response_file` function

This function writes a list of arguments into a response file, when the
resulting command line would be too long otherwise. This allows the use of
response files with `custom_target` or other functions calling a custom
executable.
