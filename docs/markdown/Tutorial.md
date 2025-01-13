---
short-description: Simplest tutorial
...

# Tutorial

This page shows from the ground up how to create a Meson build
definition for a simple project. Then we expand it to use external
dependencies to show how easily they can be integrated into your
project.

This tutorial has been written mostly for Linux usage. It assumes that
you have GTK development libraries available on the system. On
Debian-derived systems such as Ubuntu they can be installed with the
following command:

```
sudo apt install libgtk-4-dev
```

In addition, it is recommended to have the glib library with version 2.74 or higher.

It is possible to build the GUI application on other platforms, such
as Windows and macOS, but you need to install the needed dependencies.

The humble beginning
-----

Let's start with the most basic of programs, the classic hello
example. First we create a file `main.c` which holds the source. It
looks like this.

```c
#include <stdio.h>

//
// main is where all program execution starts
//
int main(int argc, char **argv) {
  printf("Hello there.\n");
  return 0;
}
```

Then we create a Meson build description and put it in a file called
`meson.build` in the same directory. Its contents are the following.

```meson
project('tutorial', 'c')
executable('demo', 'main.c')
```

That is all. Note that unlike Autotools you [do not need to add any
source headers to the list of
sources](FAQ.md#do-i-need-to-add-my-headers-to-the-sources-list-like-in-autotools).

We are now ready to build our application. First we need
to initialize the build by going into the source directory and issuing
the following commands.

```console
$ meson setup builddir
```

We create a separate build directory to hold all of the compiler
output. Meson is different from some other build systems in that it
does not permit in-source builds. You must always create a separate
build directory. Common convention is to put the default build
directory in a subdirectory of your top level source directory.

When Meson is run it prints the following output.

    The Meson build system
    Version: 1.2.1
    Source dir: /home/user/mesontutorial
    Build dir: /home/user/mesontutorial/builddir
    Build type: native build
    Project name: tutorial
    Project version: undefined
    C compiler for the host machine: cc (gcc 13.2.1 "cc (GCC) 13.2.1 20230801")
    C linker for the host machine: cc ld.bfd 2.41.0
    Host machine cpu family: x86_64
    Host machine cpu: x86_64
    Build targets in project: 1

    Found ninja-1.11.1 at /sbin/ninja

Now we are ready to build our code.


```console
$ cd builddir
$ ninja
```

If your Meson version is newer than 0.55.0, you can use the new
backend-agnostic build command:

```console
$ cd builddir
$ meson compile
```

For the rest of this document we are going to use the latter form.

Once the executable is built we can run it.

```console
$ ./demo
```

This produces the expected output.

    Hello there.

Adding dependencies
-----

Just printing text is a bit old fashioned. Let's update our program to
create a graphical window instead. We'll use the
[GTK](https://gtk.org) widget toolkit. First we edit the main file to
use GTK. The new version looks like this.

```c
#include <gtk/gtk.h>

//
// Callback function which constructs the window
//
static void activate(GtkApplication *app, gpointer user_data)
{
  GtkWidget *window;
  GtkWidget *label;

  window = gtk_application_window_new(app);
  gtk_window_set_title(GTK_WINDOW(window), "Window");
  gtk_window_set_default_size(GTK_WINDOW(window), 200, 200);

  label = gtk_label_new("Hello world!");
  gtk_window_set_child(GTK_WINDOW(window), label);
  gtk_widget_set_visible(window, true);
}

//
// main is where all program execution starts
//
int main(int argc, char **argv)
{
  GtkApplication *app;
  int status;

#if GLIB_CHECK_VERSION(2, 74, 0)
  app = gtk_application_new(NULL, G_APPLICATION_DEFAULT_FLAGS);
#else
  app = gtk_application_new(NULL, G_APPLICATION_FLAGS_NONE);
#endif

  g_signal_connect(app, "activate", G_CALLBACK(activate), NULL);
  status = g_application_run(G_APPLICATION(app), argc, argv);
  g_object_unref(app);  // Free from memory when program terminates

  return status;
}
```

Then we edit the Meson file, instructing it to find and use the GTK
libraries.

```meson
project('tutorial', 'c')
gtkdep = dependency('gtk4')
executable('demo', 'main.c', dependencies : gtkdep)
```

If your app needs to use multiple libraries, you need to use separate
[[dependency]] calls for each, like so:

```meson
project('tutorial', 'c')
gtkdep = dependency('gtk4')

# Make sure to install the new dependency first with
# sudo apt install libgtksourceview-5-dev
gtksourceview_dep = dependency('gtksourceview-5')
executable('demo', 'main.c', dependencies : [gtkdep, gtksourceview_dep])
```

We don't need it for the current example.

Now we are ready to build. The thing to notice is that we do *not*
need to recreate our build directory, run any sort of magical commands
or the like. Instead we just type the exact same command as if we were
rebuilding our code without any build system changes.

```console
$ meson compile
```

Once you have set up your build directory the first time, you don't
ever need to run the `meson` command again. You always just run `meson
compile`. Meson will automatically detect when you have done changes
to build definitions and will take care of everything so users don't
have to care. In this case the following output is produced.

    INFO: autodetecting backend as ninja
    INFO: calculating backend command to run: /sbin/ninja
    [0/1] Regenerating build files.
    The Meson build system
    Version: 1.2.1
    Source dir: /home/user/mesontutorial
    Build dir: /home/user/mesontutorial/builddir
    Build type: native build
    Project name: tutorial
    Project version: undefined
    C compiler for the host machine: cc (gcc 13.2.1 "cc (GCC) 13.2.1 20230801")
    C linker for the host machine: cc ld.bfd 2.41.0
    Host machine cpu family: x86_64
    Host machine cpu: x86_64
    Found pkg-config: /sbin/pkg-config (1.8.1)
    Run-time dependency gtk4 found: YES 4.12.0
    Run-time dependency gtksourceview-5 found: YES 5.8.0
    Build targets in project: 1

    Found ninja-1.11.1 at /sbin/ninja
    Cleaning... 0 files.
    [2/2] Linking target demo

Note how Meson noticed that the build definition has changed and reran
itself automatically. The program is now ready to be run:

```
$ ./demo
```

This creates the following GUI application.

![GTK sample application screenshot](images/gtksample.png)
