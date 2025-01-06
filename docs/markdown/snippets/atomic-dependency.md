## New custom dependency for atomic

```
dependency('atomic')
```

checks for the availability of the atomic operation library. First, it looks
for the atomic library. If that is not found, then it will try to use what is
provided by the libc.
