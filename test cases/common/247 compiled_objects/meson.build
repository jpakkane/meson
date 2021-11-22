project('compiled_objects', 'c')


no_objs = compiled_objects('no_objs', [])

objs_no_pic = compiled_objects('no-pic', ['dummy1.c'], pic: false)

objs_pic = compiled_objects('objs-pic', ['dummy1.c'], pic: true)

objs_implicit_pic = compiled_objects('objs-pic-impl', ['dummy1.c'])

objs_many = compiled_objects('objs-subd', ['dummy1.c', 'dummy2.c', 'src/dummy1.c'])

objs_bt = build_target('objs_bt', 'dummy1.c', target_type: 'objects')

# PIC
l1 = library('l1', ['dummy1.c'], objects: no_objs)
l2 = library('l2', ['dummy1.c'], objects: objs_no_pic, pic: false)
l3 = library('l3', ['dummy1.c'], objects: objs_pic, pic: true)
l4 = library('l4', ['dummy1.c'], objects: objs_implicit_pic, pic: true)

# [ExtractedObjects]
l5 = library('l5', ['dummy1.c'], objects: no_objs.extract_all_objects())
l6 = library('l6', ['dummy1.c'], objects: objs_many.extract_objects('dummy1.c'))
l7 = library('l7', ['dummy1.c'], objects: objs_many.extract_objects(['dummy2.c', files('src/dummy1.c')]))

# Extra <lang>_args
objs_args = compiled_objects('obj-args', 'error_if_ndef_MESON_MAGIC.c.c', c_args: '-DMESON_MAGIC')
