project('should fail', 'c')

exe = executable('prog', 'failing.c')
test('should-failing', exe, should_fail : true)
test('expected-failing', exe, expected_fail : true)
