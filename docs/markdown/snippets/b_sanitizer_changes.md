## Changes to the b_sanitize option

In meson <= 1.6 the b_sanitize option is a combo, which is an enumerated set of
values. One picks one of the values as provided by that enumeration. In 1.6
this was changed to a free array of options, and a compiler check for the
validity of those options.

This solves a number of longstanding issues such as:
 - sanitizers may be supported by a compiler, but not on a specific platform (OpenBSD)
 - new sanitizers are not recognized by Meson
 - using sanitizers in different combinations

In order to not break backwards compatibility, meson will continue to
return `get_option('b_sanitize')` as a string, with a guarantee that
`address,undefined` will remain ordered. Calling
 `get_option('b_sanitize', format : 2)`
returns a free form list with no ordering guarantees.
