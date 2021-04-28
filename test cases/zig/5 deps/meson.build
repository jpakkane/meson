project('zigtest-deps', 'zig')

curl_dep = dependency('libcurl')
executable('zigtest-deps', 'src/main.zig',
    dependencies: curl_dep
)
