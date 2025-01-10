#!/bin/bash

set -e

source /ci/common.sh

export DEBIAN_FRONTEND=noninteractive
export LANG='C.UTF-8'
export DC=gdc

pkgs=(
  python3-pip libxml2-dev libxslt1-dev libyaml-dev libjson-glib-dev
  wget unzip
  qt5-qmake qtbase5-dev qtchooser qtbase5-dev-tools clang
  qmake6 qt6-base-dev qt6-base-private-dev qt6-declarative-dev qt6-declarative-dev-tools qt6-l10n-tools qt6-base-dev-tools
  libomp-dev
  llvm lcov
  dub ldc
  mingw-w64 mingw-w64-tools libz-mingw-w64-dev
  libclang-dev
  libgcrypt20-dev
  libgpgme-dev
  libhdf5-dev
  libboost-python-dev libboost-regex-dev
  libblocksruntime-dev
  libperl-dev
  liblapack-dev libscalapack-mpi-dev
  bindgen
  itstool
  openjdk-11-jre
  jq
)

sed -i '/^Types: deb/s/deb/deb deb-src/' /etc/apt/sources.list.d/ubuntu.sources
apt-get -y update
apt-get -y upgrade
apt-get -y install eatmydata

# Base stuff
eatmydata apt-get -y build-dep meson

# packages
eatmydata apt-get -y install "${pkgs[@]}"
eatmydata apt-get -y install --no-install-recommends wine-stable  # Wine is special

install_python_packages hotdoc

# Lower ulimit before running dub, otherwise there's a very high chance it will OOM.
# See: https://github.com/dlang/phobos/pull/9048 and https://github.com/dlang/phobos/pull/8990
echo 'ulimit -n -S 10000' >> /ci/env_vars.sh
ulimit -n -S 10000
# dub stuff
dub_fetch dubtestproject@1.2.0
dub build dubtestproject:test1 --compiler=ldc2 --arch=x86_64
dub build dubtestproject:test2 --compiler=ldc2 --arch=x86_64
dub build dubtestproject:test3 --compiler=gdc --arch=x86_64
dub_fetch urld@3.0.0
dub build urld --compiler=gdc --arch=x86_64

# Remove debian version of Rust and install latest with rustup.
# This is needed to get the cross toolchain as well.
apt-get -y remove rustc || true
wget -O - https://sh.rustup.rs | sh -s -- -y --profile minimal --component clippy
source "$HOME/.cargo/env"
rustup target add x86_64-pc-windows-gnu
rustup target add arm-unknown-linux-gnueabihf

# Zig
# Use the GitHub API to get the latest release information
LATEST_RELEASE=$(wget -qO- "https://api.github.com/repos/ziglang/zig/releases/latest")
ZIGVER=$(echo "$LATEST_RELEASE" | jq -r '.tag_name')
ZIG_BASE="zig-linux-x86_64-$ZIGVER"
wget "https://ziglang.org/download/$ZIGVER/$ZIG_BASE.tar.xz"
tar xf "$ZIG_BASE.tar.xz"
rm -rf "$ZIG_BASE.tar.xz"
cd "$ZIG_BASE"

# As mentioned in the Zig readme, the binary and files under lib can be copied
# https://github.com/ziglang/zig?tab=readme-ov-file#installation
mv zig /usr/bin
mv lib /usr/lib/zig

# Copy the LICENSE
mkdir -p /usr/share/doc/zig
cp LICENSE /usr/share/doc/zig

# Remove what's left of the directory
cd ..
rm -rf "$ZIG_BASE"

# Hack for https://github.com/linux-test-project/lcov/issues/245
# https://github.com/linux-test-project/lcov/commit/bf135caf5f626e02191c42bd2773e08a0bb9b7e5
# XXX: Drop this once Ubuntu has lcov-2.1*
git clone https://github.com/linux-test-project/lcov
cd lcov
make install

# cleanup
apt-get -y clean
apt-get -y autoclean
