# Documentation for Meson

The documentation for users of the Meson Build system is created using hotdoc and is located in the `doc` directory.
It compiles markdown files into the documentation.

Here is a quick guide to the `doc` directory:

* The file `hotdoc.json` is the configuration file.
* The file `README.md` contains a quick info on how to compile the documentation.
* The directory `theme` contains the theme for the documentation.
* The directory `images` contains images for the documentation.
* The file `sitemap.txt` tells hotdoc the structure of the documentation and which markdown files should be places where.


## How to contribute

Find the appropriate markdown file in the `doc/markdown` (`doc\markdown` under Windows) directory and make your changes.

If you create a new markdown file (which is probably rare), add it to `sitemap.txt`.

**_Attention:_** [Integration tests should be disabled](http://mesonbuild.com/Contributing.html#skipping-integration-tests) for documentation-only commits by putting [skip ci] into the commit title.
