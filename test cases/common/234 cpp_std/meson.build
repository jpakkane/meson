project('cpp_std', 'cpp')
cpp_std = get_option('cpp_std')
# values from https://gcc.gnu.org/onlinedocs/cpp/Standard-Predefined-Macros.html
cpp_std_values = {
  'c++98': '199711L',
  'c++11': '201103L',
  'c++14': '201402L',
  'c++17': '201703L '
}
exe = executable('prog', 'prog.cpp', cpp_args: ['-DEXPECTED=@0@'.format(cpp_std_values[cpp_std])])
