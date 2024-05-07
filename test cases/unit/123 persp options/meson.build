project('toplevel', 'c')

round = get_option('round')
opt = get_option('optimization')
if round == 1
   assert(opt == '1')
elif round == 2
   assert(opt == '1')
elif round == 3
   assert(opt == '1')
elif round == 4
   assert(opt == '3')
elif round == 5
   assert(opt == '3')
elif round == 6
   assert(opt == '3', opt)
else
  assert(false, 'Invalid round number')
endif

executable('toplevel', 'toplevel.c')

subproject('sub1')
subproject('sub2')
