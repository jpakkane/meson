
// This code logs preprocessor values.

// It would be trivial to change this and assert() them in some
// automated test(s) instead.


#define QUOTE(unquoted) #unquoted
// QUOTE either "arg" iself, or its expansion if any.
#define stringify_value(arg) QUOTE(arg)

// As usual, undefined macros "expand to themselves".
#define name_value(arg) #arg "\texpands to ->\t" stringify_value(arg)

// clang makes #pragma message output look like a warning but -Werror
// doesn't actually fail

#if 1
// executable( c_args: ) never overwrites, always appends?
#pragma message name_value(executable_CPP_args)
#pragma message name_value(executable_C_args)
#endif

// In tentative partial order: if defined in two places AND they are
// mutually exclusive, then the first one should win.

#if 1
#pragma message name_value(CLIsetup_buildm_CPP_args)
#pragma message name_value(CLIsetup_buildm_C_args)
#pragma message name_value(CLIsetup_CPP_args)
#pragma message name_value(CLIsetup_C_args)

#pragma message name_value(project_default_options_buildm_CPP_args)
#pragma message name_value(project_default_options_buildm_C_args)
#pragma message name_value(project_default_options_CPP_args)
#pragma message name_value(project_default_options_C_args)

#pragma message name_value(env_CPPFLAGS)
#pragma message name_value(env_CFLAGS)

#pragma message name_value(cross_file_CPP_args)
#pragma message name_value(cross_file_C_args)

#pragma message name_value(add_global_args)
#pragma message name_value(add_project_args)

#endif


int main(int argc, char *argv[])
{
  return 0;
}
