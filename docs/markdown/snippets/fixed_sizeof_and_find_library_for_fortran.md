## Fixed `sizeof` and `find_library` methods for Fortran compilers

The implementation of the `.sizeof()` method has been fixed for Fortran
compilers (it was previously broken since it would try to compile a C code
snippet). Note that this functionality requires Fortran 2008 support.

Incidentally this also fixes the `.find_library()` method for Fortran compilers
when the `prefer_static` built-in option is set to true.
