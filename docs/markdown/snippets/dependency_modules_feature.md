## dependency now has modules argumens

In complex projects consisting of many different modules, you can now link modules with separate libraries from the package.

```dep = dependency('name', modules: [module1, module2, ...])```

If you only need header files, you must specify an empty list []

```dep_headers = dependency('name', modules: [])```