project(
    'gettext extractor',
    'c',
    default_options: {'default_library': 'static'},
    meson_version: '1.7.0',
)

if not find_program('xgettext', required: false).found()
    error('MESON_SKIP_TEST xgettext command not found')
endif

i18n = import('i18n')
xgettext_args = ['-ktr', '--add-comments=TRANSLATOR:', '--from-code=UTF-8']

subdir('src')
