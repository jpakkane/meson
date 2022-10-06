## Changes to the b_sanitize option

In meson <= 0.62 the b_sanitize option is a combo, which is an enumerated set of
values. One picks one of the values as provided by that enumeration. In 0.63
this was changed to a free array of options, and a compiler check for the
validity of those options.

This solves a number of longstanding issues such as:
 - sanitizers may be supported by a compiler, but not on a specific platform (OpenBSD)
 - new sanitizers are not recognized by Meson
 - using sanitizers in different combinations

In order to not break backwards compatibility, meson will make continue to
return `get_option('b_sanitize')` as a string if the requested meson version is
`< 0.63`. In addition, it alphabetically sorts the values so that
`undefined,address` will still be presented as `address,undefined`. When the
minimum version is changed to >= 0.63, then it will return an array of strings.
