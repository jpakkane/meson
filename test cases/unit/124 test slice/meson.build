project('test_slice')

python = import('python').find_installation('python3')

foreach i : range(10)
  test('test-' + (i + 1).to_string(),
    python,
    args: [
      meson.current_source_dir() / 'test.py'
    ],
  )
endforeach
