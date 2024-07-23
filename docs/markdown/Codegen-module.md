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

### lex()

```meson
codegen.lex('lexer.l')
```

This function wraps flex, lex, reflex (but not RE/flex), and win_flex (on Windows). When using win_flex it will automatically add the `--wincompat` argument.

This requires an input file, which may be a string, File, or generated source. It additionally takes the following options keyword arguments:

- `version`: Version constraints on the lexer
- `args`: An array of extra arguments to pass the lexer
- `plainname`: If set to true then `@PLAINNAME@` will be used as the source base, otherwise `@BASENAME@`.
- `source`: the name of the source output. If this is unset Meson will use `{base}.{ext}` with an extension of `cpp` if the input has an extension of `.ll` or `c` otherwise, with base being determined by the `plainname` argument.
- `header`: The optional output name for a header file. If this is unset no header is added
- `table`: The optional output name for a table file. If this is unset no table will be generated

The outputs will be in the form `source [header] [table]`, which means those can be accessed by indexing the output of the `lex` call:

```meson
l1 = codegen.lex('lexer.l', header : '@BASENAME@.h', table : '@BASENAME@.tab.h')
headers = [l1[1], l1[2]]  # [header, table]

l2 = codegen.lex('lexer.l', table : '@BASENAME@.tab.h')
table = l2[1]
```
