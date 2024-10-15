# Tests whether fortran sources files created during configuration are properly
# scanned for dependency information

project('generated', 'fortran',
  default_options : ['default_library=static'])

conf_data = configuration_data()
conf_data.set('ONE', 1)
conf_data.set('TWO', 2)

mod3_f = import('fs').copyfile('mod3.f90', 'mod3.f90')
three = library('mod3', mod3_f)

templates_basenames = ['mod2', 'mod1']
generated_sources = []
foreach template_basename : templates_basenames
  infilename = '@0@.fpp'.format(template_basename)
  outfilename = '@0@.f90'.format(template_basename)
  outfile = configure_file(
      input : infilename, output : outfilename, configuration : conf_data)
  generated_sources += [outfile]
endforeach

sources = ['prog.f90'] + generated_sources
exe = executable('configure_file', sources, link_with: three)
test('configure_file', exe)

gen = generator(
  find_program('gen.py'),
  arguments : [
    '@INPUT@', '@OUTPUT@',
    '--replace', '@ONE@=1',
    '--replace', '@TWO@=2',
  ],
  output : ['@BASENAME@.f90'],
)

exe = executable(
  'generator',
  'prog.f90', gen.process('mod1.fpp', 'mod2.fpp'),
  link_with: three,
)
test('generator', exe)
