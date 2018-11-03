# Copyright 2012-2017 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import re
import shlex
import pickle
import subprocess
from collections import OrderedDict
import itertools
from pathlib import PurePath
from functools import lru_cache

from . import backends
from .. import modules
from .. import environment, mesonlib
from .. import build
from .. import mlog
from .. import dependencies
from .. import compilers
from ..compilers import CompilerArgs, CCompiler
from ..linkers import ArLinker
from ..mesonlib import File, MesonException, OrderedSet
from ..mesonlib import get_compiler_for_source, has_path_sep
from .backends import CleanTrees
from ..build import InvalidArguments

if mesonlib.is_windows():
    quote_func = lambda s: '"{}"'.format(s)
    execute_wrapper = 'cmd /c'
    rmfile_prefix = 'del /f /s /q {} &&'
else:
    quote_func = shlex.quote
    execute_wrapper = ''
    rmfile_prefix = 'rm -f {} &&'

def ninja_quote(text, is_build_line=False):
    if is_build_line:
        qcs = ('$', ' ', ':')
    else:
        qcs = ('$', ' ')
    for char in qcs:
        text = text.replace(char, '$' + char)
    if '\n' in text:
        errmsg = '''Ninja does not support newlines in rules. The content was:

%s

Please report this error with a test case to the Meson bug tracker.''' % text
        raise MesonException(errmsg)
    return text


class NinjaBuildElement:
    def __init__(self, all_outputs, outfilenames, rule, infilenames):
        if isinstance(outfilenames, str):
            self.outfilenames = [outfilenames]
        else:
            self.outfilenames = outfilenames
        assert(isinstance(rule, str))
        self.rule = rule
        if isinstance(infilenames, str):
            self.infilenames = [infilenames]
        else:
            self.infilenames = infilenames
        self.deps = OrderedSet()
        self.orderdeps = OrderedSet()
        self.elems = []
        self.all_outputs = all_outputs

    def add_dep(self, dep):
        if isinstance(dep, list):
            self.deps.update(dep)
        else:
            self.deps.add(dep)

    def add_orderdep(self, dep):
        if isinstance(dep, list):
            self.orderdeps.update(dep)
        else:
            self.orderdeps.add(dep)

    def add_item(self, name, elems):
        if isinstance(elems, str):
            elems = [elems]
        self.elems.append((name, elems))

    def write(self, outfile):
        self.check_outputs()
        line = 'build %s: %s %s' % (' '.join([ninja_quote(i, True) for i in self.outfilenames]),
                                    self.rule,
                                    ' '.join([ninja_quote(i, True) for i in self.infilenames]))
        if len(self.deps) > 0:
            line += ' | ' + ' '.join([ninja_quote(x, True) for x in self.deps])
        if len(self.orderdeps) > 0:
            line += ' || ' + ' '.join([ninja_quote(x, True) for x in self.orderdeps])
        line += '\n'
        # This is the only way I could find to make this work on all
        # platforms including Windows command shell. Slash is a dir separator
        # on Windows, too, so all characters are unambiguous and, more importantly,
        # do not require quoting, unless explicitely specified, which is necessary for
        # the csc compiler.
        line = line.replace('\\', '/')
        outfile.write(line)

        # All the entries that should remain unquoted
        raw_names = {'DEPFILE', 'DESC', 'pool', 'description'}

        for e in self.elems:
            (name, elems) = e
            should_quote = name not in raw_names
            line = ' %s = ' % name
            newelems = []
            for i in elems:
                if not should_quote or i == '&&': # Hackety hack hack
                    quoter = ninja_quote
                else:
                    quoter = lambda x: ninja_quote(quote_func(x))
                i = i.replace('\\', '\\\\')
                if quote_func('') == '""':
                    i = i.replace('"', '\\"')
                newelems.append(quoter(i))
            line += ' '.join(newelems)
            line += '\n'
            outfile.write(line)
        outfile.write('\n')

    def check_outputs(self):
        for n in self.outfilenames:
            if n in self.all_outputs:
                raise MesonException('Multiple producers for Ninja target "%s". Please rename your targets.' % n)
            self.all_outputs[n] = True

class NinjaBackend(backends.Backend):

    def __init__(self, build):
        super().__init__(build)
        self.name = 'ninja'
        self.ninja_filename = 'build.ninja'
        self.fortran_deps = {}
        self.all_outputs = {}

    def create_target_alias(self, to_target, outfile):
        # We need to use aliases for targets that might be used as directory
        # names to workaround a Ninja bug that breaks `ninja -t clean`.
        # This is used for 'reserved' targets such as 'test', 'install',
        # 'benchmark', etc, and also for RunTargets.
        # https://github.com/mesonbuild/meson/issues/1644
        if not to_target.startswith('meson-'):
            m = 'Invalid usage of create_target_alias with {!r}'
            raise AssertionError(m.format(to_target))
        from_target = to_target[len('meson-'):]
        elem = NinjaBuildElement(self.all_outputs, from_target, 'phony', to_target)
        elem.write(outfile)

    def detect_vs_dep_prefix(self, tempfilename):
        '''VS writes its dependency in a locale dependent format.
        Detect the search prefix to use.'''
        for compiler in self.build.compilers.values():
            # Have to detect the dependency format
            if compiler.id == 'msvc':
                break
        else:
            # None of our compilers are MSVC, we're done.
            return open(tempfilename, 'a', encoding='utf-8')
        filename = os.path.join(self.environment.get_scratch_dir(),
                                'incdetect.c')
        with open(filename, 'w') as f:
            f.write('''#include<stdio.h>
int dummy;
''')

        # The output of cl dependency information is language
        # and locale dependent. Any attempt at converting it to
        # Python strings leads to failure. We _must_ do this detection
        # in raw byte mode and write the result in raw bytes.
        pc = subprocess.Popen(['cl', '/showIncludes', '/c', 'incdetect.c'],
                              cwd=self.environment.get_scratch_dir(),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (stdo, _) = pc.communicate()

        # We want to match 'Note: including file: ' in the line
        # 'Note: including file: d:\MyDir\include\stdio.h', however
        # different locales have different messages with a different
        # number of colons. Match up to the the drive name 'd:\'.
        matchre = re.compile(rb"^(.*\s)[a-zA-Z]:\\.*stdio.h$")
        for line in stdo.split(b'\r\n'):
            match = matchre.match(line)
            if match:
                with open(tempfilename, 'ab') as binfile:
                    binfile.write(b'msvc_deps_prefix = ' + match.group(1) + b'\n')
                return open(tempfilename, 'a', encoding='utf-8')
        raise MesonException('Could not determine vs dep dependency prefix string.')

    def generate(self, interp):
        self.interpreter = interp
        self.ninja_command = environment.detect_ninja(log=True)
        if self.ninja_command is None:
            raise MesonException('Could not detect Ninja v1.5 or newer')
        outfilename = os.path.join(self.environment.get_build_dir(), self.ninja_filename)
        tempfilename = outfilename + '~'
        with open(tempfilename, 'w', encoding='utf-8') as outfile:
            outfile.write('# This is the build file for project "%s"\n' %
                          self.build.get_project())
            outfile.write('# It is autogenerated by the Meson build system.\n')
            outfile.write('# Do not edit by hand.\n\n')
            outfile.write('ninja_required_version = 1.5.1\n\n')
        with self.detect_vs_dep_prefix(tempfilename) as outfile:
            self.generate_rules(outfile)
            self.generate_phony(outfile)
            outfile.write('# Build rules for targets\n\n')
            for t in self.build.get_targets().values():
                self.generate_target(t, outfile)
            outfile.write('# Test rules\n\n')
            self.generate_tests(outfile)
            outfile.write('# Install rules\n\n')
            self.generate_install(outfile)
            self.generate_dist(outfile)
            if 'b_coverage' in self.environment.coredata.base_options and \
                    self.environment.coredata.base_options['b_coverage'].value:
                outfile.write('# Coverage rules\n\n')
                self.generate_coverage_rules(outfile)
            outfile.write('# Suffix\n\n')
            self.generate_utils(outfile)
            self.generate_ending(outfile)
        # Only overwrite the old build file after the new one has been
        # fully created.
        os.replace(tempfilename, outfilename)
        self.generate_compdb()

    # http://clang.llvm.org/docs/JSONCompilationDatabase.html
    def generate_compdb(self):
        pch_compilers = ['%s_PCH' % i for i in self.build.compilers]
        native_compilers = ['%s_COMPILER' % i for i in self.build.compilers]
        cross_compilers = ['%s_CROSS_COMPILER' % i for i in self.build.cross_compilers]
        ninja_compdb = [self.ninja_command, '-t', 'compdb'] + pch_compilers + native_compilers + cross_compilers
        builddir = self.environment.get_build_dir()
        try:
            jsondb = subprocess.check_output(ninja_compdb, cwd=builddir)
            with open(os.path.join(builddir, 'compile_commands.json'), 'wb') as f:
                f.write(jsondb)
        except Exception:
            mlog.warning('Could not create compilation database.')

    # Get all generated headers. Any source file might need them so
    # we need to add an order dependency to them.
    def get_generated_headers(self, target):
        if hasattr(target, 'cached_generated_headers'):
            return target.cached_generated_headers
        header_deps = []
        # XXX: Why don't we add deps to CustomTarget headers here?
        for genlist in target.get_generated_sources():
            if isinstance(genlist, (build.CustomTarget, build.CustomTargetIndex)):
                continue
            for src in genlist.get_outputs():
                if self.environment.is_header(src):
                    header_deps.append(self.get_target_generated_dir(target, genlist, src))
        if 'vala' in target.compilers and not isinstance(target, build.Executable):
            vala_header = File.from_built_file(self.get_target_dir(target), target.vala_header)
            header_deps.append(vala_header)
        # Recurse and find generated headers
        for dep in itertools.chain(target.link_targets, target.link_whole_targets):
            if isinstance(dep, (build.StaticLibrary, build.SharedLibrary)):
                header_deps += self.get_generated_headers(dep)
        target.cached_generated_headers = header_deps
        return header_deps

    def get_target_generated_sources(self, target):
        """
        Returns a dictionary with the keys being the path to the file
        (relative to the build directory) of that type and the value
        being the GeneratorList or CustomTarget that generated it.
        """
        srcs = OrderedDict()
        for gensrc in target.get_generated_sources():
            for s in gensrc.get_outputs():
                f = self.get_target_generated_dir(target, gensrc, s)
                srcs[f] = s
        return srcs

    def get_target_sources(self, target):
        srcs = OrderedDict()
        for s in target.get_sources():
            # BuildTarget sources are always mesonlib.File files which are
            # either in the source root, or generated with configure_file and
            # in the build root
            if not isinstance(s, File):
                raise InvalidArguments('All sources in target {!r} must be of type mesonlib.File'.format(s))
            f = s.rel_to_builddir(self.build_to_src)
            srcs[f] = s
        return srcs

    # Languages that can mix with C or C++ but don't support unity builds yet
    # because the syntax we use for unity builds is specific to C/++/ObjC/++.
    # Assembly files cannot be unitified and neither can LLVM IR files
    langs_cant_unity = ('d', 'fortran')

    def get_target_source_can_unity(self, target, source):
        if isinstance(source, File):
            source = source.fname
        if self.environment.is_llvm_ir(source) or \
           self.environment.is_assembly(source):
            return False
        suffix = os.path.splitext(source)[1][1:]
        for lang in self.langs_cant_unity:
            if lang not in target.compilers:
                continue
            if suffix in target.compilers[lang].file_suffixes:
                return False
        return True

    def generate_target(self, target, outfile):
        if isinstance(target, build.CustomTarget):
            self.generate_custom_target(target, outfile)
        if isinstance(target, build.RunTarget):
            self.generate_run_target(target, outfile)
        name = target.get_id()
        if name in self.processed_targets:
            return
        self.processed_targets[name] = True
        # Generate rules for all dependency targets
        self.process_target_dependencies(target, outfile)
        # If target uses a language that cannot link to C objects,
        # just generate for that language and return.
        if isinstance(target, build.Jar):
            self.generate_jar_target(target, outfile)
            return
        if 'rust' in target.compilers:
            self.generate_rust_target(target, outfile)
            return
        if 'cs' in target.compilers:
            self.generate_cs_target(target, outfile)
            return
        if 'swift' in target.compilers:
            self.generate_swift_target(target, outfile)
            return

        # Now we handle the following languages:
        # ObjC++, ObjC, C++, C, D, Fortran, Vala

        # target_sources:
        #   Pre-existing target C/C++ sources to be built; dict of full path to
        #   source relative to build root and the original File object.
        # generated_sources:
        #   GeneratedList and CustomTarget sources to be built; dict of the full
        #   path to source relative to build root and the generating target/list
        # vala_generated_sources:
        #   Array of sources generated by valac that have to be compiled
        if 'vala' in target.compilers:
            # Sources consumed by valac are filtered out. These only contain
            # C/C++ sources, objects, generated libs, and unknown sources now.
            target_sources, generated_sources, \
                vala_generated_sources = self.generate_vala_compile(target, outfile)
        else:
            target_sources = self.get_target_sources(target)
            generated_sources = self.get_target_generated_sources(target)
            vala_generated_sources = []
        self.scan_fortran_module_outputs(target)
        # Generate rules for GeneratedLists
        self.generate_generator_list_rules(target, outfile)

        # Generate rules for building the remaining source files in this target
        outname = self.get_target_filename(target)
        obj_list = []
        use_pch = self.environment.coredata.base_options.get('b_pch', False)
        is_unity = self.is_unity(target)
        if use_pch and target.has_pch():
            pch_objects = self.generate_pch(target, outfile)
        else:
            pch_objects = []
        header_deps = []
        unity_src = []
        unity_deps = [] # Generated sources that must be built before compiling a Unity target.
        header_deps += self.get_generated_headers(target)

        if is_unity:
            # Warn about incompatible sources if a unity build is enabled
            langs = set(target.compilers.keys())
            langs_cant = langs.intersection(self.langs_cant_unity)
            if langs_cant:
                langs_are = langs = ', '.join(langs_cant).upper()
                langs_are += ' are' if len(langs_cant) > 1 else ' is'
                msg = '{} not supported in Unity builds yet, so {} ' \
                      'sources in the {!r} target will be compiled normally' \
                      ''.format(langs_are, langs, target.name)
                mlog.log(mlog.red('FIXME'), msg)

        # Get a list of all generated headers that will be needed while building
        # this target's sources (generated sources and pre-existing sources).
        # This will be set as dependencies of all the target's sources. At the
        # same time, also deal with generated sources that need to be compiled.
        generated_source_files = []
        for rel_src, gensrc in generated_sources.items():
            dirpart, fnamepart = os.path.split(rel_src)
            raw_src = File(True, dirpart, fnamepart)
            if self.environment.is_source(rel_src) and not self.environment.is_header(rel_src):
                if is_unity and self.get_target_source_can_unity(target, rel_src):
                    unity_deps.append(raw_src)
                    abs_src = os.path.join(self.environment.get_build_dir(), rel_src)
                    unity_src.append(abs_src)
                else:
                    generated_source_files.append(raw_src)
            elif self.environment.is_object(rel_src):
                obj_list.append(rel_src)
            elif self.environment.is_library(rel_src):
                pass
            else:
                # Assume anything not specifically a source file is a header. This is because
                # people generate files with weird suffixes (.inc, .fh) that they then include
                # in their source files.
                header_deps.append(raw_src)
        # These are the generated source files that need to be built for use by
        # this target. We create the Ninja build file elements for this here
        # because we need `header_deps` to be fully generated in the above loop.
        for src in generated_source_files:
            if self.environment.is_llvm_ir(src):
                o = self.generate_llvm_ir_compile(target, outfile, src)
            else:
                o = self.generate_single_compile(target, outfile, src, True,
                                                 header_deps=header_deps)
            obj_list.append(o)

        # Generate compilation targets for C sources generated from Vala
        # sources. This can be extended to other $LANG->C compilers later if
        # necessary. This needs to be separate for at least Vala
        vala_generated_source_files = []
        for src in vala_generated_sources:
            dirpart, fnamepart = os.path.split(src)
            raw_src = File(True, dirpart, fnamepart)
            if is_unity:
                unity_src.append(os.path.join(self.environment.get_build_dir(), src))
                header_deps.append(raw_src)
            else:
                # Generated targets are ordered deps because the must exist
                # before the sources compiling them are used. After the first
                # compile we get precise dependency info from dep files.
                # This should work in all cases. If it does not, then just
                # move them from orderdeps to proper deps.
                if self.environment.is_header(src):
                    header_deps.append(raw_src)
                else:
                    # We gather all these and generate compile rules below
                    # after `header_deps` (above) is fully generated
                    vala_generated_source_files.append(raw_src)
        for src in vala_generated_source_files:
            # Passing 'vala' here signifies that we want the compile
            # arguments to be specialized for C code generated by
            # valac. For instance, no warnings should be emitted.
            obj_list.append(self.generate_single_compile(target, outfile, src, 'vala', [], header_deps))

        # Generate compile targets for all the pre-existing sources for this target
        for f, src in target_sources.items():
            if not self.environment.is_header(src):
                if self.environment.is_llvm_ir(src):
                    obj_list.append(self.generate_llvm_ir_compile(target, outfile, src))
                elif is_unity and self.get_target_source_can_unity(target, src):
                    abs_src = os.path.join(self.environment.get_build_dir(),
                                           src.rel_to_builddir(self.build_to_src))
                    unity_src.append(abs_src)
                else:
                    obj_list.append(self.generate_single_compile(target, outfile, src, False, [], header_deps))
        obj_list += self.flatten_object_list(target)
        if is_unity:
            for src in self.generate_unity_files(target, unity_src):
                obj_list.append(self.generate_single_compile(target, outfile, src, True, unity_deps + header_deps))
        linker, stdlib_args = self.determine_linker_and_stdlib_args(target)
        elem = self.generate_link(target, outfile, outname, obj_list, linker, pch_objects, stdlib_args=stdlib_args)
        self.generate_shlib_aliases(target, self.get_target_dir(target))
        elem.write(outfile)

    def process_target_dependencies(self, target, outfile):
        for t in target.get_dependencies():
            if t.get_id() not in self.processed_targets:
                self.generate_target(t, outfile)

    def custom_target_generator_inputs(self, target, outfile):
        for s in target.sources:
            if hasattr(s, 'held_object'):
                s = s.held_object
            if isinstance(s, build.GeneratedList):
                self.generate_genlist_for_target(s, target, outfile)

    def unwrap_dep_list(self, target):
        deps = []
        for i in target.get_dependencies():
            # FIXME, should not grab element at zero but rather expand all.
            if isinstance(i, list):
                i = i[0]
            # Add a dependency on all the outputs of this target
            for output in i.get_outputs():
                deps.append(os.path.join(self.get_target_dir(i), output))
        return deps

    def generate_custom_target(self, target, outfile):
        self.custom_target_generator_inputs(target, outfile)
        (srcs, ofilenames, cmd) = self.eval_custom_target_command(target)
        deps = self.unwrap_dep_list(target)
        deps += self.get_custom_target_depend_files(target)
        desc = 'Generating {0} with a {1} command.'
        if target.build_always_stale:
            deps.append('PHONY')
        if target.depfile is None:
            rulename = 'CUSTOM_COMMAND'
        else:
            rulename = 'CUSTOM_COMMAND_DEP'
        elem = NinjaBuildElement(self.all_outputs, ofilenames, rulename, srcs)
        elem.add_dep(deps)
        for d in target.extra_depends:
            # Add a dependency on all the outputs of this target
            for output in d.get_outputs():
                elem.add_dep(os.path.join(self.get_target_dir(d), output))
        serialize = False
        extra_paths = []
        # If the target requires capturing stdout, then use the serialized
        # executable wrapper to capture that output and save it to a file.
        if target.capture:
            serialize = True
        # If the command line requires a newline, also use the wrapper, as
        # ninja does not support them in its build rule syntax.
        if any('\n' in c for c in cmd):
            serialize = True
        # Windows doesn't have -rpath, so for EXEs that need DLLs built within
        # the project, we need to set PATH so the DLLs are found. We use
        # a serialized executable wrapper for that and check if the
        # CustomTarget command needs extra paths first.
        is_cross = self.environment.is_cross_build() and \
            self.environment.cross_info.need_cross_compiler() and \
            self.environment.cross_info.need_exe_wrapper()
        if mesonlib.for_windows(is_cross, self.environment) or \
           mesonlib.for_cygwin(is_cross, self.environment):
            extra_bdeps = target.get_transitive_build_target_deps()
            extra_paths = self.determine_windows_extra_paths(target.command[0],
                                                             extra_bdeps, is_cross)
            if extra_paths:
                serialize = True
        if serialize:
            exe_data = self.serialize_executable(target.name, target.command[0], cmd[1:],
                                                 # All targets are built from the build dir
                                                 self.environment.get_build_dir(),
                                                 extra_paths=extra_paths,
                                                 capture=ofilenames[0] if target.capture else None)
            cmd = self.environment.get_build_command() + ['--internal', 'exe', exe_data]
            cmd_type = 'meson_exe.py custom'
        else:
            cmd_type = 'custom'
        if target.depfile is not None:
            depfile = target.get_dep_outname(elem.infilenames)
            rel_dfile = os.path.join(self.get_target_dir(target), depfile)
            abs_pdir = os.path.join(self.environment.get_build_dir(), self.get_target_dir(target))
            os.makedirs(abs_pdir, exist_ok=True)
            elem.add_item('DEPFILE', rel_dfile)
        if target.console:
            elem.add_item('pool', 'console')
        cmd = self.replace_paths(target, cmd)
        elem.add_item('COMMAND', cmd)
        elem.add_item('description', desc.format(target.name, cmd_type))
        elem.write(outfile)
        self.processed_targets[target.get_id()] = True

    def generate_run_target(self, target, outfile):
        cmd = self.environment.get_build_command() + ['--internal', 'commandrunner']
        deps = self.unwrap_dep_list(target)
        arg_strings = []
        for i in target.args:
            if isinstance(i, str):
                arg_strings.append(i)
            elif isinstance(i, (build.BuildTarget, build.CustomTarget)):
                relfname = self.get_target_filename(i)
                arg_strings.append(os.path.join(self.environment.get_build_dir(), relfname))
                deps.append(relfname)
            elif isinstance(i, mesonlib.File):
                relfname = i.rel_to_builddir(self.build_to_src)
                arg_strings.append(os.path.join(self.environment.get_build_dir(), relfname))
            else:
                raise AssertionError('Unreachable code in generate_run_target: ' + str(i))
        if target.subproject != '':
            subproject_prefix = '{}@@'.format(target.subproject)
        else:
            subproject_prefix = ''
        target_name = 'meson-{}{}'.format(subproject_prefix, target.name)
        elem = NinjaBuildElement(self.all_outputs, target_name, 'CUSTOM_COMMAND', [])
        cmd += [self.environment.get_source_dir(),
                self.environment.get_build_dir(),
                target.subdir] + self.environment.get_build_command()
        texe = target.command
        try:
            texe = texe.held_object
        except AttributeError:
            pass
        if isinstance(texe, build.Executable):
            abs_exe = os.path.join(self.environment.get_build_dir(), self.get_target_filename(texe))
            deps.append(self.get_target_filename(texe))
            if self.environment.is_cross_build():
                exe_wrap = self.environment.get_exe_wrapper()
                if exe_wrap:
                    if not exe_wrap.found():
                        msg = 'The exe_wrapper {!r} defined in the cross file is ' \
                              'needed by run target {!r}, but was not found. ' \
                              'Please check the command and/or add it to PATH.'
                        raise MesonException(msg.format(exe_wrap.name, target.name))
                    cmd += exe_wrap.get_command()
            cmd.append(abs_exe)
        elif isinstance(texe, dependencies.ExternalProgram):
            cmd += texe.get_command()
        elif isinstance(texe, build.CustomTarget):
            deps.append(self.get_target_filename(texe))
            cmd += [os.path.join(self.environment.get_build_dir(), self.get_target_filename(texe))]
        elif isinstance(texe, mesonlib.File):
            cmd.append(texe.absolute_path(self.environment.get_source_dir(), self.environment.get_build_dir()))
        else:
            cmd.append(target.command)
        cmd += arg_strings

        elem.add_dep(deps)
        cmd = self.replace_paths(target, cmd)
        elem.add_item('COMMAND', cmd)
        elem.add_item('description', 'Running external command %s.' % target.name)
        elem.add_item('pool', 'console')
        elem.write(outfile)
        # Alias that runs the target defined above with the name the user specified
        self.create_target_alias(target_name, outfile)
        self.processed_targets[target.get_id()] = True

    def generate_coverage_command(self, elem, outputs):
        elem.add_item('COMMAND', self.environment.get_build_command() +
                      ['--internal', 'coverage'] +
                      outputs +
                      [self.environment.get_source_dir(),
                       os.path.join(self.environment.get_source_dir(),
                                    self.build.get_subproject_dir()),
                       self.environment.get_build_dir(),
                       self.environment.get_log_dir()])

    def generate_coverage_rules(self, outfile):
        e = NinjaBuildElement(self.all_outputs, 'meson-coverage', 'CUSTOM_COMMAND', 'PHONY')
        self.generate_coverage_command(e, [])
        e.add_item('description', 'Generates coverage reports.')
        e.write(outfile)
        # Alias that runs the target defined above
        self.create_target_alias('meson-coverage', outfile)
        self.generate_coverage_legacy_rules(outfile)

    def generate_coverage_legacy_rules(self, outfile):
        e = NinjaBuildElement(self.all_outputs, 'meson-coverage-xml', 'CUSTOM_COMMAND', 'PHONY')
        self.generate_coverage_command(e, ['--xml'])
        e.add_item('description', 'Generates XML coverage report.')
        e.write(outfile)
        # Alias that runs the target defined above
        self.create_target_alias('meson-coverage-xml', outfile)

        e = NinjaBuildElement(self.all_outputs, 'meson-coverage-text', 'CUSTOM_COMMAND', 'PHONY')
        self.generate_coverage_command(e, ['--text'])
        e.add_item('description', 'Generates text coverage report.')
        e.write(outfile)
        # Alias that runs the target defined above
        self.create_target_alias('meson-coverage-text', outfile)

        e = NinjaBuildElement(self.all_outputs, 'meson-coverage-html', 'CUSTOM_COMMAND', 'PHONY')
        self.generate_coverage_command(e, ['--html'])
        e.add_item('description', 'Generates HTML coverage report.')
        e.write(outfile)
        # Alias that runs the target defined above
        self.create_target_alias('meson-coverage-html', outfile)

    def generate_install(self, outfile):
        self.create_install_data_files()
        elem = NinjaBuildElement(self.all_outputs, 'meson-install', 'CUSTOM_COMMAND', 'PHONY')
        elem.add_dep('all')
        elem.add_item('DESC', 'Installing files.')
        elem.add_item('COMMAND', self.environment.get_build_command() + ['install', '--no-rebuild'])
        elem.add_item('pool', 'console')
        elem.write(outfile)
        # Alias that runs the target defined above
        self.create_target_alias('meson-install', outfile)

    def generate_tests(self, outfile):
        self.serialize_tests()
        cmd = self.environment.get_build_command(True) + ['test', '--no-rebuild']
        if not self.environment.coredata.get_builtin_option('stdsplit'):
            cmd += ['--no-stdsplit']
        if self.environment.coredata.get_builtin_option('errorlogs'):
            cmd += ['--print-errorlogs']
        elem = NinjaBuildElement(self.all_outputs, 'meson-test', 'CUSTOM_COMMAND', ['all', 'PHONY'])
        elem.add_item('COMMAND', cmd)
        elem.add_item('DESC', 'Running all tests.')
        elem.add_item('pool', 'console')
        elem.write(outfile)
        # Alias that runs the above-defined meson-test target
        self.create_target_alias('meson-test', outfile)

        # And then benchmarks.
        cmd = self.environment.get_build_command(True) + [
            'test', '--benchmark', '--logbase',
            'benchmarklog', '--num-processes=1', '--no-rebuild']
        elem = NinjaBuildElement(self.all_outputs, 'meson-benchmark', 'CUSTOM_COMMAND', ['all', 'PHONY'])
        elem.add_item('COMMAND', cmd)
        elem.add_item('DESC', 'Running benchmark suite.')
        elem.add_item('pool', 'console')
        elem.write(outfile)
        # Alias that runs the above-defined meson-benchmark target
        self.create_target_alias('meson-benchmark', outfile)

    def generate_rules(self, outfile):
        outfile.write('# Rules for compiling.\n\n')
        self.generate_compile_rules(outfile)
        outfile.write('# Rules for linking.\n\n')
        num_pools = self.environment.coredata.backend_options['backend_max_links'].value
        if num_pools > 0:
            outfile.write('''pool link_pool
  depth = %d

''' % num_pools)
        if self.environment.is_cross_build():
            self.generate_static_link_rules(True, outfile)
        self.generate_static_link_rules(False, outfile)
        self.generate_dynamic_link_rules(outfile)
        outfile.write('# Other rules\n\n')
        outfile.write('rule CUSTOM_COMMAND\n')
        outfile.write(' command = $COMMAND\n')
        outfile.write(' description = $DESC\n')
        outfile.write(' restat = 1\n\n')
        # Ninja errors out if you have deps = gcc but no depfile, so we must
        # have two rules for custom commands.
        outfile.write('rule CUSTOM_COMMAND_DEP\n')
        outfile.write(' command = $COMMAND\n')
        outfile.write(' description = $DESC\n')
        outfile.write(' deps = gcc\n')
        outfile.write(' depfile = $DEPFILE\n')
        outfile.write(' restat = 1\n\n')
        outfile.write('rule REGENERATE_BUILD\n')
        c = [ninja_quote(quote_func(x)) for x in self.environment.get_build_command()] + \
            ['--internal',
             'regenerate',
             ninja_quote(quote_func(self.environment.get_source_dir())),
             ninja_quote(quote_func(self.environment.get_build_dir()))]
        outfile.write(" command = " + ' '.join(c) + ' --backend ninja\n')
        outfile.write(' description = Regenerating build files.\n')
        outfile.write(' generator = 1\n\n')
        outfile.write('\n')

    def generate_phony(self, outfile):
        outfile.write('# Phony build target, always out of date\n')
        outfile.write('build PHONY: phony\n')
        outfile.write('\n')

    def generate_jar_target(self, target, outfile):
        fname = target.get_filename()
        outname_rel = os.path.join(self.get_target_dir(target), fname)
        src_list = target.get_sources()
        class_list = []
        compiler = target.compilers['java']
        c = 'c'
        m = 'm'
        e = ''
        f = 'f'
        main_class = target.get_main_class()
        if main_class != '':
            e = 'e'

        # Add possible java generated files to src list
        generated_sources = self.get_target_generated_sources(target)
        for rel_src, gensrc in generated_sources.items():
            dirpart, fnamepart = os.path.split(rel_src)
            raw_src = File(True, dirpart, fnamepart)
            if rel_src.endswith('.java'):
                src_list.append(raw_src)

        for src in src_list:
            plain_class_path = self.generate_single_java_compile(src, target, compiler, outfile)
            class_list.append(plain_class_path)
        class_dep_list = [os.path.join(self.get_target_private_dir(target), i) for i in class_list]
        manifest_path = os.path.join(self.get_target_private_dir(target), 'META-INF', 'MANIFEST.MF')
        manifest_fullpath = os.path.join(self.environment.get_build_dir(), manifest_path)
        os.makedirs(os.path.dirname(manifest_fullpath), exist_ok=True)
        with open(manifest_fullpath, 'w') as manifest:
            if any(target.link_targets):
                manifest.write('Class-Path: ')
                cp_paths = [os.path.join(self.get_target_dir(l), l.get_filename()) for l in target.link_targets]
                manifest.write(' '.join(cp_paths))
            manifest.write('\n')
        jar_rule = 'java_LINKER'
        commands = [c + m + e + f]
        commands.append(manifest_path)
        if e != '':
            commands.append(main_class)
        commands.append(self.get_target_filename(target))
        # Java compilation can produce an arbitrary number of output
        # class files for a single source file. Thus tell jar to just
        # grab everything in the final package.
        commands += ['-C', self.get_target_private_dir(target), '.']
        elem = NinjaBuildElement(self.all_outputs, outname_rel, jar_rule, [])
        elem.add_dep(class_dep_list)
        elem.add_item('ARGS', commands)
        elem.write(outfile)

    def generate_cs_resource_tasks(self, target, outfile):
        args = []
        deps = []
        for r in target.resources:
            rel_sourcefile = os.path.join(self.build_to_src, target.subdir, r)
            if r.endswith('.resources'):
                a = '-resource:' + rel_sourcefile
            elif r.endswith('.txt') or r.endswith('.resx'):
                ofilebase = os.path.splitext(os.path.basename(r))[0] + '.resources'
                ofilename = os.path.join(self.get_target_private_dir(target), ofilebase)
                elem = NinjaBuildElement(self.all_outputs, ofilename, "CUSTOM_COMMAND", rel_sourcefile)
                elem.add_item('COMMAND', ['resgen', rel_sourcefile, ofilename])
                elem.add_item('DESC', 'Compiling resource %s.' % rel_sourcefile)
                elem.write(outfile)
                deps.append(ofilename)
                a = '-resource:' + ofilename
            else:
                raise InvalidArguments('Unknown resource file %s.' % r)
            args.append(a)
        return args, deps

    def generate_cs_target(self, target, outfile):
        buildtype = self.get_option_for_target('buildtype', target)
        fname = target.get_filename()
        outname_rel = os.path.join(self.get_target_dir(target), fname)
        src_list = target.get_sources()
        compiler = target.compilers['cs']
        rel_srcs = [os.path.normpath(s.rel_to_builddir(self.build_to_src)) for s in src_list]
        deps = []
        commands = CompilerArgs(compiler, target.extra_args.get('cs', []))
        commands += compiler.get_buildtype_args(buildtype)
        commands += compiler.get_optimization_args(self.get_option_for_target('optimization', target))
        commands += compiler.get_debug_args(self.get_option_for_target('debug', target))
        if isinstance(target, build.Executable):
            commands.append('-target:exe')
        elif isinstance(target, build.SharedLibrary):
            commands.append('-target:library')
        else:
            raise MesonException('Unknown C# target type.')
        (resource_args, resource_deps) = self.generate_cs_resource_tasks(target, outfile)
        commands += resource_args
        deps += resource_deps
        commands += compiler.get_output_args(outname_rel)
        for l in target.link_targets:
            lname = os.path.join(self.get_target_dir(l), l.get_filename())
            commands += compiler.get_link_args(lname)
            deps.append(lname)
        if '-g' in commands:
            outputs = [outname_rel, outname_rel + '.mdb']
        else:
            outputs = [outname_rel]
        generated_sources = self.get_target_generated_sources(target)
        for rel_src in generated_sources.keys():
            dirpart, fnamepart = os.path.split(rel_src)
            if rel_src.lower().endswith('.cs'):
                rel_srcs.append(os.path.normpath(rel_src))
            deps.append(os.path.normpath(rel_src))

        for dep in target.get_external_deps():
            commands.extend_direct(dep.get_link_args())
        commands += self.build.get_project_args(compiler, target.subproject, target.is_cross)
        commands += self.build.get_global_args(compiler, target.is_cross)

        elem = NinjaBuildElement(self.all_outputs, outputs, 'cs_COMPILER', rel_srcs)
        elem.add_dep(deps)
        elem.add_item('ARGS', commands)
        elem.write(outfile)

        self.generate_generator_list_rules(target, outfile)

    def generate_single_java_compile(self, src, target, compiler, outfile):
        deps = [os.path.join(self.get_target_dir(l), l.get_filename()) for l in target.link_targets]
        args = []
        args += compiler.get_buildtype_args(self.get_option_for_target('buildtype', target))
        args += self.build.get_global_args(compiler, target.is_cross)
        args += self.build.get_project_args(compiler, target.subproject, target.is_cross)
        args += target.get_java_args()
        args += compiler.get_output_args(self.get_target_private_dir(target))
        args += target.get_classpath_args()
        curdir = target.get_subdir()
        sourcepath = os.path.join(self.build_to_src, curdir) + os.pathsep
        sourcepath += os.path.normpath(curdir) + os.pathsep
        for i in target.include_dirs:
            for idir in i.get_incdirs():
                sourcepath += os.path.join(self.build_to_src, i.curdir, idir) + os.pathsep
        args += ['-sourcepath', sourcepath]
        rel_src = src.rel_to_builddir(self.build_to_src)
        plain_class_path = src.fname[:-4] + 'class'
        rel_obj = os.path.join(self.get_target_private_dir(target), plain_class_path)
        element = NinjaBuildElement(self.all_outputs, rel_obj, compiler.get_language() + '_COMPILER', rel_src)
        element.add_dep(deps)
        element.add_item('ARGS', args)
        element.write(outfile)
        return plain_class_path

    def generate_java_link(self, outfile):
        rule = 'rule java_LINKER\n'
        command = ' command = jar $ARGS\n'
        description = ' description = Creating JAR $out.\n'
        outfile.write(rule)
        outfile.write(command)
        outfile.write(description)
        outfile.write('\n')

    def determine_dep_vapis(self, target):
        """
        Peek into the sources of BuildTargets we're linking with, and if any of
        them was built with Vala, assume that it also generated a .vapi file of
        the same name as the BuildTarget and return the path to it relative to
        the build directory.
        """
        result = OrderedSet()
        for dep in itertools.chain(target.link_targets, target.link_whole_targets):
            if not dep.is_linkable_target():
                continue
            for i in dep.sources:
                if hasattr(i, 'fname'):
                    i = i.fname
                if i.endswith('vala'):
                    vapiname = dep.vala_vapi
                    fullname = os.path.join(self.get_target_dir(dep), vapiname)
                    result.add(fullname)
                    break
        return list(result)

    def split_vala_sources(self, t):
        """
        Splits the target's sources into .vala, .gs, .vapi, and other sources.
        Handles both pre-existing and generated sources.

        Returns a tuple (vala, vapi, others) each of which is a dictionary with
        the keys being the path to the file (relative to the build directory)
        and the value being the object that generated or represents the file.
        """
        vala = OrderedDict()
        vapi = OrderedDict()
        others = OrderedDict()
        othersgen = OrderedDict()
        # Split pre-existing sources
        for s in t.get_sources():
            # BuildTarget sources are always mesonlib.File files which are
            # either in the source root, or generated with configure_file and
            # in the build root
            if not isinstance(s, File):
                msg = 'All sources in target {!r} must be of type ' \
                      'mesonlib.File, not {!r}'.format(t, s)
                raise InvalidArguments(msg)
            f = s.rel_to_builddir(self.build_to_src)
            if s.endswith(('.vala', '.gs')):
                srctype = vala
            elif s.endswith('.vapi'):
                srctype = vapi
            else:
                srctype = others
            srctype[f] = s
        # Split generated sources
        for gensrc in t.get_generated_sources():
            for s in gensrc.get_outputs():
                f = self.get_target_generated_dir(t, gensrc, s)
                if s.endswith(('.vala', '.gs')):
                    srctype = vala
                elif s.endswith('.vapi'):
                    srctype = vapi
                # Generated non-Vala (C/C++) sources. Won't be used for
                # generating the Vala compile rule below.
                else:
                    srctype = othersgen
                # Duplicate outputs are disastrous
                if f in srctype and srctype[f] is not gensrc:
                    msg = 'Duplicate output {0!r} from {1!r} {2!r}; ' \
                          'conflicts with {0!r} from {4!r} {3!r}' \
                          ''.format(f, type(gensrc).__name__, gensrc.name,
                                    srctype[f].name, type(srctype[f]).__name__)
                    raise InvalidArguments(msg)
                # Store 'somefile.vala': GeneratedList (or CustomTarget)
                srctype[f] = gensrc
        return vala, vapi, (others, othersgen)

    def generate_vala_compile(self, target, outfile):
        """Vala is compiled into C. Set up all necessary build steps here."""
        (vala_src, vapi_src, other_src) = self.split_vala_sources(target)
        extra_dep_files = []
        if not vala_src:
            msg = 'Vala library {!r} has no Vala or Genie source files.'
            raise InvalidArguments(msg.format(target.name))

        valac = target.compilers['vala']
        c_out_dir = self.get_target_private_dir(target)
        # C files generated by valac
        vala_c_src = []
        # Files generated by valac
        valac_outputs = []
        # All sources that are passed to valac on the commandline
        all_files = list(vapi_src.keys())
        # Passed as --basedir
        srcbasedir = os.path.join(self.build_to_src, target.get_subdir())
        for (vala_file, gensrc) in vala_src.items():
            all_files.append(vala_file)
            # Figure out where the Vala compiler will write the compiled C file
            #
            # If the Vala file is in a subdir of the build dir (in our case
            # because it was generated/built by something else), and is also
            # a subdir of --basedir (because the builddir is in the source
            # tree, and the target subdir is the source root), the subdir
            # components from the source root till the private builddir will be
            # duplicated inside the private builddir. Otherwise, just the
            # basename will be used.
            #
            # If the Vala file is outside the build directory, the paths from
            # the --basedir till the subdir will be duplicated inside the
            # private builddir.
            if isinstance(gensrc, (build.CustomTarget, build.GeneratedList)) or gensrc.is_built:
                vala_c_file = os.path.splitext(os.path.basename(vala_file))[0] + '.c'
                # Check if the vala file is in a subdir of --basedir
                abs_srcbasedir = os.path.join(self.environment.get_source_dir(), target.get_subdir())
                abs_vala_file = os.path.join(self.environment.get_build_dir(), vala_file)
                if PurePath(os.path.commonpath((abs_srcbasedir, abs_vala_file))) == PurePath(abs_srcbasedir):
                    vala_c_subdir = PurePath(abs_vala_file).parent.relative_to(abs_srcbasedir)
                    vala_c_file = os.path.join(str(vala_c_subdir), vala_c_file)
            else:
                path_to_target = os.path.join(self.build_to_src, target.get_subdir())
                if vala_file.startswith(path_to_target):
                    vala_c_file = os.path.splitext(os.path.relpath(vala_file, path_to_target))[0] + '.c'
                else:
                    vala_c_file = os.path.splitext(os.path.basename(vala_file))[0] + '.c'
            # All this will be placed inside the c_out_dir
            vala_c_file = os.path.join(c_out_dir, vala_c_file)
            vala_c_src.append(vala_c_file)
            valac_outputs.append(vala_c_file)

        args = self.generate_basic_compiler_args(target, valac)
        args += valac.get_colorout_args(self.environment.coredata.base_options.get('b_colorout').value)
        # Tell Valac to output everything in our private directory. Sadly this
        # means it will also preserve the directory components of Vala sources
        # found inside the build tree (generated sources).
        args += ['--directory', c_out_dir]
        args += ['--basedir', srcbasedir]
        if target.is_linkable_target():
            # Library name
            args += ['--library', target.name]
            # Outputted header
            hname = os.path.join(self.get_target_dir(target), target.vala_header)
            args += ['--header', hname]
            if self.is_unity(target):
                # Without this the declarations will get duplicated in the .c
                # files and cause a build failure when all of them are
                # #include-d in one .c file.
                # https://github.com/mesonbuild/meson/issues/1969
                args += ['--use-header']
            valac_outputs.append(hname)
            # Outputted vapi file
            vapiname = os.path.join(self.get_target_dir(target), target.vala_vapi)
            # Force valac to write the vapi and gir files in the target build dir.
            # Without this, it will write it inside c_out_dir
            args += ['--vapi', os.path.join('..', target.vala_vapi)]
            valac_outputs.append(vapiname)
            target.outputs += [target.vala_header, target.vala_vapi]
            # Install header and vapi to default locations if user requests this
            if len(target.install_dir) > 1 and target.install_dir[1] is True:
                target.install_dir[1] = self.environment.get_includedir()
            if len(target.install_dir) > 2 and target.install_dir[2] is True:
                target.install_dir[2] = os.path.join(self.environment.get_datadir(), 'vala', 'vapi')
            # Generate GIR if requested
            if isinstance(target.vala_gir, str):
                girname = os.path.join(self.get_target_dir(target), target.vala_gir)
                args += ['--gir', os.path.join('..', target.vala_gir)]
                valac_outputs.append(girname)
                target.outputs.append(target.vala_gir)
                # Install GIR to default location if requested by user
                if len(target.install_dir) > 3 and target.install_dir[3] is True:
                    target.install_dir[3] = os.path.join(self.environment.get_datadir(), 'gir-1.0')
        # Detect gresources and add --gresources arguments for each
        for (gres, gensrc) in other_src[1].items():
            if isinstance(gensrc, modules.GResourceTarget):
                gres_xml, = self.get_custom_target_sources(gensrc)
                args += ['--gresources=' + gres_xml]
        extra_args = []

        for a in target.extra_args.get('vala', []):
            if isinstance(a, File):
                relname = a.rel_to_builddir(self.build_to_src)
                extra_dep_files.append(relname)
                extra_args.append(relname)
            else:
                extra_args.append(a)
        dependency_vapis = self.determine_dep_vapis(target)
        extra_dep_files += dependency_vapis
        args += extra_args
        element = NinjaBuildElement(self.all_outputs, valac_outputs,
                                    valac.get_language() + '_COMPILER',
                                    all_files + dependency_vapis)
        element.add_item('ARGS', args)
        element.add_dep(extra_dep_files)
        element.write(outfile)
        return other_src[0], other_src[1], vala_c_src

    def generate_rust_target(self, target, outfile):
        rustc = target.compilers['rust']
        # Rust compiler takes only the main file as input and
        # figures out what other files are needed via import
        # statements and magic.
        main_rust_file = None
        for i in target.get_sources():
            if not rustc.can_compile(i):
                raise InvalidArguments('Rust target %s contains a non-rust source file.' % target.get_basename())
            if main_rust_file is None:
                main_rust_file = i.rel_to_builddir(self.build_to_src)
        if main_rust_file is None:
            raise RuntimeError('A Rust target has no Rust sources. This is weird. Also a bug. Please report')
        target_name = os.path.join(target.subdir, target.get_filename())
        args = ['--crate-type']
        if isinstance(target, build.Executable):
            cratetype = 'bin'
        elif hasattr(target, 'rust_crate_type'):
            cratetype = target.rust_crate_type
        elif isinstance(target, build.SharedLibrary):
            cratetype = 'dylib'
        elif isinstance(target, build.StaticLibrary):
            cratetype = 'rlib'
        else:
            raise InvalidArguments('Unknown target type for rustc.')
        args.append(cratetype)
        args += ['--crate-name', target.name]
        args += rustc.get_buildtype_args(self.get_option_for_target('buildtype', target))
        args += rustc.get_debug_args(self.get_option_for_target('debug', target))
        depfile = os.path.join(target.subdir, target.name + '.d')
        args += ['--emit', 'dep-info={}'.format(depfile), '--emit', 'link']
        args += target.get_extra_args('rust')
        args += ['-o', os.path.join(target.subdir, target.get_filename())]
        orderdeps = [os.path.join(t.subdir, t.get_filename()) for t in target.link_targets]
        linkdirs = OrderedDict()
        for d in target.link_targets:
            linkdirs[d.subdir] = True
            # specify `extern CRATE_NAME=OUTPUT_FILE` for each Rust
            # dependency, so that collisions with libraries in rustc's
            # sysroot don't cause ambiguity
            args += ['--extern', '{}={}'.format(d.name, os.path.join(d.subdir, d.filename))]
        for d in linkdirs.keys():
            if d == '':
                d = '.'
            args += ['-L', d]
        has_shared_deps = False
        for dep in target.get_dependencies():
            if isinstance(dep, build.SharedLibrary):
                has_shared_deps = True
        if isinstance(target, build.SharedLibrary) or has_shared_deps:
            # add prefer-dynamic if any of the Rust libraries we link
            # against are dynamic, otherwise we'll end up with
            # multiple implementations of crates
            args += ['-C', 'prefer-dynamic']

            # build the usual rpath arguments as well...

            # Set runtime-paths so we can run executables without needing to set
            # LD_LIBRARY_PATH, etc in the environment. Doesn't work on Windows.
            if has_path_sep(target.name):
                # Target names really should not have slashes in them, but
                # unfortunately we did not check for that and some downstream projects
                # now have them. Once slashes are forbidden, remove this bit.
                target_slashname_workaround_dir = os.path.join(os.path.dirname(target.name),
                                                               self.get_target_dir(target))
            else:
                target_slashname_workaround_dir = self.get_target_dir(target)
            rpath_args = rustc.build_rpath_args(self.environment.get_build_dir(),
                                                target_slashname_workaround_dir,
                                                self.determine_rpath_dirs(target),
                                                target.build_rpath,
                                                target.install_rpath)
            # ... but then add rustc's sysroot to account for rustup
            # installations
            for rpath_arg in rpath_args:
                args += ['-C', 'link-arg=' + rpath_arg + ':' + os.path.join(rustc.get_sysroot(), 'lib')]
        crstr = ''
        if target.is_cross:
            crstr = '_CROSS'
        compiler_name = 'rust%s_COMPILER' % crstr
        element = NinjaBuildElement(self.all_outputs, target_name, compiler_name, main_rust_file)
        if len(orderdeps) > 0:
            element.add_orderdep(orderdeps)
        element.add_item('ARGS', args)
        element.add_item('targetdep', depfile)
        element.add_item('cratetype', cratetype)
        element.write(outfile)
        if isinstance(target, build.SharedLibrary):
            self.generate_shsym(outfile, target)

    def swift_module_file_name(self, target):
        return os.path.join(self.get_target_private_dir(target),
                            self.target_swift_modulename(target) + '.swiftmodule')

    def target_swift_modulename(self, target):
        return target.name

    def is_swift_target(self, target):
        for s in target.sources:
            if s.endswith('swift'):
                return True
        return False

    def determine_swift_dep_modules(self, target):
        result = []
        for l in target.link_targets:
            if self.is_swift_target(l):
                result.append(self.swift_module_file_name(l))
        return result

    def determine_swift_dep_dirs(self, target):
        result = []
        for l in target.link_targets:
            result.append(self.get_target_private_dir_abs(l))
        return result

    def get_swift_link_deps(self, target):
        result = []
        for l in target.link_targets:
            result.append(self.get_target_filename(l))
        return result

    def split_swift_generated_sources(self, target):
        all_srcs = self.get_target_generated_sources(target)
        srcs = []
        others = []
        for i in all_srcs:
            if i.endswith('.swift'):
                srcs.append(i)
            else:
                others.append(i)
        return srcs, others

    def generate_swift_target(self, target, outfile):
        module_name = self.target_swift_modulename(target)
        swiftc = target.compilers['swift']
        abssrc = []
        abs_headers = []
        header_imports = []
        for i in target.get_sources():
            if swiftc.can_compile(i):
                relsrc = i.rel_to_builddir(self.build_to_src)
                abss = os.path.normpath(os.path.join(self.environment.get_build_dir(), relsrc))
                abssrc.append(abss)
            elif self.environment.is_header(i):
                relh = i.rel_to_builddir(self.build_to_src)
                absh = os.path.normpath(os.path.join(self.environment.get_build_dir(), relh))
                abs_headers.append(absh)
                header_imports += swiftc.get_header_import_args(absh)
            else:
                raise InvalidArguments('Swift target %s contains a non-swift source file.' % target.get_basename())
        os.makedirs(self.get_target_private_dir_abs(target), exist_ok=True)
        compile_args = swiftc.get_compile_only_args()
        compile_args += swiftc.get_optimization_args(self.get_option_for_target('optimization', target))
        compile_args += swiftc.get_debug_args(self.get_option_for_target('debug', target))
        compile_args += swiftc.get_module_args(module_name)
        compile_args += self.build.get_project_args(swiftc, target.subproject, target.is_cross)
        compile_args += self.build.get_global_args(swiftc, target.is_cross)
        for i in reversed(target.get_include_dirs()):
            basedir = i.get_curdir()
            for d in i.get_incdirs():
                if d not in ('', '.'):
                    expdir = os.path.join(basedir, d)
                else:
                    expdir = basedir
                srctreedir = os.path.normpath(os.path.join(self.environment.get_build_dir(), self.build_to_src, expdir))
                sargs = swiftc.get_include_args(srctreedir)
                compile_args += sargs
        link_args = swiftc.get_output_args(os.path.join(self.environment.get_build_dir(), self.get_target_filename(target)))
        link_args += self.build.get_project_link_args(swiftc, target.subproject, target.is_cross)
        link_args += self.build.get_global_link_args(swiftc, target.is_cross)
        rundir = self.get_target_private_dir(target)
        out_module_name = self.swift_module_file_name(target)
        in_module_files = self.determine_swift_dep_modules(target)
        abs_module_dirs = self.determine_swift_dep_dirs(target)
        module_includes = []
        for x in abs_module_dirs:
            module_includes += swiftc.get_include_args(x)
        link_deps = self.get_swift_link_deps(target)
        abs_link_deps = [os.path.join(self.environment.get_build_dir(), x) for x in link_deps]
        for d in target.link_targets:
            reldir = self.get_target_dir(d)
            if reldir == '':
                reldir = '.'
            link_args += ['-L', os.path.normpath(os.path.join(self.environment.get_build_dir(), reldir))]
        (rel_generated, _) = self.split_swift_generated_sources(target)
        abs_generated = [os.path.join(self.environment.get_build_dir(), x) for x in rel_generated]
        # We need absolute paths because swiftc needs to be invoked in a subdir
        # and this is the easiest way about it.
        objects = [] # Relative to swift invocation dir
        rel_objects = [] # Relative to build.ninja
        for i in abssrc + abs_generated:
            base = os.path.basename(i)
            oname = os.path.splitext(base)[0] + '.o'
            objects.append(oname)
            rel_objects.append(os.path.join(self.get_target_private_dir(target), oname))

        # Swiftc does not seem to be able to emit objects and module files in one go.
        elem = NinjaBuildElement(self.all_outputs, rel_objects,
                                 'swift_COMPILER',
                                 abssrc)
        elem.add_dep(in_module_files + rel_generated)
        elem.add_dep(abs_headers)
        elem.add_item('ARGS', compile_args + header_imports + abs_generated + module_includes)
        elem.add_item('RUNDIR', rundir)
        elem.write(outfile)
        elem = NinjaBuildElement(self.all_outputs, out_module_name,
                                 'swift_COMPILER',
                                 abssrc)
        elem.add_dep(in_module_files + rel_generated)
        elem.add_item('ARGS', compile_args + abs_generated + module_includes + swiftc.get_mod_gen_args())
        elem.add_item('RUNDIR', rundir)
        elem.write(outfile)
        if isinstance(target, build.StaticLibrary):
            elem = self.generate_link(target, outfile, self.get_target_filename(target),
                                      rel_objects, self.build.static_linker)
            elem.write(outfile)
        elif isinstance(target, build.Executable):
            elem = NinjaBuildElement(self.all_outputs, self.get_target_filename(target), 'swift_COMPILER', [])
            elem.add_dep(rel_objects)
            elem.add_dep(link_deps)
            elem.add_item('ARGS', link_args + swiftc.get_std_exe_link_args() + objects + abs_link_deps)
            elem.add_item('RUNDIR', rundir)
            elem.write(outfile)
        else:
            raise MesonException('Swift supports only executable and static library targets.')

    def generate_static_link_rules(self, is_cross, outfile):
        num_pools = self.environment.coredata.backend_options['backend_max_links'].value
        if 'java' in self.build.compilers:
            if not is_cross:
                self.generate_java_link(outfile)
        if is_cross:
            if self.environment.cross_info.need_cross_compiler():
                static_linker = self.build.static_cross_linker
            else:
                static_linker = self.build.static_linker
            crstr = '_CROSS'
        else:
            static_linker = self.build.static_linker
            crstr = ''
        if static_linker is None:
            return
        rule = 'rule STATIC%s_LINKER\n' % crstr
        if static_linker.can_linker_accept_rsp():
            command_template = ''' command = {executable} $LINK_ARGS {output_args} @$out.rsp
 rspfile = $out.rsp
 rspfile_content = $in
'''
        else:
            command_template = ' command = {executable} $LINK_ARGS {output_args} $in\n'
        cmdlist = []
        # FIXME: Must normalize file names with pathlib.Path before writing
        #        them out to fix this properly on Windows. See:
        # https://github.com/mesonbuild/meson/issues/1517
        # https://github.com/mesonbuild/meson/issues/1526
        if isinstance(static_linker, ArLinker) and not mesonlib.is_windows():
            # `ar` has no options to overwrite archives. It always appends,
            # which is never what we want. Delete an existing library first if
            # it exists. https://github.com/mesonbuild/meson/issues/1355
            cmdlist = [execute_wrapper, rmfile_prefix.format('$out')]
        cmdlist += static_linker.get_exelist()
        command = command_template.format(
            executable=' '.join(cmdlist),
            output_args=' '.join(static_linker.get_output_args('$out')))
        description = ' description = Linking static target $out.\n\n'
        outfile.write(rule)
        outfile.write(command)
        if num_pools > 0:
            outfile.write(' pool = link_pool\n')
        outfile.write(description)

    def generate_dynamic_link_rules(self, outfile):
        num_pools = self.environment.coredata.backend_options['backend_max_links'].value
        ctypes = [(self.build.compilers, False)]
        if self.environment.is_cross_build():
            if self.environment.cross_info.need_cross_compiler():
                ctypes.append((self.build.cross_compilers, True))
            else:
                # Native compiler masquerades as the cross compiler.
                ctypes.append((self.build.compilers, True))
        else:
            ctypes.append((self.build.cross_compilers, True))
        for (complist, is_cross) in ctypes:
            for langname, compiler in complist.items():
                if langname == 'java' \
                        or langname == 'vala' \
                        or langname == 'rust' \
                        or langname == 'cs':
                    continue
                crstr = ''
                cross_args = []
                if is_cross:
                    crstr = '_CROSS'
                    try:
                        cross_args = self.environment.cross_info.config['properties'][langname + '_link_args']
                    except KeyError:
                        pass
                rule = 'rule %s%s_LINKER\n' % (langname, crstr)
                if compiler.can_linker_accept_rsp():
                    command_template = ''' command = {executable} @$out.rsp
 rspfile = $out.rsp
 rspfile_content = $ARGS  {output_args} $in $LINK_ARGS {cross_args} $aliasing
'''
                else:
                    command_template = ' command = {executable} $ARGS {output_args} $in $LINK_ARGS {cross_args} $aliasing\n'
                command = command_template.format(
                    executable=' '.join(compiler.get_linker_exelist()),
                    cross_args=' '.join(cross_args),
                    output_args=' '.join(compiler.get_linker_output_args('$out'))
                )
                description = ' description = Linking target $out.\n'
                outfile.write(rule)
                outfile.write(command)
                if num_pools > 0:
                    outfile.write(' pool = link_pool\n')
                outfile.write(description)
                outfile.write('\n')
        outfile.write('\n')
        args = [ninja_quote(quote_func(x)) for x in self.environment.get_build_command()] + \
            ['--internal',
             'symbolextractor',
             '$in',
             '$out']
        symrule = 'rule SHSYM\n'
        symcmd = ' command = ' + ' '.join(args) + ' $CROSS\n'
        synstat = ' restat = 1\n'
        syndesc = ' description = Generating symbol file $out.\n'
        outfile.write(symrule)
        outfile.write(symcmd)
        outfile.write(synstat)
        outfile.write(syndesc)
        outfile.write('\n')

    def generate_java_compile_rule(self, compiler, outfile):
        rule = 'rule %s_COMPILER\n' % compiler.get_language()
        invoc = ' '.join([ninja_quote(i) for i in compiler.get_exelist()])
        command = ' command = %s $ARGS $in\n' % invoc
        description = ' description = Compiling Java object $in.\n'
        outfile.write(rule)
        outfile.write(command)
        outfile.write(description)
        outfile.write('\n')

    def generate_cs_compile_rule(self, compiler, outfile):
        rule = 'rule %s_COMPILER\n' % compiler.get_language()
        invoc = ' '.join([ninja_quote(i) for i in compiler.get_exelist()])

        if mesonlib.is_windows():
            command = ''' command = {executable}  @$out.rsp
 rspfile = $out.rsp
 rspfile_content =  $ARGS  $in
'''.format(executable=invoc)
        else:
            command = ' command = %s $ARGS $in\n' % invoc

        description = ' description = Compiling C Sharp target $out.\n'
        outfile.write(rule)
        outfile.write(command)
        outfile.write(description)
        outfile.write('\n')

    def generate_vala_compile_rules(self, compiler, outfile):
        rule = 'rule %s_COMPILER\n' % compiler.get_language()
        invoc = ' '.join([ninja_quote(i) for i in compiler.get_exelist()])
        command = ' command = %s $ARGS $in\n' % invoc
        description = ' description = Compiling Vala source $in.\n'
        restat = ' restat = 1\n' # ValaC does this always to take advantage of it.
        outfile.write(rule)
        outfile.write(command)
        outfile.write(description)
        outfile.write(restat)
        outfile.write('\n')

    def generate_rust_compile_rules(self, compiler, outfile, is_cross):
        crstr = ''
        if is_cross:
            crstr = '_CROSS'
        rule = 'rule %s%s_COMPILER\n' % (compiler.get_language(), crstr)
        invoc = ' '.join([ninja_quote(i) for i in compiler.get_exelist()])
        command = ' command = %s $ARGS $in\n' % invoc
        description = ' description = Compiling Rust source $in.\n'
        depfile = ' depfile = $targetdep\n'

        depstyle = ' deps = gcc\n'
        outfile.write(rule)
        outfile.write(command)
        outfile.write(description)
        outfile.write(depfile)
        outfile.write(depstyle)
        outfile.write('\n')

    def generate_swift_compile_rules(self, compiler, outfile):
        rule = 'rule %s_COMPILER\n' % compiler.get_language()
        full_exe = [ninja_quote(x) for x in self.environment.get_build_command()] + [
            '--internal',
            'dirchanger',
            '$RUNDIR',
        ]
        invoc = (' '.join(full_exe) + ' ' +
                 ' '.join(ninja_quote(i) for i in compiler.get_exelist()))
        command = ' command = %s $ARGS $in\n' % invoc
        description = ' description = Compiling Swift source $in.\n'
        outfile.write(rule)
        outfile.write(command)
        outfile.write(description)
        outfile.write('\n')

    def generate_fortran_dep_hack(self, outfile, crstr):
        if mesonlib.is_windows():
            cmd = 'cmd /C ""'
        else:
            cmd = 'true'
        template = '''# Workaround for these issues:
# https://groups.google.com/forum/#!topic/ninja-build/j-2RfBIOd_8
# https://gcc.gnu.org/bugzilla/show_bug.cgi?id=47485
rule FORTRAN_DEP_HACK%s
 command = %s
 description = Dep hack
 restat = 1

'''
        outfile.write(template % (crstr, cmd))

    def generate_llvm_ir_compile_rule(self, compiler, is_cross, outfile):
        if getattr(self, 'created_llvm_ir_rule', False):
            return
        rule = 'rule llvm_ir{}_COMPILER\n'.format('_CROSS' if is_cross else '')
        if compiler.can_linker_accept_rsp():
            command_template = ' command = {executable} @$out.rsp\n' \
                               ' rspfile = $out.rsp\n' \
                               ' rspfile_content =  $ARGS {cross_args} {output_args} {compile_only_args} $in\n'
        else:
            command_template = ' command = {executable} $ARGS {cross_args} {output_args} {compile_only_args} $in\n'
        command = command_template.format(
            executable=' '.join([ninja_quote(i) for i in compiler.get_exelist()]),
            cross_args=' '.join(self.get_cross_info_lang_args(compiler.language, is_cross)),
            output_args=' '.join(compiler.get_output_args('$out')),
            compile_only_args=' '.join(compiler.get_compile_only_args())
        )
        description = ' description = Compiling LLVM IR object $in.\n'
        outfile.write(rule)
        outfile.write(command)
        outfile.write(description)
        outfile.write('\n')
        self.created_llvm_ir_rule = True

    def get_cross_info_lang_args(self, lang, is_cross):
        if is_cross:
            try:
                return self.environment.cross_info.config['properties'][lang + '_args']
            except KeyError:
                pass
        return []

    def generate_compile_rule_for(self, langname, compiler, is_cross, outfile):
        if langname == 'java':
            if not is_cross:
                self.generate_java_compile_rule(compiler, outfile)
            return
        if langname == 'cs':
            if not is_cross:
                self.generate_cs_compile_rule(compiler, outfile)
            return
        if langname == 'vala':
            if not is_cross:
                self.generate_vala_compile_rules(compiler, outfile)
            return
        if langname == 'rust':
            self.generate_rust_compile_rules(compiler, outfile, is_cross)
            return
        if langname == 'swift':
            if not is_cross:
                self.generate_swift_compile_rules(compiler, outfile)
            return
        if is_cross:
            crstr = '_CROSS'
        else:
            crstr = ''
        if langname == 'fortran':
            self.generate_fortran_dep_hack(outfile, crstr)
        rule = 'rule %s%s_COMPILER\n' % (langname, crstr)
        depargs = compiler.get_dependency_gen_args('$out', '$DEPFILE')
        quoted_depargs = []
        for d in depargs:
            if d != '$out' and d != '$in':
                d = quote_func(d)
            quoted_depargs.append(d)
        cross_args = self.get_cross_info_lang_args(langname, is_cross)
        if compiler.can_linker_accept_rsp():
            command_template = ''' command = {executable} @$out.rsp
 rspfile = $out.rsp
 rspfile_content = $ARGS {cross_args} {dep_args} {output_args} {compile_only_args} $in
'''
        else:
            command_template = ' command = {executable} $ARGS {cross_args} {dep_args} {output_args} {compile_only_args} $in\n'
        command = command_template.format(
            executable=' '.join([ninja_quote(i) for i in compiler.get_exelist()]),
            cross_args=' '.join(cross_args),
            dep_args=' '.join(quoted_depargs),
            output_args=' '.join(compiler.get_output_args('$out')),
            compile_only_args=' '.join(compiler.get_compile_only_args())
        )
        description = ' description = Compiling %s object $out.\n' % compiler.get_display_language()
        if compiler.get_id() == 'msvc':
            deps = ' deps = msvc\n'
        else:
            deps = ' deps = gcc\n'
            deps += ' depfile = $DEPFILE\n'
        outfile.write(rule)
        outfile.write(command)
        outfile.write(deps)
        outfile.write(description)
        outfile.write('\n')

    def generate_pch_rule_for(self, langname, compiler, is_cross, outfile):
        if langname != 'c' and langname != 'cpp':
            return
        if is_cross:
            crstr = '_CROSS'
        else:
            crstr = ''
        rule = 'rule %s%s_PCH\n' % (langname, crstr)
        depargs = compiler.get_dependency_gen_args('$out', '$DEPFILE')
        cross_args = []
        if is_cross:
            try:
                cross_args = self.environment.cross_info.config['properties'][langname + '_args']
            except KeyError:
                pass

        quoted_depargs = []
        for d in depargs:
            if d != '$out' and d != '$in':
                d = quote_func(d)
            quoted_depargs.append(d)
        if compiler.get_id() == 'msvc':
            output = ''
        else:
            output = ' '.join(compiler.get_output_args('$out'))
        command = " command = {executable} $ARGS {cross_args} {dep_args} {output_args} {compile_only_args} $in\n".format(
            executable=' '.join(compiler.get_exelist()),
            cross_args=' '.join(cross_args),
            dep_args=' '.join(quoted_depargs),
            output_args=output,
            compile_only_args=' '.join(compiler.get_compile_only_args())
        )
        description = ' description = Precompiling header %s.\n' % '$in'
        if compiler.get_id() == 'msvc':
            deps = ' deps = msvc\n'
        else:
            deps = ' deps = gcc\n'
            deps += ' depfile = $DEPFILE\n'
        outfile.write(rule)
        outfile.write(command)
        outfile.write(deps)
        outfile.write(description)
        outfile.write('\n')

    def generate_compile_rules(self, outfile):
        for langname, compiler in self.build.compilers.items():
            if compiler.get_id() == 'clang':
                self.generate_llvm_ir_compile_rule(compiler, False, outfile)
            self.generate_compile_rule_for(langname, compiler, False, outfile)
            self.generate_pch_rule_for(langname, compiler, False, outfile)
        if self.environment.is_cross_build():
            # In case we are going a target-only build, make the native compilers
            # masquerade as cross compilers.
            if self.environment.cross_info.need_cross_compiler():
                cclist = self.build.cross_compilers
            else:
                cclist = self.build.compilers
            for langname, compiler in cclist.items():
                if compiler.get_id() == 'clang':
                    self.generate_llvm_ir_compile_rule(compiler, True, outfile)
                self.generate_compile_rule_for(langname, compiler, True, outfile)
                self.generate_pch_rule_for(langname, compiler, True, outfile)
        outfile.write('\n')

    def generate_generator_list_rules(self, target, outfile):
        # CustomTargets have already written their rules and
        # CustomTargetIndexes don't actually get generated, so write rules for
        # GeneratedLists here
        for genlist in target.get_generated_sources():
            if isinstance(genlist, (build.CustomTarget, build.CustomTargetIndex)):
                continue
            self.generate_genlist_for_target(genlist, target, outfile)

    def replace_paths(self, target, args, override_subdir=None):
        if override_subdir:
            source_target_dir = os.path.join(self.build_to_src, override_subdir)
        else:
            source_target_dir = self.get_target_source_dir(target)
        relout = self.get_target_private_dir(target)
        args = [x.replace("@SOURCE_DIR@", self.build_to_src).replace("@BUILD_DIR@", relout)
                for x in args]
        args = [x.replace("@CURRENT_SOURCE_DIR@", source_target_dir) for x in args]
        args = [x.replace("@SOURCE_ROOT@", self.build_to_src).replace("@BUILD_ROOT@", '.')
                for x in args]
        args = [x.replace('\\', '/') for x in args]
        return args

    def generate_genlist_for_target(self, genlist, target, outfile):
        generator = genlist.get_generator()
        subdir = genlist.subdir
        exe = generator.get_exe()
        exe_arr = self.exe_object_to_cmd_array(exe)
        infilelist = genlist.get_inputs()
        outfilelist = genlist.get_outputs()
        extra_dependencies = [os.path.join(self.build_to_src, i) for i in genlist.extra_depends]
        for i in range(len(infilelist)):
            if len(generator.outputs) == 1:
                sole_output = os.path.join(self.get_target_private_dir(target), outfilelist[i])
            else:
                sole_output = ''
            curfile = infilelist[i]
            infilename = curfile.rel_to_builddir(self.build_to_src)
            base_args = generator.get_arglist(infilename)
            outfiles = genlist.get_outputs_for(curfile)
            outfiles = [os.path.join(self.get_target_private_dir(target), of) for of in outfiles]
            if generator.depfile is None:
                rulename = 'CUSTOM_COMMAND'
                args = base_args
            else:
                rulename = 'CUSTOM_COMMAND_DEP'
                depfilename = generator.get_dep_outname(infilename)
                depfile = os.path.join(self.get_target_private_dir(target), depfilename)
                args = [x.replace('@DEPFILE@', depfile) for x in base_args]
            args = [x.replace("@INPUT@", infilename).replace('@OUTPUT@', sole_output)
                    for x in args]
            args = self.replace_outputs(args, self.get_target_private_dir(target), outfilelist)
            # We have consumed output files, so drop them from the list of remaining outputs.
            if sole_output == '':
                outfilelist = outfilelist[len(generator.outputs):]
            args = self.replace_paths(target, args, override_subdir=subdir)
            cmdlist = exe_arr + self.replace_extra_args(args, genlist)
            if generator.capture:
                exe_data = self.serialize_executable(
                    'generator ' + cmdlist[0],
                    cmdlist[0],
                    cmdlist[1:],
                    self.environment.get_build_dir(),
                    capture=outfiles[0]
                )
                cmd = self.environment.get_build_command() + ['--internal', 'exe', exe_data]
                abs_pdir = os.path.join(self.environment.get_build_dir(), self.get_target_dir(target))
                os.makedirs(abs_pdir, exist_ok=True)
            else:
                cmd = cmdlist

            elem = NinjaBuildElement(self.all_outputs, outfiles, rulename, infilename)
            if generator.depfile is not None:
                elem.add_item('DEPFILE', depfile)
            if len(extra_dependencies) > 0:
                elem.add_dep(extra_dependencies)
            elem.add_item('DESC', 'Generating {!r}.'.format(sole_output))
            if isinstance(exe, build.BuildTarget):
                elem.add_dep(self.get_target_filename(exe))
            elem.add_item('COMMAND', cmd)
            elem.write(outfile)

    def scan_fortran_module_outputs(self, target):
        compiler = None
        for lang, c in self.build.compilers.items():
            if lang == 'fortran':
                compiler = c
                break
        if compiler is None:
            self.fortran_deps[target.get_basename()] = {}
            return
        modre = re.compile(r"\s*module\s+(\w+)", re.IGNORECASE)
        module_files = {}
        for s in target.get_sources():
            # FIXME, does not work for Fortran sources generated by
            # custom_target() and generator() as those are run after
            # the configuration (configure_file() is OK)
            if not compiler.can_compile(s):
                continue
            filename = s.absolute_path(self.environment.get_source_dir(),
                                       self.environment.get_build_dir())
            # Some Fortran editors save in weird encodings,
            # but all the parts we care about are in ASCII.
            with open(filename, errors='ignore') as f:
                for line in f:
                    modmatch = modre.match(line)
                    if modmatch is not None:
                        modname = modmatch.group(1).lower()
                        if modname == 'procedure':
                            # MODULE PROCEDURE construct
                            continue
                        if modname in module_files:
                            raise InvalidArguments(
                                'Namespace collision: module %s defined in '
                                'two files %s and %s.' %
                                (modname, module_files[modname], s))
                        module_files[modname] = s
        self.fortran_deps[target.get_basename()] = module_files

    def get_fortran_deps(self, compiler, src, target):
        mod_files = []
        usere = re.compile(r"\s*use\s+(\w+)", re.IGNORECASE)
        dirname = self.get_target_private_dir(target)
        tdeps = self.fortran_deps[target.get_basename()]
        with open(src) as f:
            for line in f:
                usematch = usere.match(line)
                if usematch is not None:
                    usename = usematch.group(1).lower()
                    if usename not in tdeps:
                        # The module is not provided by any source file. This
                        # is due to:
                        #   a) missing file/typo/etc
                        #   b) using a module provided by the compiler, such as
                        #      OpenMP
                        # There's no easy way to tell which is which (that I
                        # know of) so just ignore this and go on. Ideally we
                        # would print a warning message to the user but this is
                        # a common occurrence, which would lead to lots of
                        # distracting noise.
                        continue
                    mod_source_file = tdeps[usename]
                    # Check if a source uses a module it exports itself.
                    # Potential bug if multiple targets have a file with
                    # the same name.
                    if mod_source_file.fname == os.path.basename(src):
                        continue
                    mod_name = compiler.module_name_to_filename(
                        usematch.group(1))
                    mod_files.append(os.path.join(dirname, mod_name))
        return mod_files

    def get_cross_stdlib_args(self, target, compiler):
        if not target.is_cross:
            return []
        if not self.environment.cross_info.has_stdlib(compiler.language):
            return []
        return compiler.get_no_stdinc_args()

    def get_compile_debugfile_args(self, compiler, target, objfile):
        if compiler.id != 'msvc':
            return []
        # The way MSVC uses PDB files is documented exactly nowhere so
        # the following is what we have been able to decipher via
        # reverse engineering.
        #
        # Each object file gets the path of its PDB file written
        # inside it.  This can be either the final PDB (for, say,
        # foo.exe) or an object pdb (for foo.obj). If the former, then
        # each compilation step locks the pdb file for writing, which
        # is a bottleneck and object files from one target can not be
        # used in a different target. The latter seems to be the
        # sensible one (and what Unix does) but there is a catch.  If
        # you try to use precompiled headers MSVC will error out
        # because both source and pch pdbs go in the same file and
        # they must be the same.
        #
        # This means:
        #
        # - pch files must be compiled anew for every object file (negating
        #   the entire point of having them in the first place)
        # - when using pch, output must go to the target pdb
        #
        # Since both of these are broken in some way, use the one that
        # works for each target. This unfortunately means that you
        # can't combine pch and object extraction in a single target.
        #
        # PDB files also lead to filename collisions. A target foo.exe
        # has a corresponding foo.pdb. A shared library foo.dll _also_
        # has pdb file called foo.pdb. So will a static library
        # foo.lib, which clobbers both foo.pdb _and_ the dll file's
        # export library called foo.lib (by default, currently we name
        # them libfoo.a to avoidt this issue). You can give the files
        # unique names such as foo_exe.pdb but VC also generates a
        # bunch of other files which take their names from the target
        # basename (i.e. "foo") and stomp on each other.
        #
        # CMake solves this problem by doing two things. First of all
        # static libraries do not generate pdb files at
        # all. Presumably you don't need them and VC is smart enough
        # to look up the original data when linking (speculation, not
        # tested). The second solution is that you can only have
        # target named "foo" as an exe, shared lib _or_ static
        # lib. This makes filename collisions not happen. The downside
        # is that you can't have an executable foo that uses a shared
        # library libfoo.so, which is a common idiom on Unix.
        #
        # If you feel that the above is completely wrong and all of
        # this is actually doable, please send patches.

        if target.has_pch():
            tfilename = self.get_target_filename_abs(target)
            return compiler.get_compile_debugfile_args(tfilename, pch=True)
        else:
            return compiler.get_compile_debugfile_args(objfile, pch=False)

    def get_link_debugfile_args(self, linker, target, outname):
        return linker.get_link_debugfile_args(outname)

    def generate_llvm_ir_compile(self, target, outfile, src):
        compiler = get_compiler_for_source(target.compilers.values(), src)
        commands = CompilerArgs(compiler)
        # Compiler args for compiling this target
        commands += compilers.get_base_compile_args(self.environment.coredata.base_options,
                                                    compiler)
        if isinstance(src, File):
            if src.is_built:
                src_filename = os.path.join(src.subdir, src.fname)
            else:
                src_filename = src.fname
        elif os.path.isabs(src):
            src_filename = os.path.basename(src)
        else:
            src_filename = src
        obj_basename = src_filename.replace('/', '_').replace('\\', '_')
        rel_obj = os.path.join(self.get_target_private_dir(target), obj_basename)
        rel_obj += '.' + self.environment.get_object_suffix()
        commands += self.get_compile_debugfile_args(compiler, target, rel_obj)
        if isinstance(src, File) and src.is_built:
            rel_src = src.fname
        elif isinstance(src, File):
            rel_src = src.rel_to_builddir(self.build_to_src)
        else:
            raise InvalidArguments('Invalid source type: {!r}'.format(src))
        # Write the Ninja build command
        compiler_name = 'llvm_ir{}_COMPILER'.format('_CROSS' if target.is_cross else '')
        element = NinjaBuildElement(self.all_outputs, rel_obj, compiler_name, rel_src)
        # Convert from GCC-style link argument naming to the naming used by the
        # current compiler.
        commands = commands.to_native()
        element.add_item('ARGS', commands)
        element.write(outfile)
        return rel_obj

    def get_source_dir_include_args(self, target, compiler):
        curdir = target.get_subdir()
        tmppath = os.path.normpath(os.path.join(self.build_to_src, curdir))
        return compiler.get_include_args(tmppath, False)

    def get_build_dir_include_args(self, target, compiler):
        curdir = target.get_subdir()
        if curdir == '':
            curdir = '.'
        return compiler.get_include_args(curdir, False)

    def get_custom_target_dir_include_args(self, target, compiler):
        custom_target_include_dirs = []
        for i in target.get_generated_sources():
            # Generator output goes into the target private dir which is
            # already in the include paths list. Only custom targets have their
            # own target build dir.
            if not isinstance(i, (build.CustomTarget, build.CustomTargetIndex)):
                continue
            idir = self.get_target_dir(i)
            if not idir:
                idir = '.'
            if idir not in custom_target_include_dirs:
                custom_target_include_dirs.append(idir)
        incs = []
        for i in custom_target_include_dirs:
            incs += compiler.get_include_args(i, False)
        return incs

    @lru_cache(maxsize=None)
    def _generate_single_compile(self, target, compiler, is_generated=False):
        base_proxy = self.get_base_options_for_target(target)
        # Create an empty commands list, and start adding arguments from
        # various sources in the order in which they must override each other
        commands = CompilerArgs(compiler)
        # Start with symbol visibility.
        commands += compiler.gnu_symbol_visibility_args(target.gnu_symbol_visibility)
        # Add compiler args for compiling this target derived from 'base' build
        # options passed on the command-line, in default_options, etc.
        # These have the lowest priority.
        commands += compilers.get_base_compile_args(base_proxy,
                                                    compiler)
        # The code generated by valac is usually crap and has tons of unused
        # variables and such, so disable warnings for Vala C sources.
        no_warn_args = (is_generated == 'vala')
        # Add compiler args and include paths from several sources; defaults,
        # build options, external dependencies, etc.
        commands += self.generate_basic_compiler_args(target, compiler, no_warn_args)
        # Add custom target dirs as includes automatically, but before
        # target-specific include directories.
        # XXX: Not sure if anyone actually uses this? It can cause problems in
        # situations which increase the likelihood for a header name collision,
        # such as in subprojects.
        commands += self.get_custom_target_dir_include_args(target, compiler)
        # Add include dirs from the `include_directories:` kwarg on the target
        # and from `include_directories:` of internal deps of the target.
        #
        # Target include dirs should override internal deps include dirs.
        # This is handled in BuildTarget.process_kwargs()
        #
        # Include dirs from internal deps should override include dirs from
        # external deps and must maintain the order in which they are specified.
        # Hence, we must reverse the list so that the order is preserved.
        for i in reversed(target.get_include_dirs()):
            basedir = i.get_curdir()
            # We should iterate include dirs in reversed orders because
            # -Ipath will add to begin of array. And without reverse
            # flags will be added in reversed order.
            for d in reversed(i.get_incdirs()):
                # Avoid superfluous '/.' at the end of paths when d is '.'
                if d not in ('', '.'):
                    expdir = os.path.join(basedir, d)
                else:
                    expdir = basedir
                srctreedir = os.path.join(self.build_to_src, expdir)
                # Add source subdir first so that the build subdir overrides it
                sargs = compiler.get_include_args(srctreedir, i.is_system)
                commands += sargs
                # There may be include dirs where a build directory has not been
                # created for some source dir. For example if someone does this:
                #
                # inc = include_directories('foo/bar/baz')
                #
                # But never subdir()s into the actual dir.
                if os.path.isdir(os.path.join(self.environment.get_build_dir(), expdir)):
                    bargs = compiler.get_include_args(expdir, i.is_system)
                else:
                    bargs = []
                commands += bargs
            for d in i.get_extra_build_dirs():
                commands += compiler.get_include_args(d, i.is_system)
        # Add per-target compile args, f.ex, `c_args : ['-DFOO']`. We set these
        # near the end since these are supposed to override everything else.
        commands += self.escape_extra_args(compiler,
                                           target.get_extra_args(compiler.get_language()))

        # D specific additional flags
        if compiler.language == 'd':
            commands += compiler.get_feature_args(target.d_features, self.build_to_src)

        # Add source dir and build dir. Project-specific and target-specific
        # include paths must override per-target compile args, include paths
        # from external dependencies, internal dependencies, and from
        # per-target `include_directories:`
        #
        # We prefer headers in the build dir over the source dir since, for
        # instance, the user might have an srcdir == builddir Autotools build
        # in their source tree. Many projects that are moving to Meson have
        # both Meson and Autotools in parallel as part of the transition.
        if target.implicit_include_directories:
            commands += self.get_source_dir_include_args(target, compiler)
        if target.implicit_include_directories:
            commands += self.get_build_dir_include_args(target, compiler)
        # Finally add the private dir for the target to the include path. This
        # must override everything else and must be the final path added.
        commands += compiler.get_include_args(self.get_target_private_dir(target), False)
        return commands

    def generate_single_compile(self, target, outfile, src, is_generated=False, header_deps=[], order_deps=[]):
        """
        Compiles C/C++, ObjC/ObjC++, Fortran, and D sources
        """
        if isinstance(src, str) and src.endswith('.h'):
            raise AssertionError('BUG: sources should not contain headers {!r}'.format(src))

        compiler = get_compiler_for_source(target.compilers.values(), src)
        commands = self._generate_single_compile(target, compiler, is_generated)
        commands = CompilerArgs(commands.compiler, commands)

        build_dir = self.environment.get_build_dir()
        if isinstance(src, File):
            rel_src = src.rel_to_builddir(self.build_to_src)
            if os.path.isabs(rel_src):
                # Source files may not be from the source directory if they originate in source-only libraries,
                # so we can't assert that the absolute path is anywhere in particular.
                if src.is_built:
                    assert rel_src.startswith(build_dir)
                    rel_src = rel_src[len(build_dir) + 1:]
        elif is_generated:
            raise AssertionError('BUG: broken generated source file handling for {!r}'.format(src))
        else:
            raise InvalidArguments('Invalid source type: {!r}'.format(src))
        obj_basename = self.object_filename_from_source(target, src)
        rel_obj = os.path.join(self.get_target_private_dir(target), obj_basename)
        dep_file = compiler.depfile_for_object(rel_obj)

        # Add MSVC debug file generation compile flags: /Fd /FS
        commands += self.get_compile_debugfile_args(compiler, target, rel_obj)

        # PCH handling
        if self.environment.coredata.base_options.get('b_pch', False):
            commands += self.get_pch_include_args(compiler, target)
            pchlist = target.get_pch(compiler.language)
        else:
            pchlist = []
        if not pchlist:
            pch_dep = []
        elif compiler.id == 'intel':
            pch_dep = []
        else:
            arr = []
            i = os.path.join(self.get_target_private_dir(target), compiler.get_pch_name(pchlist[0]))
            arr.append(i)
            pch_dep = arr

        crstr = ''
        if target.is_cross:
            crstr = '_CROSS'
        compiler_name = '%s%s_COMPILER' % (compiler.get_language(), crstr)
        extra_deps = []
        if compiler.get_language() == 'fortran':
            # Can't read source file to scan for deps if it's generated later
            # at build-time. Skip scanning for deps, and just set the module
            # outdir argument instead.
            # https://github.com/mesonbuild/meson/issues/1348
            if not is_generated:
                abs_src = os.path.join(build_dir, rel_src)
                extra_deps += self.get_fortran_deps(compiler, abs_src, target)
            # Dependency hack. Remove once multiple outputs in Ninja is fixed:
            # https://groups.google.com/forum/#!topic/ninja-build/j-2RfBIOd_8
            for modname, srcfile in self.fortran_deps[target.get_basename()].items():
                modfile = os.path.join(self.get_target_private_dir(target),
                                       compiler.module_name_to_filename(modname))
                if srcfile == src:
                    depelem = NinjaBuildElement(self.all_outputs, modfile, 'FORTRAN_DEP_HACK' + crstr, rel_obj)
                    depelem.write(outfile)
            commands += compiler.get_module_outdir_args(self.get_target_private_dir(target))

        element = NinjaBuildElement(self.all_outputs, rel_obj, compiler_name, rel_src)
        for d in header_deps:
            if isinstance(d, File):
                d = d.rel_to_builddir(self.build_to_src)
            elif not self.has_dir_part(d):
                d = os.path.join(self.get_target_private_dir(target), d)
            element.add_dep(d)
        for d in extra_deps:
            element.add_dep(d)
        for d in order_deps:
            if isinstance(d, File):
                d = d.rel_to_builddir(self.build_to_src)
            elif not self.has_dir_part(d):
                d = os.path.join(self.get_target_private_dir(target), d)
            element.add_orderdep(d)
        element.add_orderdep(pch_dep)
        # Convert from GCC-style link argument naming to the naming used by the
        # current compiler.
        commands = commands.to_native()
        for i in self.get_fortran_orderdeps(target, compiler):
            element.add_orderdep(i)
        element.add_item('DEPFILE', dep_file)
        element.add_item('ARGS', commands)
        element.write(outfile)
        return rel_obj

    def has_dir_part(self, fname):
        # FIXME FIXME: The usage of this is a terrible and unreliable hack
        if isinstance(fname, File):
            return fname.subdir != ''
        return has_path_sep(fname)

    # Fortran is a bit weird (again). When you link against a library, just compiling a source file
    # requires the mod files that are output when single files are built. To do this right we would need to
    # scan all inputs and write out explicit deps for each file. That is stoo slow and too much effort so
    # instead just have an ordered dependency on the library. This ensures all required mod files are created.
    # The real deps are then detected via dep file generation from the compiler. This breaks on compilers that
    # produce incorrect dep files but such is life.
    def get_fortran_orderdeps(self, target, compiler):
        if compiler.language != 'fortran':
            return []
        return [os.path.join(self.get_target_dir(lt), lt.get_filename()) for lt in target.link_targets]

    def generate_msvc_pch_command(self, target, compiler, pch):
        if len(pch) != 2:
            raise MesonException('MSVC requires one header and one source to produce precompiled headers.')
        header = pch[0]
        source = pch[1]
        pchname = compiler.get_pch_name(header)
        dst = os.path.join(self.get_target_private_dir(target), pchname)

        commands = []
        commands += self.generate_basic_compiler_args(target, compiler)
        just_name = os.path.basename(header)
        (objname, pch_args) = compiler.gen_pch_args(just_name, source, dst)
        commands += pch_args
        commands += self.get_compile_debugfile_args(compiler, target, objname)
        dep = dst + '.' + compiler.get_depfile_suffix()
        return commands, dep, dst, [objname]

    def generate_gcc_pch_command(self, target, compiler, pch):
        commands = self._generate_single_compile(target, compiler)
        dst = os.path.join(self.get_target_private_dir(target),
                           os.path.basename(pch) + '.' + compiler.get_pch_suffix())
        dep = dst + '.' + compiler.get_depfile_suffix()
        return commands, dep, dst, []  # Gcc does not create an object file during pch generation.

    def generate_pch(self, target, outfile):
        cstr = ''
        pch_objects = []
        if target.is_cross:
            cstr = '_CROSS'
        for lang in ['c', 'cpp']:
            pch = target.get_pch(lang)
            if not pch:
                continue
            if not has_path_sep(pch[0]) or not has_path_sep(pch[-1]):
                msg = 'Precompiled header of {!r} must not be in the same ' \
                      'directory as source, please put it in a subdirectory.' \
                      ''.format(target.get_basename())
                raise InvalidArguments(msg)
            compiler = target.compilers[lang]
            if compiler.id == 'msvc':
                src = os.path.join(self.build_to_src, target.get_source_subdir(), pch[-1])
                (commands, dep, dst, objs) = self.generate_msvc_pch_command(target, compiler, pch)
                extradep = os.path.join(self.build_to_src, target.get_source_subdir(), pch[0])
            elif compiler.id == 'intel':
                # Intel generates on target generation
                continue
            else:
                src = os.path.join(self.build_to_src, target.get_source_subdir(), pch[0])
                (commands, dep, dst, objs) = self.generate_gcc_pch_command(target, compiler, pch[0])
                extradep = None
            pch_objects += objs
            rulename = compiler.get_language() + cstr + '_PCH'
            elem = NinjaBuildElement(self.all_outputs, dst, rulename, src)
            if extradep is not None:
                elem.add_dep(extradep)
            elem.add_item('ARGS', commands)
            elem.add_item('DEPFILE', dep)
            elem.write(outfile)
        return pch_objects

    def generate_shsym(self, outfile, target):
        target_name = target.get_filename()
        target_file = self.get_target_filename(target)
        targetdir = self.get_target_private_dir(target)
        symname = os.path.join(targetdir, target_name + '.symbols')
        elem = NinjaBuildElement(self.all_outputs, symname, 'SHSYM', target_file)
        if self.environment.is_cross_build() and self.environment.cross_info.need_cross_compiler():
            elem.add_item('CROSS', '--cross-host=' + self.environment.cross_info.config['host_machine']['system'])
        elem.write(outfile)

    def get_cross_stdlib_link_args(self, target, linker):
        if isinstance(target, build.StaticLibrary) or not target.is_cross:
            return []
        if not self.environment.cross_info.has_stdlib(linker.language):
            return []
        return linker.get_no_stdlib_link_args()

    def get_target_type_link_args(self, target, linker):
        commands = []
        if isinstance(target, build.Executable):
            # Currently only used with the Swift compiler to add '-emit-executable'
            commands += linker.get_std_exe_link_args()
            # If gui_app is significant on this platform, add the appropriate linker arguments
            commands += linker.get_gui_app_args(target.gui_app)
            # If export_dynamic, add the appropriate linker arguments
            if target.export_dynamic:
                commands += linker.gen_export_dynamic_link_args(self.environment)
            # If implib, and that's significant on this platform (i.e. Windows using either GCC or Visual Studio)
            if target.import_filename:
                commands += linker.gen_import_library_args(os.path.join(self.get_target_dir(target), target.import_filename))
            if target.pie:
                commands += linker.get_pie_link_args()
        elif isinstance(target, build.SharedLibrary):
            if isinstance(target, build.SharedModule):
                options = self.environment.coredata.base_options
                commands += linker.get_std_shared_module_link_args(options)
            else:
                commands += linker.get_std_shared_lib_link_args()
            # All shared libraries are PIC
            commands += linker.get_pic_args()
            # Add -Wl,-soname arguments on Linux, -install_name on OS X
            commands += linker.get_soname_args(target.prefix, target.name, target.suffix,
                                               target.soversion, target.darwin_versions,
                                               isinstance(target, build.SharedModule))
            # This is only visited when building for Windows using either GCC or Visual Studio
            if target.vs_module_defs and hasattr(linker, 'gen_vs_module_defs_args'):
                commands += linker.gen_vs_module_defs_args(target.vs_module_defs.rel_to_builddir(self.build_to_src))
            # This is only visited when building for Windows using either GCC or Visual Studio
            if target.import_filename:
                commands += linker.gen_import_library_args(os.path.join(self.get_target_dir(target), target.import_filename))
        elif isinstance(target, build.StaticLibrary):
            commands += linker.get_std_link_args()
        else:
            raise RuntimeError('Unknown build target type.')
        return commands

    def get_link_whole_args(self, linker, target):
        target_args = self.build_target_link_arguments(linker, target.link_whole_targets)
        return linker.get_link_whole_for(target_args) if len(target_args) else []

    @staticmethod
    @lru_cache(maxsize=None)
    def guess_library_absolute_path(linker, libname, search_dirs, patterns):
        for d in search_dirs:
            for p in patterns:
                trial = CCompiler._get_trials_from_pattern(p, d, libname)
                if not trial:
                    continue
                trial = CCompiler._get_file_from_list(trial)
                if not trial:
                    continue
                # Return the first result
                return trial

    def guess_external_link_dependencies(self, linker, target, commands, internal):
        # Ideally the linker would generate dependency information that could be used.
        # But that has 2 problems:
        # * currently ld can not create dependency information in a way that ninja can use:
        #   https://sourceware.org/bugzilla/show_bug.cgi?id=22843
        # * Meson optimizes libraries from the same build using the symbol extractor.
        #   Just letting ninja use ld generated dependencies would undo this optimization.
        search_dirs = OrderedSet()
        libs = OrderedSet()
        absolute_libs = []

        build_dir = self.environment.get_build_dir()
        # the following loop sometimes consumes two items from command in one pass
        it = iter(commands)
        for item in it:
            if item in internal and not item.startswith('-'):
                continue

            if item.startswith('-L'):
                if len(item) > 2:
                    path = item[2:]
                else:
                    try:
                        path = next(it)
                    except StopIteration:
                        mlog.warning("Generated linker command has -L argument without following path")
                        break
                if not os.path.isabs(path):
                    path = os.path.join(build_dir, path)
                search_dirs.add(path)
            elif item.startswith('-l'):
                if len(item) > 2:
                    lib = item[2:]
                else:
                    try:
                        lib = next(it)
                    except StopIteration:
                        mlog.warning("Generated linker command has '-l' argument without following library name")
                        break
                libs.add(lib)
            elif os.path.isabs(item) and self.environment.is_library(item) and os.path.isfile(item):
                absolute_libs.append(item)

        guessed_dependencies = []
        # TODO The get_library_naming requirement currently excludes link targets that use d or fortran as their main linker
        if hasattr(linker, 'get_library_naming'):
            search_dirs = tuple(search_dirs) + linker.get_library_dirs(self.environment)
            static_patterns = linker.get_library_naming(self.environment, 'static', strict=True)
            shared_patterns = linker.get_library_naming(self.environment, 'shared', strict=True)
            for libname in libs:
                # be conservative and record most likely shared and static resolution, because we don't know exactly
                # which one the linker will prefer
                staticlibs = self.guess_library_absolute_path(linker, libname,
                                                              search_dirs, static_patterns)
                sharedlibs = self.guess_library_absolute_path(linker, libname,
                                                              search_dirs, shared_patterns)
                if staticlibs:
                    guessed_dependencies.append(os.path.realpath(staticlibs))
                if sharedlibs:
                    guessed_dependencies.append(os.path.realpath(sharedlibs))

        return guessed_dependencies + absolute_libs

    def generate_link(self, target, outfile, outname, obj_list, linker, extra_args=[], stdlib_args=[]):
        if isinstance(target, build.StaticLibrary):
            linker_base = 'STATIC'
        else:
            linker_base = linker.get_language() # Fixme.
        if isinstance(target, build.SharedLibrary):
            self.generate_shsym(outfile, target)
        crstr = ''
        if target.is_cross:
            crstr = '_CROSS'
        linker_rule = linker_base + crstr + '_LINKER'
        # Create an empty commands list, and start adding link arguments from
        # various sources in the order in which they must override each other
        # starting from hard-coded defaults followed by build options and so on.
        #
        # Once all the linker options have been passed, we will start passing
        # libraries and library paths from internal and external sources.
        commands = CompilerArgs(linker)
        # First, the trivial ones that are impossible to override.
        #
        # Add linker args for linking this target derived from 'base' build
        # options passed on the command-line, in default_options, etc.
        # These have the lowest priority.
        if isinstance(target, build.StaticLibrary):
            commands += linker.get_base_link_args(self.get_base_options_for_target(target))
        else:
            commands += compilers.get_base_link_args(self.get_base_options_for_target(target),
                                                     linker,
                                                     isinstance(target, build.SharedModule))
        # Add -nostdlib if needed; can't be overridden
        commands += self.get_cross_stdlib_link_args(target, linker)
        # Add things like /NOLOGO; usually can't be overridden
        commands += linker.get_linker_always_args()
        # Add buildtype linker args: optimization level, etc.
        commands += linker.get_buildtype_linker_args(self.get_option_for_target('buildtype', target))
        # Add /DEBUG and the pdb filename when using MSVC
        if self.get_option_for_target('debug', target):
            commands += self.get_link_debugfile_args(linker, target, outname)
        # Add link args specific to this BuildTarget type, such as soname args,
        # PIC, import library generation, etc.
        commands += self.get_target_type_link_args(target, linker)
        # Archives that are copied wholesale in the result. Must be before any
        # other link targets so missing symbols from whole archives are found in those.
        if not isinstance(target, build.StaticLibrary):
            commands += self.get_link_whole_args(linker, target)

        if not isinstance(target, build.StaticLibrary):
            # Add link args added using add_project_link_arguments()
            commands += self.build.get_project_link_args(linker, target.subproject, target.is_cross)
            # Add link args added using add_global_link_arguments()
            # These override per-project link arguments
            commands += self.build.get_global_link_args(linker, target.is_cross)
            if not target.is_cross:
                # Link args added from the env: LDFLAGS. We want these to
                # override all the defaults but not the per-target link args.
                commands += self.environment.coredata.get_external_link_args(linker.get_language())

        # Now we will add libraries and library paths from various sources

        # Add link args to link to all internal libraries (link_with:) and
        # internal dependencies needed by this target.
        if linker_base == 'STATIC':
            # Link arguments of static libraries are not put in the command
            # line of the library. They are instead appended to the command
            # line where the static library is used.
            dependencies = []
        else:
            dependencies = target.get_dependencies()
        internal = self.build_target_link_arguments(linker, dependencies)
        commands += internal
        # Only non-static built targets need link args and link dependencies
        if not isinstance(target, build.StaticLibrary):
            # For 'automagic' deps: Boost and GTest. Also dependency('threads').
            # pkg-config puts the thread flags itself via `Cflags:`
            need_threads = False
            need_openmp = False

            commands += target.link_args
            # External deps must be last because target link libraries may depend on them.
            for dep in target.get_external_deps():
                # Extend without reordering or de-dup to preserve `-L -l` sets
                # https://github.com/mesonbuild/meson/issues/1718
                commands.extend_direct(dep.get_link_args())
                need_threads |= dep.need_threads()
                need_openmp |= dep.need_openmp()
            for d in target.get_dependencies():
                if isinstance(d, build.StaticLibrary):
                    for dep in d.get_external_deps():
                        need_threads |= dep.need_threads()
                        need_openmp |= dep.need_openmp()
                        commands.extend_direct(dep.get_link_args())
            if need_openmp:
                commands += linker.openmp_flags()
            if need_threads:
                commands += linker.thread_link_flags(self.environment)

        # Add link args for c_* or cpp_* build options. Currently this only
        # adds c_winlibs and cpp_winlibs when building for Windows. This needs
        # to be after all internal and external libraries so that unresolved
        # symbols from those can be found here. This is needed when the
        # *_winlibs that we want to link to are static mingw64 libraries.
        commands += linker.get_option_link_args(self.environment.coredata.compiler_options)

        dep_targets = []
        dep_targets.extend(self.guess_external_link_dependencies(linker, target, commands, internal))

        # Set runtime-paths so we can run executables without needing to set
        # LD_LIBRARY_PATH, etc in the environment. Doesn't work on Windows.
        if has_path_sep(target.name):
            # Target names really should not have slashes in them, but
            # unfortunately we did not check for that and some downstream projects
            # now have them. Once slashes are forbidden, remove this bit.
            target_slashname_workaround_dir = os.path.join(
                os.path.dirname(target.name),
                self.get_target_dir(target))
        else:
            target_slashname_workaround_dir = self.get_target_dir(target)
        commands += linker.build_rpath_args(self.environment.get_build_dir(),
                                            target_slashname_workaround_dir,
                                            self.determine_rpath_dirs(target),
                                            target.build_rpath,
                                            target.install_rpath)
        # Add libraries generated by custom targets
        custom_target_libraries = self.get_custom_target_provided_libraries(target)
        commands += extra_args
        commands += custom_target_libraries
        commands += stdlib_args # Standard library arguments go last, because they never depend on anything.
        # Convert from GCC-style link argument naming to the naming used by the
        # current compiler.
        commands = commands.to_native()
        dep_targets.extend([self.get_dependency_filename(t) for t in dependencies])
        dep_targets.extend([self.get_dependency_filename(t)
                            for t in target.link_depends])
        elem = NinjaBuildElement(self.all_outputs, outname, linker_rule, obj_list)
        elem.add_dep(dep_targets + custom_target_libraries)
        elem.add_item('LINK_ARGS', commands)
        return elem

    def get_dependency_filename(self, t):
        if isinstance(t, build.SharedLibrary):
            return os.path.join(self.get_target_private_dir(t), t.get_filename() + '.symbols')
        elif isinstance(t, mesonlib.File):
            if t.is_built:
                return t.relative_name()
            else:
                return t.absolute_path(self.environment.get_source_dir(),
                                       self.environment.get_build_dir())
        return self.get_target_filename(t)

    def generate_shlib_aliases(self, target, outdir):
        aliases = target.get_aliases()
        for alias, to in aliases.items():
            aliasfile = os.path.join(self.environment.get_build_dir(), outdir, alias)
            try:
                os.remove(aliasfile)
            except Exception:
                pass
            try:
                os.symlink(to, aliasfile)
            except NotImplementedError:
                mlog.debug("Library versioning disabled because symlinks are not supported.")
            except OSError:
                mlog.debug("Library versioning disabled because we do not have symlink creation privileges.")

    def generate_custom_target_clean(self, outfile, trees):
        e = NinjaBuildElement(self.all_outputs, 'meson-clean-ctlist', 'CUSTOM_COMMAND', 'PHONY')
        d = CleanTrees(self.environment.get_build_dir(), trees)
        d_file = os.path.join(self.environment.get_scratch_dir(), 'cleantrees.dat')
        e.add_item('COMMAND', self.environment.get_build_command() + ['--internal', 'cleantrees', d_file])
        e.add_item('description', 'Cleaning custom target directories.')
        e.write(outfile)
        # Alias that runs the target defined above
        self.create_target_alias('meson-clean-ctlist', outfile)
        # Write out the data file passed to the script
        with open(d_file, 'wb') as ofile:
            pickle.dump(d, ofile)
        return 'clean-ctlist'

    def generate_gcov_clean(self, outfile):
        gcno_elem = NinjaBuildElement(self.all_outputs, 'meson-clean-gcno', 'CUSTOM_COMMAND', 'PHONY')
        script_root = self.environment.get_script_dir()
        clean_script = os.path.join(script_root, 'delwithsuffix.py')
        gcno_elem.add_item('COMMAND', mesonlib.python_command + [clean_script, '.', 'gcno'])
        gcno_elem.add_item('description', 'Deleting gcno files.')
        gcno_elem.write(outfile)
        # Alias that runs the target defined above
        self.create_target_alias('meson-clean-gcno', outfile)

        gcda_elem = NinjaBuildElement(self.all_outputs, 'meson-clean-gcda', 'CUSTOM_COMMAND', 'PHONY')
        script_root = self.environment.get_script_dir()
        clean_script = os.path.join(script_root, 'delwithsuffix.py')
        gcda_elem.add_item('COMMAND', mesonlib.python_command + [clean_script, '.', 'gcda'])
        gcda_elem.add_item('description', 'Deleting gcda files.')
        gcda_elem.write(outfile)
        # Alias that runs the target defined above
        self.create_target_alias('meson-clean-gcda', outfile)

    def get_user_option_args(self):
        cmds = []
        for (k, v) in self.environment.coredata.user_options.items():
            cmds.append('-D' + k + '=' + (v.value if isinstance(v.value, str) else str(v.value).lower()))
        # The order of these arguments must be the same between runs of Meson
        # to ensure reproducible output. The order we pass them shouldn't
        # affect behavior in any other way.
        return sorted(cmds)

    def generate_dist(self, outfile):
        elem = NinjaBuildElement(self.all_outputs, 'meson-dist', 'CUSTOM_COMMAND', 'PHONY')
        elem.add_item('DESC', 'Creating source packages')
        elem.add_item('COMMAND', self.environment.get_build_command() + [
            '--internal', 'dist',
            self.environment.source_dir,
            self.environment.build_dir,
        ] + self.environment.get_build_command())
        elem.add_item('pool', 'console')
        elem.write(outfile)
        # Alias that runs the target defined above
        self.create_target_alias('meson-dist', outfile)

    # For things like scan-build and other helper tools we might have.
    def generate_utils(self, outfile):
        cmd = self.environment.get_build_command() + \
            ['--internal', 'scanbuild', self.environment.source_dir, self.environment.build_dir] + \
            self.environment.get_build_command() + self.get_user_option_args()
        elem = NinjaBuildElement(self.all_outputs, 'meson-scan-build', 'CUSTOM_COMMAND', 'PHONY')
        elem.add_item('COMMAND', cmd)
        elem.add_item('pool', 'console')
        elem.write(outfile)
        # Alias that runs the target defined above
        self.create_target_alias('meson-scan-build', outfile)
        cmd = self.environment.get_build_command() + ['--internal', 'uninstall']
        elem = NinjaBuildElement(self.all_outputs, 'meson-uninstall', 'CUSTOM_COMMAND', 'PHONY')
        elem.add_item('COMMAND', cmd)
        elem.add_item('pool', 'console')
        elem.write(outfile)
        # Alias that runs the target defined above
        self.create_target_alias('meson-uninstall', outfile)

    def generate_ending(self, outfile):
        targetlist = []
        for t in self.get_build_by_default_targets().values():
            # Add the first output of each target to the 'all' target so that
            # they are all built
            targetlist.append(os.path.join(self.get_target_dir(t), t.get_outputs()[0]))

        elem = NinjaBuildElement(self.all_outputs, 'all', 'phony', targetlist)
        elem.write(outfile)

        default = 'default all\n\n'
        outfile.write(default)

        elem = NinjaBuildElement(self.all_outputs, 'meson-clean', 'CUSTOM_COMMAND', 'PHONY')
        elem.add_item('COMMAND', [self.ninja_command, '-t', 'clean'])
        elem.add_item('description', 'Cleaning.')
        # Alias that runs the above-defined meson-clean target
        self.create_target_alias('meson-clean', outfile)

        # If we have custom targets in this project, add all their outputs to
        # the list that is passed to the `cleantrees.py` script. The script
        # will manually delete all custom_target outputs that are directories
        # instead of files. This is needed because on platforms other than
        # Windows, Ninja only deletes directories while cleaning if they are
        # empty. https://github.com/mesonbuild/meson/issues/1220
        ctlist = []
        for t in self.build.get_targets().values():
            if isinstance(t, build.CustomTarget):
                # Create a list of all custom target outputs
                for o in t.get_outputs():
                    ctlist.append(os.path.join(self.get_target_dir(t), o))
        if ctlist:
            elem.add_dep(self.generate_custom_target_clean(outfile, ctlist))

        if 'b_coverage' in self.environment.coredata.base_options and \
           self.environment.coredata.base_options['b_coverage'].value:
            self.generate_gcov_clean(outfile)
            elem.add_dep('clean-gcda')
            elem.add_dep('clean-gcno')
        elem.write(outfile)

        deps = self.get_regen_filelist()
        elem = NinjaBuildElement(self.all_outputs, 'build.ninja', 'REGENERATE_BUILD', deps)
        elem.add_item('pool', 'console')
        elem.write(outfile)

        elem = NinjaBuildElement(self.all_outputs, 'reconfigure', 'REGENERATE_BUILD', 'PHONY')
        elem.add_item('pool', 'console')
        elem.write(outfile)

        elem = NinjaBuildElement(self.all_outputs, deps, 'phony', '')
        elem.write(outfile)

def load(build_dir):
    filename = os.path.join(build_dir, 'meson-private', 'install.dat')
    with open(filename, 'rb') as f:
        obj = pickle.load(f)
    return obj
