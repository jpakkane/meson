## Added support for DIA SDK on linux via msvc-wine

Microsoft DIA SDK library (for reading with .PDB files) can now be
used when cross-compiling on linux with mstorsjo/msvc-wine
environment. Both compiling with native clang and MSVC cl over
wine are supported.
