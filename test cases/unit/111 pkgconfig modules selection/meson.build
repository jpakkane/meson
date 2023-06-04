project('modules_test', 'c')

case_num = get_option('case_num')

if case_num == 0
  dep_mods = dependency('modules') # all modules
elif case_num == 1
  dep_mods = dependency('modules', modules : ['foo1'])
elif case_num == 2
  dep_mods = dependency('modules', modules : ['foo1', 'foo2'])
elif case_num == 3
  dep_mods = dependency('modules', modules : ['foo3'])
elif case_num == 4
  dep_mods = dependency('modules', modules : ['foo4', 'foo5'])
elif case_num == 5
  dep_mods = dependency('modules', modules : ['foo5'])
elif case_num == 6
  dep_mods = dependency('modules', modules : ['foo1', 'foo3', 'foo5'])
elif case_num == 7
  dep_mods = dependency('modules', modules : []) #header only

elif case_num == 8
  dep_mods = dependency('modules_frameworks') # all modules
elif case_num == 9
  dep_mods = dependency('modules_frameworks', modules : ['frmwk1'])
elif case_num == 10
  dep_mods = dependency('modules_frameworks', modules : ['frmwk1', 'frmwk2'])
elif case_num == 11
  dep_mods = dependency('modules_frameworks', modules : ['frmwk3'])
elif case_num == 12
  dep_mods = dependency('modules_frameworks', modules : ['frmwk4', 'frmwk5'])
elif case_num == 13
  dep_mods = dependency('modules_frameworks', modules : ['frmwk5'])
elif case_num == 14
  dep_mods = dependency('modules_frameworks', modules : ['frmwk1', 'frmwk3', 'frmwk5'])
elif case_num == 15
  dep_mods = dependency('modules_frameworks', modules : []) #header only

elif case_num == 16
  dep_mods = dependency('modules_combined', modules : ['frmwk1', 'foo1'])
elif case_num == 17
  dep_mods = dependency('modules_combined', modules : ['frmwk2', 'foo2'])
elif case_num == 18
  dep_mods = dependency('modules_combined', modules : ['foo1', 'foo2', 'frmwk2', 'frmwk3'])
elif case_num == 19
  dep_mods = dependency('modules_combined', modules : ['foo3'])
elif case_num == 20
  dep_mods = dependency('modules_combined', modules : ['frmwk3'])

else
  error('not supported case')
endif

executable('mod_test', 'prog.c', dependencies : [dep_mods])
