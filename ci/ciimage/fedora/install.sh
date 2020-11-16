#!/bin/bash

set -e

pkgs=(
  python python-setuptools python-wheel python-pip python-pytest-xdist python3-devel
  ninja-build make git autoconf automake patch python3-Cython python3-jsonschema
  elfutils gcc gcc-c++ gcc-fortran gcc-objc gcc-objc++ vala rust bison flex ldc libasan libasan-static
  mono-core boost-devel gtkmm30 gtest-devel gmock-devel protobuf-devel wxGTK3-devel gobject-introspection
  boost-python3-devel
  itstool gtk3-devel java-latest-openjdk-devel gtk-doc llvm-devel clang-devel SDL2-devel graphviz-devel zlib zlib-devel zlib-static
  #hdf5-openmpi-devel hdf5-devel netcdf-openmpi-devel netcdf-devel netcdf-fortran-openmpi-devel netcdf-fortran-devel scalapack-openmpi-devel
  doxygen vulkan-devel vulkan-validation-layers-devel openssh mercurial gtk-sharp2-devel libpcap-devel gpgme-devel
  qt5-qtbase-devel qt5-qttools-devel qt5-linguist qt5-qtbase-private-devel
  libwmf-devel valgrind cmake openmpi-devel nasm gnustep-base-devel gettext-devel ncurses-devel
  libxml2-devel libxslt-devel libyaml-devel glib2-devel json-glib-devel python3-lxml libgcrypt-devel
)

# Sys update
dnf -y upgrade

# Install deps
dnf -y install "${pkgs[@]}"
python3 -m pip install hotdoc gcovr gobject PyGObject

# Cleanup
dnf -y clean all
