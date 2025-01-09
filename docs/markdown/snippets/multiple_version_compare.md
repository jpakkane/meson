## `version_compare` now accept multiple compare strings

Is it now possible to compare version against multiple values, to check for
a range of version for instance.

```meson
'1.5'.version_compare('>=1', '<2')
```
