## Add subprojects syncwrap command to update wrap files according to their repository

Using `meson subprojects syncwrap` will update the revision in all wrap files (git only) to match
the revision of their repository. It is particularly useful when developing subprojects along the main project.
