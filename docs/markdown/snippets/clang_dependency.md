## A Clang dependency

This helps to simplify the use of libclang, removing the need to try cmake and
then falling back to not cmake. It also transparently handles the issues
associated with different paths to find Clang on different OSes.
