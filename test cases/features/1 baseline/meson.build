project('baseline', 'c')
subdir('init_features')

baseline = mod_features.test(SSE3, NEON, anyfet: true)
message(baseline)
baseline_args = baseline[1]['args']
foreach def : baseline[1]['defines']
    baseline_args += ['-DHAVE_' + def]
endforeach
add_project_arguments(baseline_args, language: ['c', 'cpp'])

exe = executable('baseline', 'baseline.c')
test('baseline', exe)

