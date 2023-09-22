project('rewritetest', 'cpp')

src1 = ['main.cpp', 'fileA.cpp']
src2 = files(['fileB.cpp', 'fileC.cpp'])
src3 = src1
src4 = [src3]
src5 = ['main.cpp', 'fileA.cpp']
src5 += ['fileB.cpp']
src6 = ['main.cpp', 'fileA.cpp']
src6 = files(src6)
src7 = ['main.cpp', 'fileA.cpp']
src8 = src7
src7 = ['fileB.cpp', 'fileC.cpp']
name = 'rightName'
trickyName = get_variable('name')
name = 'wrongName'

# Magic comment

exe0 = executable('trivialprog0', src1 + src2)
exe1 = executable('trivialprog1', src1)
exe2 = executable('trivialprog2', [src2])
exe3 = executable('trivialprog3', ['main.cpp', 'fileA.cpp'])
exe4 = executable('trivialprog4', ['main.cpp', ['fileA.cpp']])
exe5 = executable('trivialprog5', [src2, 'main.cpp'])
exe6 = executable('trivialprog6', 'main.cpp', 'fileA.cpp')
exe7 = executable('trivialprog7', 'fileB.cpp', get_variable('src1'), 'fileC.cpp')
exe8 = executable('trivialprog8', src3)
executable('trivialprog9', src4)
executable('trivialprog10', src5)
executable('trivialprog11', src6)
executable('trivialprog12', src8)
executable(trickyName, 'main.cpp')
