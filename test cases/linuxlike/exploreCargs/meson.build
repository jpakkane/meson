
project('c_args test', 'c',
       default_options: [

          'build.cpp_args=-Dproject_default_options_buildm_CPP_args=___YES_project_defaults__',
          'build.c_args=-Dproject_default_options_buildm_C_args=___YES_project_defaults__',
          'build.c_link_args=-Wl,--undefined=project_default_options_buildm_C_link_args',

         'cpp_args=-Dproject_default_options_CPP_args=___YES_project_defaults__',
          'c_args=-Dproject_default_options_C_args=___YES_project_defaults__',
          'c_link_args=-Wl,--undefined=project_default_options_C_link_args',

        ]
)


# These also take native:true/false. The default value is: "!is_cross_build()"
add_global_arguments('-Dadd_global_args=___YES_add_global_args____', language : 'c')

add_project_arguments('-Dadd_project_args=___YES_add_project_args___', language : 'c')


YES_SIR = '___YES_executable_nativetrue___'
exe_true = executable('test_nativetrue.exe', 'test_params.c',     native:true,

          # Never overriden?
          cpp_args : '-Dexecutable_CPP_args=' + YES_SIR,
          c_args : '-Dexecutable_C_args=' + YES_SIR,
          link_args : '-Wl,--undefined=executable_nativetrue_C_link_args',

)
run_target('print_link_nativetrue',
      command : [ 'nm', '--undefined-only', exe_true ],
          )


YES_SIR = '___YES_executable_nativenone___'
exe_none = executable('test_nativenone.exe', 'test_params.c',    # native: none

          cpp_args : '-Dexecutable_CPP_args=' + YES_SIR,
          c_args : '-Dexecutable_C_args=' + YES_SIR,
          link_args : '-Wl,--undefined=executable_nativenone_C_link_args',
)
run_target('print_link_nativenone',
      command : [ 'nm', '--undefined-only', exe_none ]
)


YES_SIR = '___YES_executable_nativefalse___'
exe_false = executable('test_nativefalse.exe', 'test_params.c',   native:false,

          cpp_args : '-Dexecutable_CPP_args=' + YES_SIR,
          c_args : '-Dexecutable_C_args=' + YES_SIR,
          link_args : '-Wl,--undefined=executable_nativefalse_C_link_args',
)
run_target('print_link_nativefalse',
      command : [ 'nm', '--undefined-only', exe_false ],
          )




# To not look ugly, \n and \t need this workaround:
#   https://github.com/mesonbuild/meson/pull/6241
run_target('print_flags',
    command : [
      'printf',

#      '''\n\nget_option(cpp_args)\t=\t[%s]\n''' +
      'get_option(c_args)\\t=\\t[%s]\\n' +
      'get_option(c_link_args)\\t=\\t[%s]\\n' +

#      '''get_option(build.cpp_args)\t=\t[%s]\n''' +
      '''get_option(build.c_args)\t=\t[%s]\n''' +
      'get_option(build.c_link_args)\\t=\\t[%s]\\n' +

      'meson.get_cross_property(cpp_args, <empty>)\\t=\\t[%s]\\n' +
      'meson.get_cross_property(c_args, <empty>)\\t=\\t[%s]\\n' +
      'meson.get_cross_property(c_link_args, <empty>)\\t=\\t[%s]\\n' +
      'meson.get_cross_property(fubar, <empty>)\\t=\\t[%s]\\n',

#      ','.join(get_option('cpp_args')),
      ','.join(get_option('c_args')),
      ','.join(get_option('c_link_args')),

#      ','.join(get_option('build.cpp_args')),
      ','.join(get_option('build.c_args')),
      ','.join(get_option('build.c_link_args')),

# Unlike get_option(), .get_cross_property() is free-form.

      ','.join(meson.get_cross_property('cpp_args',
                                        ['<EMPTY>'])),
      ','.join(meson.get_cross_property('c_args',
                                        ['<EMPTY>'])),
      ','.join(meson.get_cross_property('c_link_args',
                                        ['<EMPTY>'])),
      ','.join(meson.get_cross_property('fubar',
                                        ['<EMPTY>'])),

           ]
)

