## Cargo features are resolved globally

When configuring a Cargo dependency, Meson will now resolve its complete
dependency tree and feature set before generating the subproject AST.
This solves many cases of Cargo subprojects being configured with missing
features that the main project had to enable by hand using e.g.
`default_options: ['foo-rs:feature-default=true']`.

Note that there could still be issues in the case there are multiple Cargo
entry points. That happens if the main Meson project makes multiple `dependency()`
calls for different Cargo crates that have common dependencies.

Breaks: This change removes per feature Meson options that were previously
possible to set as shown above or from command line `-Dfoo-rs:feature-foo=true`.
