## String formatting supports replacing variable names, similar to fstrings

Next to positional arguments, variable name placeholders can be formatted as well.
This means only plain variable names, not arbitrary code can be inserted into strings.
```meson
a = 1
template = 'string: @0@, number: @a@'
res = template.format('text')
# res now has value 'string: text, number: 1'
```
