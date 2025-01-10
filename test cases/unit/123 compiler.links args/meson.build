# https://github.com/mesonbuild/meson/issues/13610

project('279 compiler.links args', 'c')
cc = meson.get_compiler('c')

gcov_str = '''
#include <gcov.h>
int main(void) {
  __gcov_dump();
  return 0;
}
'''

if cc.links(gcov_str)
  message('gcov links successfully')
else
  error('gcov does not link')
endif
