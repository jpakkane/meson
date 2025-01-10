#!/bin/sh

set -e
set -x

MESON=~/meson/meson.py


# "-Wl,--undefined=_test_value" has for the linker useful test
# properties similar to how D_test_value behaves for the preprocessor:
# visible and testable yet "pass-through" and completely harmless. In a
# way it's even better than -D because a dummy test program ends up with
# a large noise of -D macros that the toolchain adds by default, whereas
# "-Wl,--undefined=_test_value" doesn't even need to be filtered.

do_bld()
{
    local bld="$1"; shift
    if true; then
        ${MESON} setup \
             -Dcpp_args=-DCLIsetup_CPP_args=___YES_CLIsetup___ \
             -Dbuild.cpp_args=-DCLIsetup_buildm_CPP_args=___YES_CLIsetup_buildm____ \
             -Dc_args=-DCLIsetup_C_args=___YES_CLIsetup____ \
             -Dbuild.c_args=-DCLIsetup_buildm_C_args=___YES_CLIsetup_buildm____ \
             -Dc_link_args=-Wl,--undefined=CLIsetup_C_link_args \
             -Dbuild.c_link_args=-Wl,--undefined=CLIsetup_buildm_C_link_args \
             "$bld" "$@"
    else
        ${MESON} setup  "$bld" "$@"
    fi

    ${MESON} configure "$bld" | grep -C2 args
    ninja -C "$bld" print_flags

    if true; then
        jq . "${bld}"/meson-info/intro-buildoptions.json | grep -C 5 args
        jq . "${bld}"/meson-info/intro-targets.json | grep -C 8 _args
    fi
}

main()
{
    local YES_SIR='___YES_ENV___'

    # envvars considered harmful:
    #   https://github.com/mesonbuild/meson/issues/4664
    if true; then
        export CPPFLAGS="-Denv_CPPFLAGS=${YES_SIR}"
        export CFLAGS="-Denv_CFLAGS=${YES_SIR}"
        export LDFLAGS='-Wl,--undefined=env_LDFLAGS'
    fi

    # --wipe fails when bld*/ is missing, so let's not use it.
    rm -rf bldnat/ bldcross/

    if false; then
        printf '\n\n ----  native ---- \n\n'
        do_bld bldnat
        ninja -j1 -v -C bldnat print_link_nativetrue
        ninja -j1 -v -C bldnat print_link_nativenone
        ninja -j1 -v -C bldnat print_link_nativefalse
    fi

    # One --cross-file
    if true; then
        printf '\n\n ---- cross ----- \n\n'
        do_bld bldcross --cross-file=cross-clang.ini
#        ninja -j1 -v -C bldcross print_link_nativetrue
#        ninja -j1 -v -C bldcross print_link_nativenone
        ninja -j1 -v -C bldcross print_link_nativefalse
    fi

}

main "$@"
