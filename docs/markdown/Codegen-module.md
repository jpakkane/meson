---
short-description: Common Code Generators Module
authors:
    - name: Dylan Baker
      email: dylan@pnwbakers.com
      years: [2024]
...

# Codegen Module

*(New in 1.6.0)*

This module provides wrappers around common code generators, such as flex/lex and bison/yacc. This purpose of this is to make it easier and more pleasant to use *common* code generators in a mesonic way.

## Functions

### find_lex()

```meson
codegen.find_lex(implementations : ['flex', 'reflex], flex_version : ['>= 2.6', '< 3'], reflex_version : '!= 1.4.2')
```

This function provides fine grained control over what implementation(s) and version(s) of lex are acceptable for a given project (These are set per-subproject). This call may only be made once per subproject, and must be made before any calls to [codegen.lex](#lex).

It accepts the following keyword arguments:

 - `implementations`: a string array of acceptable implementations to use. May include: `lex`, `flex`, `reflex`, or `win_flex`.
 - `lex_version`: a string array of version constraints to apply to the `lex` binary
 - `flex_version`: a string array of version constraints to apply to the `flex` binary
 - `reflex_version`: a string array of version constraints to apply to the `relex` binary
 - `win_flex_version`: a string array of version constraints to apply to the `win_flex` binary


### lex()

```meson
codegen.lex('lexer.l')
```

This function wraps flex, lex, reflex (but not RE/flex), and win_flex (on Windows). When using win_flex it will automatically add the `--wincompat` argument. When this function is run the first time, if no lex implementation has been found it will search for any version of lex, flex, reflex, and win_flex, with any version. For greater control over what implementation is used, refer to the [find_lex method](#find_lex).

This requires an input file, which may be a string, File, or generated source. It additionally takes the following options keyword arguments:

- `args`: An array of extra arguments to pass the lexer
- `plainname`: If set to true then `@PLAINNAME@` will be used as the source base, otherwise `@BASENAME@`.
- `source`: the name of the source output. If this is unset Meson will use `{base}.{ext}` with an extension of `cpp` if the input has an extension of `.ll` or `c` otherwise, with base being determined by the `plainname` argument.
- `header`: The optional output name for a header file. If this is unset no header is added
- `table`: The optional output name for a table file. If this is unset no table will be generated
                         'POSIX specification does not require that header output be cont')
The outputs will be in the form `source [header] [table]`, which means those can be accessed by indexing the output of the `lex` call:

```meson
l1 = codegen.lex('lexer.l', header : '@BASENAME@.h', table : '@BASENAME@.tab.h')
headers = [l1[1], l1[2]]  # [header, table]

l2 = codegen.lex('lexer.l', table : '@BASENAME@.tab.h')
table = l2[1]
```

### find_yacc()

```meson
codegen.find_yacc(implementations : ['bison', 'win_bison'])
```

This function provides fine grained controls over which implementation(s) and version(s) of the parser generator to use.

Accepts the following keyword arguments:

 - `implementations`: a string array of acceptable implementations to use. May include: `yacc`, `byacc`, or `bison`.
 - `yacc_version`: a string array of version constraints to apply to the `yacc` binary
 - `byacc_version`: a string array of version constraints to apply to the `byacc` binary
 - `bison_version`: a string array of version constraints to apply to the `bison` binary
 - `win_bison_version`: a string array of version constraints to apply to the `win_bison` binary

### yacc()

```meson
codegen.yacc('parser.y')
```

This function wraps bison, yacc, byacc, and win_bison (on Windows), and attempts to abstract away the differences between them

This requires an input file, which may be a string, File, or generated source. It additionally takes the following options keyword arguments:

- `version`: Version constraints on the lexer
- `args`: An array of extra arguments to pass the lexer
- `plainname`: If set to true then `@PLAINNAME@` will be used as the source base, otherwise `@BASENAME@`.
- `source`: the name of the source output. If this is unset Meson will use `{base}.{ext}` with an extension of `cpp` if the input has an extension of `.yy` or `c` otherwise, with base being determined by the `plainname` argument.
- `header`: the name of the source output. If this is unset Meson will use `{base}.{ext}` with an extension of `hpp` if the input has an extension of `.yy` or `h` otherwise, with base being determined by the `plainname` argument.
- `locations`: The name of the locations file, if one is generated. Due to the way yacc works this must be duplicated in the file and in the command.

The outputs will be in the form `source header [locations]`, which means those can be accessed by indexing the output of the `yacc` call:

```meson
p1 = codegen.yacc('parser.y', header : '@BASENAME@.h', table : '@BASENAME@.tab.h')
headers = [l1[1], l1[2]]  # [header, table]

p2 = codegen.lex('parser.y', locations : 'locations.hpp')
table = l2[1]
```
