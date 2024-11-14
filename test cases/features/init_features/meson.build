#project('test-features', 'c')
mod_features = import('features')
cpu_family = host_machine.cpu_family()
compiler_id = meson.get_compiler('c').get_id()
source_root = meson.project_source_root() + '/../init_features/'
# Basic X86 Features
# ------------------
SSE = mod_features.new(
  'SSE', 1,  args: '-msse',
  test_code: files(source_root + 'checks/cpu_sse.c')[0]
)
SSE2 = mod_features.new(
  'SSE2', 2, implies: SSE,
  args: '-msse2',
  test_code: files(source_root + 'checks/cpu_sse2.c')[0]
)
# enabling SSE without SSE2 is useless also
# it's non-optional for x86_64
SSE.update(implies: SSE2)
SSE3 = mod_features.new(
  'SSE3', 3, implies: SSE2,
  args: '-msse3',
  test_code: files(source_root + 'checks/cpu_sse3.c')[0]
)
SSSE3 = mod_features.new(
  'SSSE3', 4, implies: SSE3,
  args: '-mssse3',
  test_code: files(source_root + 'checks/cpu_ssse3.c')[0]
)
SSE41 = mod_features.new(
  'SSE41', 5, implies: SSSE3,
  args: '-msse4.1',
  test_code: files(source_root + 'checks/cpu_sse41.c')[0]
)
if cpu_family not in ['x86', 'x86_64']
  # should disable any prevalent features
  SSE.update(disable: 'not supported by the current platform')
endif
# Specializations for non unix-like compilers
if compiler_id == 'intel-cl'
  foreach fet : [SSE, SSE2, SSE3, SSSE3]
    fet.update(args: {'val': '/arch:' + fet.get('name'), 'match': '/arch:.*'})
  endforeach
  SSE41.update(args: {'val': '/arch:SSE4.1', 'match': '/arch:.*'})
elif compiler_id == 'msvc'
  # only available on 32-bit. Its enabled by default on 64-bit mode
  foreach fet : [SSE, SSE2]
    if cpu_family == 'x86'
      fet.update(args: {'val': '/arch:' + fet.get('name'), 'match': clear_arch})
    else
      fet.update(args: '')
    endif
  endforeach
  # The following features don't own private FLAGS still
  # the compiler provides ISA capability for them.
  foreach fet : [SSE3, SSSE3, SSE41]
    fet.update(args: '')
  endforeach
endif

# Basic ARM Features
# ------------------
NEON = mod_features.new(
  'NEON', 200,
  test_code: files(source_root + 'checks/cpu_neon.c')[0]
)
NEON_FP16 = mod_features.new(
  'NEON_FP16', 201, implies: NEON,
  test_code: files(source_root + 'checks/cpu_neon_fp16.c')[0]
)
# FMA
NEON_VFPV4 = mod_features.new(
  'NEON_VFPV4', 202, implies: NEON_FP16,
  test_code: files(source_root + 'checks/cpu_neon_vfpv4.c')[0]
)
# Advanced SIMD
ASIMD = mod_features.new(
  'ASIMD', 203, implies: NEON_VFPV4, detect: {'val': 'ASIMD', 'match': 'NEON.*'},
  test_code: files(source_root + 'checks/cpu_asimd.c')[0]
)
if cpu_family == 'aarch64'
  # hardware baseline, they can't be enabled independently
  NEON.update(implies: [NEON_FP16, NEON_VFPV4, ASIMD])
  NEON_FP16.update(implies: [NEON, NEON_VFPV4, ASIMD])
  NEON_VFPV4.update(implies: [NEON, NEON_FP16, ASIMD])
elif cpu_family == 'arm'
  NEON.update(args: '-mfpu=neon')
  NEON_FP16.update(args: ['-mfp16-format=ieee', {'val': '-mfpu=neon-fp16', 'match': '-mfpu=.*'}])
  NEON_VFPV4.update(args: {'val': '-mfpu=neon-vfpv4', 'match': '-mfpu=.*'})
  ASIMD.update(args: [
    {'val': '-mfpu=neon-fp-armv8', 'match': '-mfpu=.*'},
    '-march=armv8-a+simd'
  ])
else
  # should disable any prevalent features
  NEON.update(disable: 'not supported by the current platform')
endif

