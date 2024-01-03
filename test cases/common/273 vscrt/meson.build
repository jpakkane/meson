project('vscrt',
    default_options: [
        'b_vscrt=from_buildtype',
        'buildtype=debug',
    ]
)


languages = ['c', 'cpp', 'cs', 'cuda', 'd', 'fortran', 'java', 'objc', 'objcpp', 'rust', 'vala', 'cython', 'nasm', 'masm']
foreach lang : languages
    if not add_languages(lang, required: false)
        continue
    endif

    compiler = meson.get_compiler(lang)
    compiler_id = compiler.get_id()
    message(f'testing compiler @compiler_id@ for language @lang@')

    if (compiler_id in ['dmd', 'ml', 'msvc']
            or compiler_id.endswith('-cl')
            or compiler_id in ['cuda', 'rustc'] and host_machine.system() == 'windows')
        crt = compiler.get_crt()
        assert(crt == 'mdd')
    else
        testcase expect_error('This compiler does not support Windows CRT selection')
            compiler.get_crt()
        endtestcase
    endif
endforeach
