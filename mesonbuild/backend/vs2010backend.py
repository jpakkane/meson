# Copyright 2014-2016 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations
import copy
import itertools
import os
import xml.dom.minidom
import xml.etree.ElementTree as ET
import uuid
import typing as T
from pathlib import Path, PurePath

from . import backends
from .. import build
from .. import dependencies
from .. import mlog
from .. import compilers
from ..mesonlib import (
    File, MesonException, replace_if_different, OptionKey, version_compare, MachineChoice
)
from ..environment import Environment, build_filename

if T.TYPE_CHECKING:
    from ..interpreter import Interpreter


def autodetect_vs_version(build: T.Optional[build.Build], interpreter: T.Optional[Interpreter]) -> backends.Backend:
    vs_version = os.getenv('VisualStudioVersion', None)
    vs_install_dir = os.getenv('VSINSTALLDIR', None)
    if not vs_install_dir:
        raise MesonException('Could not detect Visual Studio: Environment variable VSINSTALLDIR is not set!\n'
                             'Are you running meson from the Visual Studio Developer Command Prompt?')
    # VisualStudioVersion is set since Visual Studio 11.0, but sometimes
    # vcvarsall.bat doesn't set it, so also use VSINSTALLDIR
    if vs_version == '11.0' or 'Visual Studio 11' in vs_install_dir:
        from mesonbuild.backend.vs2012backend import Vs2012Backend
        return Vs2012Backend(build, interpreter)
    if vs_version == '12.0' or 'Visual Studio 12' in vs_install_dir:
        from mesonbuild.backend.vs2013backend import Vs2013Backend
        return Vs2013Backend(build, interpreter)
    if vs_version == '14.0' or 'Visual Studio 14' in vs_install_dir:
        from mesonbuild.backend.vs2015backend import Vs2015Backend
        return Vs2015Backend(build, interpreter)
    if vs_version == '15.0' or 'Visual Studio 17' in vs_install_dir or \
       'Visual Studio\\2017' in vs_install_dir:
        from mesonbuild.backend.vs2017backend import Vs2017Backend
        return Vs2017Backend(build, interpreter)
    if vs_version == '16.0' or 'Visual Studio 19' in vs_install_dir or \
       'Visual Studio\\2019' in vs_install_dir:
        from mesonbuild.backend.vs2019backend import Vs2019Backend
        return Vs2019Backend(build, interpreter)
    if vs_version == '17.0' or 'Visual Studio 22' in vs_install_dir or \
       'Visual Studio\\2022' in vs_install_dir:
        from mesonbuild.backend.vs2022backend import Vs2022Backend
        return Vs2022Backend(build, interpreter)
    if 'Visual Studio 10.0' in vs_install_dir:
        return Vs2010Backend(build, interpreter)
    raise MesonException('Could not detect Visual Studio using VisualStudioVersion: {!r} or VSINSTALLDIR: {!r}!\n'
                         'Please specify the exact backend to use.'.format(vs_version, vs_install_dir))


def split_o_flags_args(args):
    """
    Splits any /O args and returns them. Does not take care of flags overriding
    previous ones. Skips non-O flag arguments.

    ['/Ox', '/Ob1'] returns ['/Ox', '/Ob1']
    ['/Oxj', '/MP'] returns ['/Ox', '/Oj']
    """
    o_flags = []
    for arg in args:
        if not arg.startswith('/O'):
            continue
        flags = list(arg[2:])
        # Assume that this one can't be clumped with the others since it takes
        # an argument itself
        if 'b' in flags:
            o_flags.append(arg)
        else:
            o_flags += ['/O' + f for f in flags]
    return o_flags


def generate_guid_from_path(path, path_type):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'meson-vs-' + path_type + ':' + str(path))).upper()


class Vs2010Backend(backends.Backend):
    def __init__(self, build: T.Optional[build.Build], interpreter: T.Optional[Interpreter]):
        super().__init__(build, interpreter)
        self.name = 'vs2010'
        self.project_file_version = '10.0.30319.1'
        self.sln_file_version = '11.00'
        self.sln_version_comment = '2010'
        self.platform_toolset = None
        self.vs_version = '2010'
        self.windows_target_platform_version = None
        self.subdirs = {}
        self.handled_target_deps = {}

    def get_target_private_dir(self, target):
        return os.path.join(self.get_target_dir(target), target.get_id())

    def generate_custom_generator_commands(self, target, parent_node):
        generator_output_files = []
        custom_target_include_dirs = []
        custom_target_output_files = []
        target_private_dir = self.relpath(self.get_target_private_dir(target), self.get_target_dir(target))
        down = self.target_to_build_root(target)
        for genlist in target.get_generated_sources():
            if isinstance(genlist, (build.CustomTarget, build.CustomTargetIndex)):
                for i in genlist.get_outputs():
                    # Path to the generated source from the current vcxproj dir via the build root
                    ipath = os.path.join(down, self.get_target_dir(genlist), i)
                    custom_target_output_files.append(ipath)
                idir = self.relpath(self.get_target_dir(genlist), self.get_target_dir(target))
                if idir not in custom_target_include_dirs:
                    custom_target_include_dirs.append(idir)
            else:
                generator = genlist.get_generator()
                exe = generator.get_exe()
                infilelist = genlist.get_inputs()
                outfilelist = genlist.get_outputs()
                source_dir = os.path.join(down, self.build_to_src, genlist.subdir)
                exe_arr = self.build_target_to_cmd_array(exe)
                idgroup = ET.SubElement(parent_node, 'ItemGroup')
                for i, curfile in enumerate(infilelist):
                    if len(infilelist) == len(outfilelist):
                        sole_output = os.path.join(target_private_dir, outfilelist[i])
                    else:
                        sole_output = ''
                    infilename = os.path.join(down, curfile.rel_to_builddir(self.build_to_src))
                    deps = self.get_custom_target_depend_files(genlist, True)
                    base_args = generator.get_arglist(infilename)
                    outfiles_rel = genlist.get_outputs_for(curfile)
                    outfiles = [os.path.join(target_private_dir, of) for of in outfiles_rel]
                    generator_output_files += outfiles
                    args = [x.replace("@INPUT@", infilename).replace('@OUTPUT@', sole_output)
                            for x in base_args]
                    args = self.replace_outputs(args, target_private_dir, outfiles_rel)
                    args = [x.replace("@SOURCE_DIR@", self.environment.get_source_dir())
                             .replace("@BUILD_DIR@", target_private_dir)
                            for x in args]
                    args = [x.replace("@CURRENT_SOURCE_DIR@", source_dir) for x in args]
                    args = [x.replace("@SOURCE_ROOT@", self.environment.get_source_dir())
                             .replace("@BUILD_ROOT@", self.environment.get_build_dir())
                            for x in args]
                    args = [x.replace('\\', '/') for x in args]
                    cmd = exe_arr + self.replace_extra_args(args, genlist)
                    # Always use a wrapper because MSBuild eats random characters when
                    # there are many arguments.
                    tdir_abs = os.path.join(self.environment.get_build_dir(), self.get_target_dir(target))
                    cmd, _ = self.as_meson_exe_cmdline(
                        cmd[0],
                        cmd[1:],
                        workdir=tdir_abs,
                        capture=outfiles[0] if generator.capture else None,
                        force_serialize=True
                    )
                    deps = cmd[-1:] + deps
                    abs_pdir = os.path.join(self.environment.get_build_dir(), self.get_target_dir(target))
                    os.makedirs(abs_pdir, exist_ok=True)
                    cbs = ET.SubElement(idgroup, 'CustomBuild', Include=infilename)
                    ET.SubElement(cbs, 'Command').text = ' '.join(self.quote_arguments(cmd))
                    ET.SubElement(cbs, 'Outputs').text = ';'.join(outfiles)
                    ET.SubElement(cbs, 'AdditionalInputs').text = ';'.join(deps)
        return generator_output_files, custom_target_output_files, custom_target_include_dirs

    def generate(self):
        target_machine = self.interpreter.builtin['target_machine'].cpu_family_method(None, None)
        if target_machine == '64' or target_machine == 'x86_64':
            # amd64 or x86_64
            self.platform = 'x64'
        elif target_machine == 'x86':
            # x86
            self.platform = 'Win32'
        elif target_machine == 'aarch64' or target_machine == 'arm64':
            target_cpu = self.interpreter.builtin['target_machine'].cpu_method(None, None)
            if target_cpu == 'arm64ec':
                self.platform = 'arm64ec'
            else:
                self.platform = 'arm64'
        elif 'arm' in target_machine.lower():
            self.platform = 'ARM'
        else:
            raise MesonException('Unsupported Visual Studio platform: ' + target_machine)

        build_machine = self.interpreter.builtin['build_machine'].cpu_family_method(None, None)
        if build_machine == '64' or build_machine == 'x86_64':
            # amd64 or x86_64
            self.build_platform = 'x64'
        elif build_machine == 'x86':
            # x86
            self.build_platform = 'Win32'
        elif build_machine == 'aarch64' or build_machine == 'arm64':
            target_cpu = self.interpreter.builtin['build_machine'].cpu_method(None, None)
            if target_cpu == 'arm64ec':
                self.build_platform = 'arm64ec'
            else:
                self.build_platform = 'arm64'
        elif 'arm' in build_machine.lower():
            self.build_platform = 'ARM'
        else:
            raise MesonException('Unsupported Visual Studio platform: ' + build_machine)

        self.buildtype = self.environment.coredata.get_option(OptionKey('buildtype'))
        self.optimization = self.environment.coredata.get_option(OptionKey('optimization'))
        self.debug = self.environment.coredata.get_option(OptionKey('debug'))
        try:
            self.sanitize = self.environment.coredata.get_option(OptionKey('b_sanitize'))
        except MesonException:
            self.sanitize = 'none'
        sln_filename = os.path.join(self.environment.get_build_dir(), self.build.project_name + '.sln')
        projlist = self.generate_projects()
        self.gen_testproj('RUN_TESTS', os.path.join(self.environment.get_build_dir(), 'RUN_TESTS.vcxproj'))
        self.gen_installproj('RUN_INSTALL', os.path.join(self.environment.get_build_dir(), 'RUN_INSTALL.vcxproj'))
        self.gen_regenproj('REGEN', os.path.join(self.environment.get_build_dir(), 'REGEN.vcxproj'))
        self.generate_solution(sln_filename, projlist)
        self.generate_regen_info()
        Vs2010Backend.touch_regen_timestamp(self.environment.get_build_dir())

    @staticmethod
    def get_regen_stampfile(build_dir: str) -> None:
        return os.path.join(os.path.join(build_dir, Environment.private_dir), 'regen.stamp')

    @staticmethod
    def touch_regen_timestamp(build_dir: str) -> None:
        with open(Vs2010Backend.get_regen_stampfile(build_dir), 'w', encoding='utf-8'):
            pass

    def get_vcvars_command(self):
        has_arch_values = 'VSCMD_ARG_TGT_ARCH' in os.environ and 'VSCMD_ARG_HOST_ARCH' in os.environ

        # Use vcvarsall.bat if we found it.
        if 'VCINSTALLDIR' in os.environ:
            vs_version = os.environ['VisualStudioVersion'] \
                if 'VisualStudioVersion' in os.environ else None
            relative_path = 'Auxiliary\\Build\\' if vs_version is not None and vs_version >= '15.0' else ''
            script_path = os.environ['VCINSTALLDIR'] + relative_path + 'vcvarsall.bat'
            if os.path.exists(script_path):
                if has_arch_values:
                    target_arch = os.environ['VSCMD_ARG_TGT_ARCH']
                    host_arch = os.environ['VSCMD_ARG_HOST_ARCH']
                else:
                    target_arch = os.environ.get('Platform', 'x86')
                    host_arch = target_arch
                arch = host_arch + '_' + target_arch if host_arch != target_arch else target_arch
                return f'"{script_path}" {arch}'

        # Otherwise try the VS2017 Developer Command Prompt.
        if 'VS150COMNTOOLS' in os.environ and has_arch_values:
            script_path = os.environ['VS150COMNTOOLS'] + 'VsDevCmd.bat'
            if os.path.exists(script_path):
                return '"%s" -arch=%s -host_arch=%s' % \
                    (script_path, os.environ['VSCMD_ARG_TGT_ARCH'], os.environ['VSCMD_ARG_HOST_ARCH'])
        return ''

    def get_obj_target_deps(self, obj_list):
        result = {}
        for o in obj_list:
            if isinstance(o, build.ExtractedObjects):
                result[o.target.get_id()] = o.target
        return result.items()

    def get_target_deps(self, t: T.Dict[T.Any, build.Target], recursive=False):
        all_deps: T.Dict[str, build.Target] = {}
        for target in t.values():
            if isinstance(target, build.CustomTarget):
                for d in target.get_target_dependencies():
                    # FIXME: this isn't strictly correct, as the target doesn't
                    # Get dependencies on non-targets, such as Files
                    if isinstance(d, build.Target):
                        all_deps[d.get_id()] = d
            elif isinstance(target, build.RunTarget):
                for d in target.get_dependencies():
                    all_deps[d.get_id()] = d
            elif isinstance(target, build.BuildTarget):
                for ldep in target.link_with:
                    if isinstance(ldep, build.CustomTargetIndex):
                        all_deps[ldep.get_id()] = ldep.target
                    else:
                        all_deps[ldep.get_id()] = ldep
                for ldep in target.link_whole:
                    if isinstance(ldep, build.CustomTargetIndex):
                        all_deps[ldep.get_id()] = ldep.target
                    else:
                        all_deps[ldep.get_id()] = ldep

                for ldep in target.link_depends:
                    if isinstance(ldep, build.CustomTargetIndex):
                        all_deps[ldep.get_id()] = ldep.target
                    elif isinstance(ldep, File):
                        # Already built, no target references needed
                        pass
                    else:
                        all_deps[ldep.get_id()] = ldep

                for obj_id, objdep in self.get_obj_target_deps(target.objects):
                    all_deps[obj_id] = objdep
            else:
                raise MesonException(f'Unknown target type for target {target}')

            for gendep in target.get_generated_sources():
                if isinstance(gendep, build.CustomTarget):
                    all_deps[gendep.get_id()] = gendep
                elif isinstance(gendep, build.CustomTargetIndex):
                    all_deps[gendep.target.get_id()] = gendep.target
                else:
                    generator = gendep.get_generator()
                    gen_exe = generator.get_exe()
                    if isinstance(gen_exe, build.Executable):
                        all_deps[gen_exe.get_id()] = gen_exe
                    for d in itertools.chain(generator.depends, gendep.depends):
                        if isinstance(d, build.CustomTargetIndex):
                            all_deps[d.get_id()] = d.target
                        elif isinstance(d, build.Target):
                            all_deps[d.get_id()] = d
                        # FIXME: we don't handle other kinds of deps correctly here, such
                        # as GeneratedLists, StructuredSources, and generated File.

        if not t or not recursive:
            return all_deps
        ret = self.get_target_deps(all_deps, recursive)
        ret.update(all_deps)
        return ret

    def generate_solution_dirs(self, ofile, parents):
        prj_templ = 'Project("{%s}") = "%s", "%s", "{%s}"\n'
        iterpaths = reversed(parents)
        # Skip first path
        next(iterpaths)
        for path in iterpaths:
            if path not in self.subdirs:
                basename = path.name
                identifier = generate_guid_from_path(path, 'subdir')
                # top-level directories have None as their parent_dir
                parent_dir = path.parent
                parent_identifier = self.subdirs[parent_dir][0] \
                    if parent_dir != PurePath('.') else None
                self.subdirs[path] = (identifier, parent_identifier)
                prj_line = prj_templ % (
                    self.environment.coredata.lang_guids['directory'],
                    basename, basename, self.subdirs[path][0])
                ofile.write(prj_line)
                ofile.write('EndProject\n')

    def generate_solution(self, sln_filename, projlist):
        default_projlist = self.get_build_by_default_targets()
        default_projlist.update(self.get_testlike_targets())
        sln_filename_tmp = sln_filename + '~'
        # Note using the utf-8 BOM requires the blank line, otherwise Visual Studio Version Selector fails.
        # Without the BOM, VSVS fails if there is a blank line.
        with open(sln_filename_tmp, 'w', encoding='utf-8-sig') as ofile:
            ofile.write('\nMicrosoft Visual Studio Solution File, Format Version %s\n' % self.sln_file_version)
            ofile.write('# Visual Studio %s\n' % self.sln_version_comment)
            prj_templ = 'Project("{%s}") = "%s", "%s", "{%s}"\n'
            for prj in projlist:
                coredata = self.environment.coredata
                if coredata.get_option(OptionKey('layout')) == 'mirror':
                    self.generate_solution_dirs(ofile, prj[1].parents)
                target = self.build.targets[prj[0]]
                lang = 'default'
                if hasattr(target, 'compilers') and target.compilers:
                    for lang_out in target.compilers.keys():
                        lang = lang_out
                        break
                prj_line = prj_templ % (
                    self.environment.coredata.lang_guids[lang],
                    prj[0], prj[1], prj[2])
                ofile.write(prj_line)
                target_dict = {target.get_id(): target}
                # Get recursive deps
                recursive_deps = self.get_target_deps(
                    target_dict, recursive=True)
                ofile.write('EndProject\n')
                for dep, target in recursive_deps.items():
                    if prj[0] in default_projlist:
                        default_projlist[dep] = target

            test_line = prj_templ % (self.environment.coredata.lang_guids['default'],
                                     'RUN_TESTS', 'RUN_TESTS.vcxproj',
                                     self.environment.coredata.test_guid)
            ofile.write(test_line)
            ofile.write('EndProject\n')
            regen_line = prj_templ % (self.environment.coredata.lang_guids['default'],
                                      'REGEN', 'REGEN.vcxproj',
                                      self.environment.coredata.regen_guid)
            ofile.write(regen_line)
            ofile.write('EndProject\n')
            install_line = prj_templ % (self.environment.coredata.lang_guids['default'],
                                        'RUN_INSTALL', 'RUN_INSTALL.vcxproj',
                                        self.environment.coredata.install_guid)
            ofile.write(install_line)
            ofile.write('EndProject\n')
            ofile.write('Global\n')
            ofile.write('\tGlobalSection(SolutionConfigurationPlatforms) = '
                        'preSolution\n')
            ofile.write('\t\t%s|%s = %s|%s\n' %
                        (self.buildtype, self.platform, self.buildtype,
                         self.platform))
            ofile.write('\tEndGlobalSection\n')
            ofile.write('\tGlobalSection(ProjectConfigurationPlatforms) = '
                        'postSolution\n')
            ofile.write('\t\t{%s}.%s|%s.ActiveCfg = %s|%s\n' %
                        (self.environment.coredata.regen_guid, self.buildtype,
                         self.platform, self.buildtype, self.platform))
            ofile.write('\t\t{%s}.%s|%s.Build.0 = %s|%s\n' %
                        (self.environment.coredata.regen_guid, self.buildtype,
                         self.platform, self.buildtype, self.platform))
            # Create the solution configuration
            for p in projlist:
                if p[3] is MachineChoice.BUILD:
                    config_platform = self.build_platform
                else:
                    config_platform = self.platform
                # Add to the list of projects in this solution
                ofile.write('\t\t{%s}.%s|%s.ActiveCfg = %s|%s\n' %
                            (p[2], self.buildtype, self.platform,
                             self.buildtype, config_platform))
                if p[0] in default_projlist and \
                   not isinstance(self.build.targets[p[0]], build.RunTarget):
                    # Add to the list of projects to be built
                    ofile.write('\t\t{%s}.%s|%s.Build.0 = %s|%s\n' %
                                (p[2], self.buildtype, self.platform,
                                 self.buildtype, config_platform))
            ofile.write('\t\t{%s}.%s|%s.ActiveCfg = %s|%s\n' %
                        (self.environment.coredata.test_guid, self.buildtype,
                         self.platform, self.buildtype, self.platform))
            ofile.write('\t\t{%s}.%s|%s.ActiveCfg = %s|%s\n' %
                        (self.environment.coredata.install_guid, self.buildtype,
                         self.platform, self.buildtype, self.platform))
            ofile.write('\tEndGlobalSection\n')
            ofile.write('\tGlobalSection(SolutionProperties) = preSolution\n')
            ofile.write('\t\tHideSolutionNode = FALSE\n')
            ofile.write('\tEndGlobalSection\n')
            if self.subdirs:
                ofile.write('\tGlobalSection(NestedProjects) = '
                            'preSolution\n')
                for p in projlist:
                    if p[1].parent != PurePath('.'):
                        ofile.write("\t\t{{{}}} = {{{}}}\n".format(p[2], self.subdirs[p[1].parent][0]))
                for subdir in self.subdirs.values():
                    if subdir[1]:
                        ofile.write("\t\t{{{}}} = {{{}}}\n".format(subdir[0], subdir[1]))
                ofile.write('\tEndGlobalSection\n')
            ofile.write('EndGlobal\n')
        replace_if_different(sln_filename, sln_filename_tmp)

    def generate_projects(self):
        startup_project = self.environment.coredata.options[OptionKey('backend_startup_project')].value
        projlist = []
        startup_idx = 0
        for (i, (name, target)) in enumerate(self.build.targets.items()):
            if startup_project and startup_project == target.get_basename():
                startup_idx = i
            outdir = Path(
                self.environment.get_build_dir(),
                self.get_target_dir(target)
            )
            outdir.mkdir(exist_ok=True, parents=True)
            fname = name + '.vcxproj'
            target_dir = PurePath(self.get_target_dir(target))
            relname = target_dir / fname
            projfile_path = outdir / fname
            proj_uuid = self.environment.coredata.target_guids[name]
            self.gen_vcxproj(target, str(projfile_path), proj_uuid)
            projlist.append((name, relname, proj_uuid, target.for_machine))

        # Put the startup project first in the project list
        if startup_idx:
            projlist.insert(0, projlist.pop(startup_idx))

        return projlist

    def split_sources(self, srclist):
        sources = []
        headers = []
        objects = []
        languages = []
        for i in srclist:
            if self.environment.is_header(i):
                headers.append(i)
            elif self.environment.is_object(i):
                objects.append(i)
            elif self.environment.is_source(i):
                sources.append(i)
                lang = self.lang_from_source_file(i)
                if lang not in languages:
                    languages.append(lang)
            elif self.environment.is_library(i):
                pass
            else:
                # Everything that is not an object or source file is considered a header.
                headers.append(i)
        return sources, headers, objects, languages

    def target_to_build_root(self, target):
        if self.get_target_dir(target) == '':
            return ''

        directories = os.path.normpath(self.get_target_dir(target)).split(os.sep)
        return os.sep.join(['..'] * len(directories))

    def quote_arguments(self, arr):
        return ['"%s"' % i for i in arr]

    def add_project_reference(self, root, include, projid, link_outputs=False):
        ig = ET.SubElement(root, 'ItemGroup')
        pref = ET.SubElement(ig, 'ProjectReference', Include=include)
        ET.SubElement(pref, 'Project').text = '{%s}' % projid
        if not link_outputs:
            # Do not link in generated .lib files from dependencies automatically.
            # We only use the dependencies for ordering and link in the generated
            # objects and .lib files manually.
            ET.SubElement(pref, 'LinkLibraryDependencies').text = 'false'

    def add_target_deps(self, root, target):
        target_dict = {target.get_id(): target}
        for dep in self.get_target_deps(target_dict).values():
            if dep.get_id() in self.handled_target_deps[target.get_id()]:
                # This dependency was already handled manually.
                continue
            relpath = self.get_target_dir_relative_to(dep, target)
            vcxproj = os.path.join(relpath, dep.get_id() + '.vcxproj')
            tid = self.environment.coredata.target_guids[dep.get_id()]
            self.add_project_reference(root, vcxproj, tid)

    def create_basic_project(self, target_name, *,
                             temp_dir,
                             guid,
                             conftype='Utility',
                             target_ext=None,
                             target_platform=None):
        root = ET.Element('Project', {'DefaultTargets': "Build",
                                      'ToolsVersion': '4.0',
                                      'xmlns': 'http://schemas.microsoft.com/developer/msbuild/2003'})

        confitems = ET.SubElement(root, 'ItemGroup', {'Label': 'ProjectConfigurations'})
        if not target_platform:
            target_platform = self.platform
        prjconf = ET.SubElement(confitems, 'ProjectConfiguration',
                                {'Include': self.buildtype + '|' + target_platform})
        p = ET.SubElement(prjconf, 'Configuration')
        p.text = self.buildtype
        pl = ET.SubElement(prjconf, 'Platform')
        pl.text = target_platform

        # Globals
        globalgroup = ET.SubElement(root, 'PropertyGroup', Label='Globals')
        guidelem = ET.SubElement(globalgroup, 'ProjectGuid')
        guidelem.text = '{%s}' % guid
        kw = ET.SubElement(globalgroup, 'Keyword')
        kw.text = self.platform + 'Proj'
        # XXX Wasn't here before for anything but gen_vcxproj , but seems fine?
        ns = ET.SubElement(globalgroup, 'RootNamespace')
        ns.text = target_name

        p = ET.SubElement(globalgroup, 'Platform')
        p.text = target_platform
        pname = ET.SubElement(globalgroup, 'ProjectName')
        pname.text = target_name
        if self.windows_target_platform_version:
            ET.SubElement(globalgroup, 'WindowsTargetPlatformVersion').text = self.windows_target_platform_version
        ET.SubElement(globalgroup, 'UseMultiToolTask').text = 'true'

        ET.SubElement(root, 'Import', Project=r'$(VCTargetsPath)\Microsoft.Cpp.Default.props')

        # Start configuration
        type_config = ET.SubElement(root, 'PropertyGroup', Label='Configuration')
        ET.SubElement(type_config, 'ConfigurationType').text = conftype
        ET.SubElement(type_config, 'CharacterSet').text = 'MultiByte'
        # Fixme: wasn't here before for gen_vcxproj()
        ET.SubElement(type_config, 'UseOfMfc').text = 'false'
        if self.platform_toolset:
            ET.SubElement(type_config, 'PlatformToolset').text = self.platform_toolset

        # End configuration section (but it can be added to further via type_config)
        ET.SubElement(root, 'Import', Project=r'$(VCTargetsPath)\Microsoft.Cpp.props')

        # Project information
        direlem = ET.SubElement(root, 'PropertyGroup')
        fver = ET.SubElement(direlem, '_ProjectFileVersion')
        fver.text = self.project_file_version
        outdir = ET.SubElement(direlem, 'OutDir')
        outdir.text = '.\\'
        intdir = ET.SubElement(direlem, 'IntDir')
        intdir.text = temp_dir + '\\'

        tname = ET.SubElement(direlem, 'TargetName')
        tname.text = target_name

        if target_ext:
            ET.SubElement(direlem, 'TargetExt').text = target_ext

        return (root, type_config)

    def gen_run_target_vcxproj(self, target, ofname, guid):
        (root, type_config) = self.create_basic_project(target.name,
                                                        temp_dir=target.get_id(),
                                                        guid=guid)
        depend_files = self.get_custom_target_depend_files(target)

        if not target.command:
            # This is an alias target and thus doesn't run any command. It's
            # enough to emit the references to the other projects for them to
            # be built/run/..., if necessary.
            assert isinstance(target, build.AliasTarget)
            assert len(depend_files) == 0
        else:
            assert not isinstance(target, build.AliasTarget)

            target_env = self.get_run_target_env(target)
            _, _, cmd_raw = self.eval_custom_target_command(target)
            wrapper_cmd, _ = self.as_meson_exe_cmdline(target.command[0], cmd_raw[1:],
                                                       force_serialize=True, env=target_env,
                                                       verbose=True)
            self.add_custom_build(root, 'run_target', ' '.join(self.quote_arguments(wrapper_cmd)),
                                  deps=depend_files)

        # The import is needed even for alias targets, otherwise the build
        # target isn't defined
        ET.SubElement(root, 'Import', Project=r'$(VCTargetsPath)\Microsoft.Cpp.targets')
        self.add_regen_dependency(root)
        self.add_target_deps(root, target)
        self._prettyprint_vcxproj_xml(ET.ElementTree(root), ofname)

    def gen_custom_target_vcxproj(self, target, ofname, guid):
        if target.for_machine is MachineChoice.BUILD:
            platform = self.build_platform
        else:
            platform = self.platform
        (root, type_config) = self.create_basic_project(target.name,
                                                        temp_dir=target.get_id(),
                                                        guid=guid,
                                                        target_platform=platform)
        # We need to always use absolute paths because our invocation is always
        # from the target dir, not the build root.
        target.absolute_paths = True
        (srcs, ofilenames, cmd) = self.eval_custom_target_command(target, True)
        depend_files = self.get_custom_target_depend_files(target, True)
        # Always use a wrapper because MSBuild eats random characters when
        # there are many arguments.
        tdir_abs = os.path.join(self.environment.get_build_dir(), self.get_target_dir(target))
        extra_bdeps = target.get_transitive_build_target_deps()
        wrapper_cmd, _ = self.as_meson_exe_cmdline(target.command[0], cmd[1:],
                                                   # All targets run from the target dir
                                                   workdir=tdir_abs,
                                                   extra_bdeps=extra_bdeps,
                                                   capture=ofilenames[0] if target.capture else None,
                                                   feed=srcs[0] if target.feed else None,
                                                   force_serialize=True,
                                                   env=target.env,
                                                   verbose=target.console)
        if target.build_always_stale:
            # Use a nonexistent file to always consider the target out-of-date.
            ofilenames += [self.nonexistent_file(os.path.join(self.environment.get_scratch_dir(),
                                                 'outofdate.file'))]
        self.add_custom_build(root, 'custom_target', ' '.join(self.quote_arguments(wrapper_cmd)),
                              deps=wrapper_cmd[-1:] + srcs + depend_files, outputs=ofilenames,
                              verify_files=not target.build_always_stale)
        ET.SubElement(root, 'Import', Project=r'$(VCTargetsPath)\Microsoft.Cpp.targets')
        self.generate_custom_generator_commands(target, root)
        self.add_regen_dependency(root)
        self.add_target_deps(root, target)
        self._prettyprint_vcxproj_xml(ET.ElementTree(root), ofname)

    @classmethod
    def lang_from_source_file(cls, src):
        ext = src.split('.')[-1]
        if ext in compilers.c_suffixes:
            return 'c'
        if ext in compilers.cpp_suffixes:
            return 'cpp'
        raise MesonException(f'Could not guess language from source file {src}.')

    def add_pch(self, pch_sources, lang, inc_cl):
        if lang in pch_sources:
            self.use_pch(pch_sources, lang, inc_cl)

    def create_pch(self, pch_sources, lang, inc_cl):
        pch = ET.SubElement(inc_cl, 'PrecompiledHeader')
        pch.text = 'Create'
        self.add_pch_files(pch_sources, lang, inc_cl)

    def use_pch(self, pch_sources, lang, inc_cl):
        pch = ET.SubElement(inc_cl, 'PrecompiledHeader')
        pch.text = 'Use'
        header = self.add_pch_files(pch_sources, lang, inc_cl)
        pch_include = ET.SubElement(inc_cl, 'ForcedIncludeFiles')
        pch_include.text = header + ';%(ForcedIncludeFiles)'

    def add_pch_files(self, pch_sources, lang, inc_cl):
        header = os.path.basename(pch_sources[lang][0])
        pch_file = ET.SubElement(inc_cl, 'PrecompiledHeaderFile')
        # When USING PCHs, MSVC will not do the regular include
        # directory lookup, but simply use a string match to find the
        # PCH to use. That means the #include directive must match the
        # pch_file.text used during PCH CREATION verbatim.
        # When CREATING a PCH, MSVC will do the include directory
        # lookup to find the actual PCH header to use. Thus, the PCH
        # header must either be in the include_directories of the target
        # or be in the same directory as the PCH implementation.
        pch_file.text = header
        pch_out = ET.SubElement(inc_cl, 'PrecompiledHeaderOutputFile')
        pch_out.text = f'$(IntDir)$(TargetName)-{lang}.pch'

        # Need to set the name for the pdb, as cl otherwise gives it a static
        # name. Which leads to problems when there is more than one pch
        # (e.g. for different languages).
        pch_pdb = ET.SubElement(inc_cl, 'ProgramDataBaseFileName')
        pch_pdb.text = f'$(IntDir)$(TargetName)-{lang}.pdb'

        return header

    def is_argument_with_msbuild_xml_entry(self, entry):
        # Remove arguments that have a top level XML entry so
        # they are not used twice.
        # FIXME add args as needed.
        if entry[1:].startswith('fsanitize'):
            return True
        return entry[1:].startswith('M')

    def add_additional_options(self, lang, parent_node, file_args):
        args = []
        for arg in file_args[lang].to_native():
            if self.is_argument_with_msbuild_xml_entry(arg):
                continue
            if arg == '%(AdditionalOptions)':
                args.append(arg)
            else:
                args.append(self.escape_additional_option(arg))
        ET.SubElement(parent_node, "AdditionalOptions").text = ' '.join(args)

    def add_preprocessor_defines(self, lang, parent_node, file_defines):
        defines = []
        for define in file_defines[lang]:
            if define == '%(PreprocessorDefinitions)':
                defines.append(define)
            else:
                defines.append(self.escape_preprocessor_define(define))
        ET.SubElement(parent_node, "PreprocessorDefinitions").text = ';'.join(defines)

    def add_include_dirs(self, lang, parent_node, file_inc_dirs):
        dirs = file_inc_dirs[lang]
        ET.SubElement(parent_node, "AdditionalIncludeDirectories").text = ';'.join(dirs)

    @staticmethod
    def has_objects(objects, additional_objects, generated_objects):
        # Ignore generated objects, those are automatically used by MSBuild because they are part of
        # the CustomBuild Outputs.
        return len(objects) + len(additional_objects) > 0

    @staticmethod
    def add_generated_objects(node, generated_objects):
        # Do not add generated objects to project file. Those are automatically used by MSBuild, because
        # they are part of the CustomBuild Outputs.
        return

    @staticmethod
    def escape_preprocessor_define(define):
        # See: https://msdn.microsoft.com/en-us/library/bb383819.aspx
        table = str.maketrans({'%': '%25', '$': '%24', '@': '%40',
                               "'": '%27', ';': '%3B', '?': '%3F', '*': '%2A',
                               # We need to escape backslash because it'll be un-escaped by
                               # Windows during process creation when it parses the arguments
                               # Basically, this converts `\` to `\\`.
                               '\\': '\\\\'})
        return define.translate(table)

    @staticmethod
    def escape_additional_option(option):
        # See: https://msdn.microsoft.com/en-us/library/bb383819.aspx
        table = str.maketrans({'%': '%25', '$': '%24', '@': '%40',
                               "'": '%27', ';': '%3B', '?': '%3F', '*': '%2A', ' ': '%20'})
        option = option.translate(table)
        # Since we're surrounding the option with ", if it ends in \ that will
        # escape the " when the process arguments are parsed and the starting
        # " will not terminate. So we escape it if that's the case.  I'm not
        # kidding, this is how escaping works for process args on Windows.
        if option.endswith('\\'):
            option += '\\'
        return f'"{option}"'

    @staticmethod
    def split_link_args(args):
        """
        Split a list of link arguments into three lists:
        * library search paths
        * library filenames (or paths)
        * other link arguments
        """
        lpaths = []
        libs = []
        other = []
        for arg in args:
            if arg.startswith('/LIBPATH:'):
                lpath = arg[9:]
                # De-dup library search paths by removing older entries when
                # a new one is found. This is necessary because unlike other
                # search paths such as the include path, the library is
                # searched for in the newest (right-most) search path first.
                if lpath in lpaths:
                    lpaths.remove(lpath)
                lpaths.append(lpath)
            elif arg.startswith(('/', '-')):
                other.append(arg)
            # It's ok if we miss libraries with non-standard extensions here.
            # They will go into the general link arguments.
            elif arg.endswith('.lib') or arg.endswith('.a'):
                # De-dup
                if arg not in libs:
                    libs.append(arg)
            else:
                other.append(arg)
        return lpaths, libs, other

    def _get_cl_compiler(self, target):
        for lang, c in target.compilers.items():
            if lang in ('c', 'cpp'):
                return c
        # No source files, only objects, but we still need a compiler, so
        # return a found compiler
        if len(target.objects) > 0:
            for lang, c in self.environment.coredata.compilers[target.for_machine].items():
                if lang in ('c', 'cpp'):
                    return c
        raise MesonException('Could not find a C or C++ compiler. MSVC can only build C/C++ projects.')

    def _prettyprint_vcxproj_xml(self, tree, ofname):
        ofname_tmp = ofname + '~'
        tree.write(ofname_tmp, encoding='utf-8', xml_declaration=True)

        # ElementTree can not do prettyprinting so do it manually
        doc = xml.dom.minidom.parse(ofname_tmp)
        with open(ofname_tmp, 'w', encoding='utf-8') as of:
            of.write(doc.toprettyxml())
        replace_if_different(ofname, ofname_tmp)

    def gen_vcxproj(self, target, ofname, guid):
        mlog.debug(f'Generating vcxproj {target.name}.')
        subsystem = 'Windows'
        self.handled_target_deps[target.get_id()] = []
        if isinstance(target, build.Executable):
            conftype = 'Application'
            # If someone knows how to set the version properly,
            # please send a patch.
            subsystem = target.win_subsystem.split(',')[0]
        elif isinstance(target, build.StaticLibrary):
            conftype = 'StaticLibrary'
        elif isinstance(target, build.SharedLibrary):
            conftype = 'DynamicLibrary'
        elif isinstance(target, build.CustomTarget):
            return self.gen_custom_target_vcxproj(target, ofname, guid)
        elif isinstance(target, build.RunTarget):
            return self.gen_run_target_vcxproj(target, ofname, guid)
        else:
            raise MesonException(f'Unknown target type for {target.get_basename()}')
        # Prefix to use to access the build root from the vcxproj dir
        down = self.target_to_build_root(target)
        # Prefix to use to access the source tree's root from the vcxproj dir
        proj_to_src_root = os.path.join(down, self.build_to_src)
        # Prefix to use to access the source tree's subdir from the vcxproj dir
        proj_to_src_dir = os.path.join(proj_to_src_root, self.get_target_dir(target))
        (sources, headers, objects, languages) = self.split_sources(target.sources)
        if target.is_unity:
            sources = self.generate_unity_files(target, sources)
        compiler = self._get_cl_compiler(target)
        build_args = compiler.get_buildtype_args(self.buildtype)
        build_args += compiler.get_optimization_args(self.optimization)
        build_args += compiler.get_debug_args(self.debug)
        build_args += compiler.sanitizer_compile_args(self.sanitize)
        buildtype_link_args = compiler.get_buildtype_linker_args(self.buildtype)
        vscrt_type = self.environment.coredata.options[OptionKey('b_vscrt')]
        target_name = target.name
        if target.for_machine is MachineChoice.BUILD:
            platform = self.build_platform
        else:
            platform = self.platform

        tfilename = os.path.splitext(target.get_filename())

        (root, type_config) = self.create_basic_project(tfilename[0],
                                                        temp_dir=target.get_id(),
                                                        guid=guid,
                                                        conftype=conftype,
                                                        target_ext=tfilename[1],
                                                        target_platform=platform)

        # FIXME: Should these just be set in create_basic_project(), even if
        # irrelevant for current target?

        # FIXME: Meson's LTO support needs to be integrated here
        ET.SubElement(type_config, 'WholeProgramOptimization').text = 'false'
        # Let VS auto-set the RTC level
        ET.SubElement(type_config, 'BasicRuntimeChecks').text = 'Default'
        # Incremental linking increases code size
        if '/INCREMENTAL:NO' in buildtype_link_args:
            ET.SubElement(type_config, 'LinkIncremental').text = 'false'

        # Build information
        compiles = ET.SubElement(root, 'ItemDefinitionGroup')
        clconf = ET.SubElement(compiles, 'ClCompile')
        # CRT type; debug or release
        if vscrt_type.value == 'from_buildtype':
            if self.buildtype == 'debug':
                ET.SubElement(type_config, 'UseDebugLibraries').text = 'true'
                ET.SubElement(clconf, 'RuntimeLibrary').text = 'MultiThreadedDebugDLL'
            else:
                ET.SubElement(type_config, 'UseDebugLibraries').text = 'false'
                ET.SubElement(clconf, 'RuntimeLibrary').text = 'MultiThreadedDLL'
        elif vscrt_type.value == 'static_from_buildtype':
            if self.buildtype == 'debug':
                ET.SubElement(type_config, 'UseDebugLibraries').text = 'true'
                ET.SubElement(clconf, 'RuntimeLibrary').text = 'MultiThreadedDebug'
            else:
                ET.SubElement(type_config, 'UseDebugLibraries').text = 'false'
                ET.SubElement(clconf, 'RuntimeLibrary').text = 'MultiThreaded'
        elif vscrt_type.value == 'mdd':
            ET.SubElement(type_config, 'UseDebugLibraries').text = 'true'
            ET.SubElement(clconf, 'RuntimeLibrary').text = 'MultiThreadedDebugDLL'
        elif vscrt_type.value == 'mt':
            # FIXME, wrong
            ET.SubElement(type_config, 'UseDebugLibraries').text = 'false'
            ET.SubElement(clconf, 'RuntimeLibrary').text = 'MultiThreaded'
        elif vscrt_type.value == 'mtd':
            # FIXME, wrong
            ET.SubElement(type_config, 'UseDebugLibraries').text = 'true'
            ET.SubElement(clconf, 'RuntimeLibrary').text = 'MultiThreadedDebug'
        else:
            ET.SubElement(type_config, 'UseDebugLibraries').text = 'false'
            ET.SubElement(clconf, 'RuntimeLibrary').text = 'MultiThreadedDLL'
        # Sanitizers
        if '/fsanitize=address' in build_args:
            ET.SubElement(type_config, 'EnableASAN').text = 'true'
        # Debug format
        if '/ZI' in build_args:
            ET.SubElement(clconf, 'DebugInformationFormat').text = 'EditAndContinue'
        elif '/Zi' in build_args:
            ET.SubElement(clconf, 'DebugInformationFormat').text = 'ProgramDatabase'
        elif '/Z7' in build_args:
            ET.SubElement(clconf, 'DebugInformationFormat').text = 'OldStyle'
        else:
            ET.SubElement(clconf, 'DebugInformationFormat').text = 'None'
        # Runtime checks
        if '/RTC1' in build_args:
            ET.SubElement(clconf, 'BasicRuntimeChecks').text = 'EnableFastChecks'
        elif '/RTCu' in build_args:
            ET.SubElement(clconf, 'BasicRuntimeChecks').text = 'UninitializedLocalUsageCheck'
        elif '/RTCs' in build_args:
            ET.SubElement(clconf, 'BasicRuntimeChecks').text = 'StackFrameRuntimeCheck'
        # Exception handling has to be set in the xml in addition to the "AdditionalOptions" because otherwise
        # cl will give warning D9025: overriding '/Ehs' with cpp_eh value
        if 'cpp' in target.compilers:
            eh = self.environment.coredata.options[OptionKey('eh', machine=target.for_machine, lang='cpp')]
            if eh.value == 'a':
                ET.SubElement(clconf, 'ExceptionHandling').text = 'Async'
            elif eh.value == 's':
                ET.SubElement(clconf, 'ExceptionHandling').text = 'SyncCThrow'
            elif eh.value == 'none':
                ET.SubElement(clconf, 'ExceptionHandling').text = 'false'
            else:  # 'sc' or 'default'
                ET.SubElement(clconf, 'ExceptionHandling').text = 'Sync'
        generated_files, custom_target_output_files, generated_files_include_dirs = self.generate_custom_generator_commands(
            target, root)
        (gen_src, gen_hdrs, gen_objs, gen_langs) = self.split_sources(generated_files)
        (custom_src, custom_hdrs, custom_objs, custom_langs) = self.split_sources(custom_target_output_files)
        gen_src += custom_src
        gen_hdrs += custom_hdrs
        gen_langs += custom_langs

        # Arguments, include dirs, defines for all files in the current target
        target_args = []
        target_defines = []
        target_inc_dirs = []
        # Arguments, include dirs, defines passed to individual files in
        # a target; perhaps because the args are language-specific
        #
        # file_args is also later split out into defines and include_dirs in
        # case someone passed those in there
        file_args = {l: c.compiler_args() for l, c in target.compilers.items()}
        file_defines = {l: [] for l in target.compilers}
        file_inc_dirs = {l: [] for l in target.compilers}
        # The order in which these compile args are added must match
        # generate_single_compile() and generate_basic_compiler_args()
        for l, comp in target.compilers.items():
            if l in file_args:
                file_args[l] += compilers.get_base_compile_args(
                    target.get_options(), comp)
                file_args[l] += comp.get_option_compile_args(
                    self.environment.coredata.options)

        # Add compile args added using add_project_arguments()
        for l, args in self.build.projects_args[target.for_machine].get(target.subproject, {}).items():
            if l in file_args:
                file_args[l] += args
        # Add compile args added using add_global_arguments()
        # These override per-project arguments
        for l, args in self.build.global_args[target.for_machine].items():
            if l in file_args:
                file_args[l] += args
        # Compile args added from the env or cross file: CFLAGS/CXXFLAGS, etc. We want these
        # to override all the defaults, but not the per-target compile args.
        for l in file_args.keys():
            opts = self.environment.coredata.options[OptionKey('args', machine=target.for_machine, lang=l)]
            file_args[l] += opts.value
        for args in file_args.values():
            # This is where Visual Studio will insert target_args, target_defines,
            # etc, which are added later from external deps (see below).
            args += ['%(AdditionalOptions)', '%(PreprocessorDefinitions)', '%(AdditionalIncludeDirectories)']
            # Add custom target dirs as includes automatically, but before
            # target-specific include dirs. See _generate_single_compile() in
            # the ninja backend for caveats.
            args += ['-I' + arg for arg in generated_files_include_dirs]
            # Add include dirs from the `include_directories:` kwarg on the target
            # and from `include_directories:` of internal deps of the target.
            #
            # Target include dirs should override internal deps include dirs.
            # This is handled in BuildTarget.process_kwargs()
            #
            # Include dirs from internal deps should override include dirs from
            # external deps and must maintain the order in which they are
            # specified. Hence, we must reverse so that the order is preserved.
            #
            # These are per-target, but we still add them as per-file because we
            # need them to be looked in first.
            for d in reversed(target.get_include_dirs()):
                # reversed is used to keep order of includes
                for i in reversed(d.get_incdirs()):
                    curdir = os.path.join(d.get_curdir(), i)
                    args.append('-I' + self.relpath(curdir, target.subdir))  # build dir
                    args.append('-I' + os.path.join(proj_to_src_root, curdir))  # src dir
                for i in d.get_extra_build_dirs():
                    curdir = os.path.join(d.get_curdir(), i)
                    args.append('-I' + self.relpath(curdir, target.subdir))  # build dir
        # Add per-target compile args, f.ex, `c_args : ['/DFOO']`. We set these
        # near the end since these are supposed to override everything else.
        for l, args in target.extra_args.items():
            if l in file_args:
                file_args[l] += args
        # The highest priority includes. In order of directory search:
        # target private dir, target build dir, target source dir
        for args in file_args.values():
            t_inc_dirs = [self.relpath(self.get_target_private_dir(target),
                                       self.get_target_dir(target))]
            if target.implicit_include_directories:
                t_inc_dirs += ['.', proj_to_src_dir]
            args += ['-I' + arg for arg in t_inc_dirs]

        # Split preprocessor defines and include directories out of the list of
        # all extra arguments. The rest go into %(AdditionalOptions).
        for l, args in file_args.items():
            for arg in args[:]:
                if arg.startswith(('-D', '/D')) or arg == '%(PreprocessorDefinitions)':
                    file_args[l].remove(arg)
                    # Don't escape the marker
                    if arg == '%(PreprocessorDefinitions)':
                        define = arg
                    else:
                        define = arg[2:]
                    # De-dup
                    if define not in file_defines[l]:
                        file_defines[l].append(define)
                elif arg.startswith(('-I', '/I')) or arg == '%(AdditionalIncludeDirectories)':
                    file_args[l].remove(arg)
                    # Don't escape the marker
                    if arg == '%(AdditionalIncludeDirectories)':
                        inc_dir = arg
                    else:
                        inc_dir = arg[2:]
                    # De-dup
                    if inc_dir not in file_inc_dirs[l]:
                        file_inc_dirs[l].append(inc_dir)
                    # Add include dirs to target as well so that "Go to Document" works in headers
                    if inc_dir not in target_inc_dirs:
                        target_inc_dirs.append(inc_dir)

        # Split compile args needed to find external dependencies
        # Link args are added while generating the link command
        for d in reversed(target.get_external_deps()):
            # Cflags required by external deps might have UNIX-specific flags,
            # so filter them out if needed
            if isinstance(d, dependencies.OpenMPDependency):
                ET.SubElement(clconf, 'OpenMPSupport').text = 'true'
            else:
                d_compile_args = compiler.unix_args_to_native(d.get_compile_args())
                for arg in d_compile_args:
                    if arg.startswith(('-D', '/D')):
                        define = arg[2:]
                        # De-dup
                        if define in target_defines:
                            target_defines.remove(define)
                        target_defines.append(define)
                    elif arg.startswith(('-I', '/I')):
                        inc_dir = arg[2:]
                        # De-dup
                        if inc_dir not in target_inc_dirs:
                            target_inc_dirs.append(inc_dir)
                    else:
                        target_args.append(arg)

        languages += gen_langs
        if '/Gw' in build_args:
            target_args.append('/Gw')
        if len(target_args) > 0:
            target_args.append('%(AdditionalOptions)')
            ET.SubElement(clconf, "AdditionalOptions").text = ' '.join(target_args)
        ET.SubElement(clconf, 'AdditionalIncludeDirectories').text = ';'.join(target_inc_dirs)
        target_defines.append('%(PreprocessorDefinitions)')
        ET.SubElement(clconf, 'PreprocessorDefinitions').text = ';'.join(target_defines)
        ET.SubElement(clconf, 'FunctionLevelLinking').text = 'true'
        # Warning level
        warning_level = target.get_option(OptionKey('warning_level'))
        ET.SubElement(clconf, 'WarningLevel').text = 'Level' + str(1 + int(warning_level))
        if target.get_option(OptionKey('werror')):
            ET.SubElement(clconf, 'TreatWarningAsError').text = 'true'
        # Optimization flags
        o_flags = split_o_flags_args(build_args)
        if '/Ox' in o_flags:
            ET.SubElement(clconf, 'Optimization').text = 'Full'
        elif '/O2' in o_flags:
            ET.SubElement(clconf, 'Optimization').text = 'MaxSpeed'
        elif '/O1' in o_flags:
            ET.SubElement(clconf, 'Optimization').text = 'MinSpace'
        elif '/Od' in o_flags:
            ET.SubElement(clconf, 'Optimization').text = 'Disabled'
        if '/Oi' in o_flags:
            ET.SubElement(clconf, 'IntrinsicFunctions').text = 'true'
        if '/Ob1' in o_flags:
            ET.SubElement(clconf, 'InlineFunctionExpansion').text = 'OnlyExplicitInline'
        elif '/Ob2' in o_flags:
            ET.SubElement(clconf, 'InlineFunctionExpansion').text = 'AnySuitable'
        # Size-preserving flags
        if '/Os' in o_flags:
            ET.SubElement(clconf, 'FavorSizeOrSpeed').text = 'Size'
        else:
            ET.SubElement(clconf, 'FavorSizeOrSpeed').text = 'Speed'
        # Note: SuppressStartupBanner is /NOLOGO and is 'true' by default
        self.generate_lang_standard_info(file_args, clconf)
        pch_sources = {}
        if self.environment.coredata.options.get(OptionKey('b_pch')):
            for lang in ['c', 'cpp']:
                pch = target.get_pch(lang)
                if not pch:
                    continue
                if compiler.id == 'msvc':
                    if len(pch) == 1:
                        # Auto generate PCH.
                        src = os.path.join(down, self.create_msvc_pch_implementation(target, lang, pch[0]))
                        pch_header_dir = os.path.dirname(os.path.join(proj_to_src_dir, pch[0]))
                    else:
                        src = os.path.join(proj_to_src_dir, pch[1])
                        pch_header_dir = None
                    pch_sources[lang] = [pch[0], src, lang, pch_header_dir]
                else:
                    # I don't know whether its relevant but let's handle other compilers
                    # used with a vs backend
                    pch_sources[lang] = [pch[0], None, lang, None]

        resourcecompile = ET.SubElement(compiles, 'ResourceCompile')
        ET.SubElement(resourcecompile, 'PreprocessorDefinitions')

        # Linker options
        link = ET.SubElement(compiles, 'Link')
        extra_link_args = compiler.compiler_args()
        # FIXME: Can these buildtype linker args be added as tags in the
        # vcxproj file (similar to buildtype compiler args) instead of in
        # AdditionalOptions?
        extra_link_args += compiler.get_buildtype_linker_args(self.buildtype)
        # Generate Debug info
        if self.debug:
            self.generate_debug_information(link)
        else:
            ET.SubElement(link, 'GenerateDebugInformation').text = 'false'
        if not isinstance(target, build.StaticLibrary):
            if isinstance(target, build.SharedModule):
                options = self.environment.coredata.options
                extra_link_args += compiler.get_std_shared_module_link_args(options)
            # Add link args added using add_project_link_arguments()
            extra_link_args += self.build.get_project_link_args(compiler, target.subproject, target.for_machine)
            # Add link args added using add_global_link_arguments()
            # These override per-project link arguments
            extra_link_args += self.build.get_global_link_args(compiler, target.for_machine)
            # Link args added from the env: LDFLAGS, or the cross file. We want
            # these to override all the defaults but not the per-target link
            # args.
            extra_link_args += self.environment.coredata.get_external_link_args(
                target.for_machine, compiler.get_language())
            # Only non-static built targets need link args and link dependencies
            extra_link_args += target.link_args
            # External deps must be last because target link libraries may depend on them.
            for dep in target.get_external_deps():
                # Extend without reordering or de-dup to preserve `-L -l` sets
                # https://github.com/mesonbuild/meson/issues/1718
                if isinstance(dep, dependencies.OpenMPDependency):
                    ET.SubElement(clconf, 'OpenMPSuppport').text = 'true'
                else:
                    extra_link_args.extend_direct(dep.get_link_args())
            for d in target.get_dependencies():
                if isinstance(d, build.StaticLibrary):
                    for dep in d.get_external_deps():
                        if isinstance(dep, dependencies.OpenMPDependency):
                            ET.SubElement(clconf, 'OpenMPSuppport').text = 'true'
                        else:
                            extra_link_args.extend_direct(dep.get_link_args())
        # Add link args for c_* or cpp_* build options. Currently this only
        # adds c_winlibs and cpp_winlibs when building for Windows. This needs
        # to be after all internal and external libraries so that unresolved
        # symbols from those can be found here. This is needed when the
        # *_winlibs that we want to link to are static mingw64 libraries.
        extra_link_args += compiler.get_option_link_args(self.environment.coredata.options)
        (additional_libpaths, additional_links, extra_link_args) = self.split_link_args(extra_link_args.to_native())

        # Add more libraries to be linked if needed
        for t in target.get_dependencies():
            if isinstance(t, build.CustomTargetIndex):
                # We don't need the actual project here, just the library name
                lobj = t
            else:
                lobj = self.build.targets[t.get_id()]
            linkname = os.path.join(down, self.get_target_filename_for_linking(lobj))
            if t in target.link_whole:
                if compiler.id == 'msvc' and version_compare(compiler.version, '<19.00.23918'):
                    # Expand our object lists manually if we are on pre-Visual Studio 2015 Update 2
                    l = t.extract_all_objects(False)

                    # Unfortunately, we can't use self.object_filename_from_source()
                    for gen in l.genlist:
                        for src in gen.get_outputs():
                            if self.environment.is_source(src) and not self.environment.is_header(src):
                                path = self.get_target_generated_dir(t, gen, src)
                                gen_src_ext = '.' + os.path.splitext(path)[1][1:]
                                extra_link_args.append(path[:-len(gen_src_ext)] + '.obj')

                    for src in l.srclist:
                        obj_basename = None
                        if self.environment.is_source(src) and not self.environment.is_header(src):
                            obj_basename = self.object_filename_from_source(t, src)
                            target_private_dir = self.relpath(self.get_target_private_dir(t),
                                                              self.get_target_dir(t))
                            rel_obj = os.path.join(target_private_dir, obj_basename)
                            extra_link_args.append(rel_obj)

                    extra_link_args.extend(self.flatten_object_list(t))
                else:
                    # /WHOLEARCHIVE:foo must go into AdditionalOptions
                    extra_link_args += compiler.get_link_whole_for(linkname)
                # To force Visual Studio to build this project even though it
                # has no sources, we include a reference to the vcxproj file
                # that builds this target. Technically we should add this only
                # if the current target has no sources, but it doesn't hurt to
                # have 'extra' references.
                trelpath = self.get_target_dir_relative_to(t, target)
                tvcxproj = os.path.join(trelpath, t.get_id() + '.vcxproj')
                tid = self.environment.coredata.target_guids[t.get_id()]
                self.add_project_reference(root, tvcxproj, tid, link_outputs=True)
                # Mark the dependency as already handled to not have
                # multiple references to the same target.
                self.handled_target_deps[target.get_id()].append(t.get_id())
            else:
                # Other libraries go into AdditionalDependencies
                if linkname not in additional_links:
                    additional_links.append(linkname)
        for lib in self.get_custom_target_provided_libraries(target):
            additional_links.append(self.relpath(lib, self.get_target_dir(target)))
        additional_objects = []
        for o in self.flatten_object_list(target, down):
            assert isinstance(o, str)
            additional_objects.append(o)
        for o in custom_objs:
            additional_objects.append(o)

        if len(extra_link_args) > 0:
            extra_link_args.append('%(AdditionalOptions)')
            ET.SubElement(link, "AdditionalOptions").text = ' '.join(extra_link_args)
        if len(additional_libpaths) > 0:
            additional_libpaths.insert(0, '%(AdditionalLibraryDirectories)')
            ET.SubElement(link, 'AdditionalLibraryDirectories').text = ';'.join(additional_libpaths)
        if len(additional_links) > 0:
            additional_links.append('%(AdditionalDependencies)')
            ET.SubElement(link, 'AdditionalDependencies').text = ';'.join(additional_links)
        ofile = ET.SubElement(link, 'OutputFile')
        ofile.text = f'$(OutDir){target.get_filename()}'
        subsys = ET.SubElement(link, 'SubSystem')
        subsys.text = subsystem
        if (isinstance(target, build.SharedLibrary) or isinstance(target, build.Executable)) and target.get_import_filename():
            # DLLs built with MSVC always have an import library except when
            # they're data-only DLLs, but we don't support those yet.
            ET.SubElement(link, 'ImportLibrary').text = target.get_import_filename()
        if isinstance(target, build.SharedLibrary):
            # Add module definitions file, if provided
            if target.vs_module_defs:
                if isinstance(target.vs_module_defs, File):
                    _vdf = os.path.join(down, target.vs_module_defs.rel_to_builddir(self.build_to_src))
                else:
                    _vdf = os.path.join(down, self.get_target_dir(target.vs_module_defs), target.vs_module_defs.get_outputs()[0])
                ET.SubElement(link, 'ModuleDefinitionFile').text = _vdf
        if self.debug:
            pdb = ET.SubElement(link, 'ProgramDataBaseFileName')
            pdb.text = f'$(OutDir){target_name}.pdb'
        targetmachine = ET.SubElement(link, 'TargetMachine')
        if target.for_machine is MachineChoice.BUILD:
            targetplatform = platform.lower()
        else:
            targetplatform = self.platform.lower()
        if targetplatform == 'win32':
            targetmachine.text = 'MachineX86'
        elif targetplatform == 'x64':
            targetmachine.text = 'MachineX64'
        elif targetplatform == 'arm':
            targetmachine.text = 'MachineARM'
        elif targetplatform == 'arm64':
            targetmachine.text = 'MachineARM64'
        elif targetplatform == 'arm64ec':
            targetmachine.text = 'MachineARM64EC'
        else:
            raise MesonException('Unsupported Visual Studio target machine: ' + targetplatform)
        # /nologo
        ET.SubElement(link, 'SuppressStartupBanner').text = 'true'
        # /release
        if not self.environment.coredata.get_option(OptionKey('debug')):
            ET.SubElement(link, 'SetChecksum').text = 'true'

        meson_file_group = ET.SubElement(root, 'ItemGroup')
        ET.SubElement(meson_file_group, 'None', Include=os.path.join(proj_to_src_dir, build_filename))

        # Visual Studio can't load projects that present duplicated items. Filter them out
        # by keeping track of already added paths.
        def path_normalize_add(path, lis):
            normalized = os.path.normcase(os.path.normpath(path))
            if normalized not in lis:
                lis.append(normalized)
                return True
            else:
                return False

        previous_includes = []
        if len(headers) + len(gen_hdrs) + len(target.extra_files) + len(pch_sources) > 0:
            inc_hdrs = ET.SubElement(root, 'ItemGroup')
            for h in headers:
                relpath = os.path.join(down, h.rel_to_builddir(self.build_to_src))
                if path_normalize_add(relpath, previous_includes):
                    ET.SubElement(inc_hdrs, 'CLInclude', Include=relpath)
            for h in gen_hdrs:
                if path_normalize_add(h, previous_includes):
                    ET.SubElement(inc_hdrs, 'CLInclude', Include=h)
            for h in target.extra_files:
                relpath = os.path.join(down, h.rel_to_builddir(self.build_to_src))
                if path_normalize_add(relpath, previous_includes):
                    ET.SubElement(inc_hdrs, 'CLInclude', Include=relpath)
            for lang in pch_sources:
                h = pch_sources[lang][0]
                path = os.path.join(proj_to_src_dir, h)
                if path_normalize_add(path, previous_includes):
                    ET.SubElement(inc_hdrs, 'CLInclude', Include=path)

        previous_sources = []
        if len(sources) + len(gen_src) + len(pch_sources) > 0:
            inc_src = ET.SubElement(root, 'ItemGroup')
            for s in sources:
                relpath = os.path.join(down, s.rel_to_builddir(self.build_to_src))
                if path_normalize_add(relpath, previous_sources):
                    inc_cl = ET.SubElement(inc_src, 'CLCompile', Include=relpath)
                    lang = Vs2010Backend.lang_from_source_file(s)
                    self.add_pch(pch_sources, lang, inc_cl)
                    self.add_additional_options(lang, inc_cl, file_args)
                    self.add_preprocessor_defines(lang, inc_cl, file_defines)
                    self.add_include_dirs(lang, inc_cl, file_inc_dirs)
                    ET.SubElement(inc_cl, 'ObjectFileName').text = "$(IntDir)" + \
                        self.object_filename_from_source(target, s)
            for s in gen_src:
                if path_normalize_add(s, previous_sources):
                    inc_cl = ET.SubElement(inc_src, 'CLCompile', Include=s)
                    lang = Vs2010Backend.lang_from_source_file(s)
                    self.add_pch(pch_sources, lang, inc_cl)
                    self.add_additional_options(lang, inc_cl, file_args)
                    self.add_preprocessor_defines(lang, inc_cl, file_defines)
                    self.add_include_dirs(lang, inc_cl, file_inc_dirs)
                    s = File.from_built_file(target.get_subdir(), s)
                    ET.SubElement(inc_cl, 'ObjectFileName').text = "$(IntDir)" + \
                        self.object_filename_from_source(target, s)
            for lang in pch_sources:
                impl = pch_sources[lang][1]
                if impl and path_normalize_add(impl, previous_sources):
                    inc_cl = ET.SubElement(inc_src, 'CLCompile', Include=impl)
                    self.create_pch(pch_sources, lang, inc_cl)
                    self.add_additional_options(lang, inc_cl, file_args)
                    self.add_preprocessor_defines(lang, inc_cl, file_defines)
                    pch_header_dir = pch_sources[lang][3]
                    if pch_header_dir:
                        inc_dirs = copy.deepcopy(file_inc_dirs)
                        inc_dirs[lang] = [pch_header_dir] + inc_dirs[lang]
                    else:
                        inc_dirs = file_inc_dirs
                    self.add_include_dirs(lang, inc_cl, inc_dirs)
                    # XXX: Do we need to set the object file name name here too?

        previous_objects = []
        if self.has_objects(objects, additional_objects, gen_objs):
            inc_objs = ET.SubElement(root, 'ItemGroup')
            for s in objects:
                relpath = os.path.join(down, s.rel_to_builddir(self.build_to_src))
                if path_normalize_add(relpath, previous_objects):
                    ET.SubElement(inc_objs, 'Object', Include=relpath)
            for s in additional_objects:
                if path_normalize_add(s, previous_objects):
                    ET.SubElement(inc_objs, 'Object', Include=s)
            self.add_generated_objects(inc_objs, gen_objs)

        ET.SubElement(root, 'Import', Project=r'$(VCTargetsPath)\Microsoft.Cpp.targets')
        self.add_regen_dependency(root)
        self.add_target_deps(root, target)
        self._prettyprint_vcxproj_xml(ET.ElementTree(root), ofname)

    def gen_regenproj(self, project_name, ofname):
        guid = self.environment.coredata.regen_guid
        (root, type_config) = self.create_basic_project(project_name,
                                                        temp_dir='regen-temp',
                                                        guid=guid)

        action = ET.SubElement(root, 'ItemDefinitionGroup')
        midl = ET.SubElement(action, 'Midl')
        ET.SubElement(midl, "AdditionalIncludeDirectories").text = '%(AdditionalIncludeDirectories)'
        ET.SubElement(midl, "OutputDirectory").text = '$(IntDir)'
        ET.SubElement(midl, 'HeaderFileName').text = '%(Filename).h'
        ET.SubElement(midl, 'TypeLibraryName').text = '%(Filename).tlb'
        ET.SubElement(midl, 'InterfaceIdentifierFilename').text = '%(Filename)_i.c'
        ET.SubElement(midl, 'ProxyFileName').text = '%(Filename)_p.c'
        regen_command = self.environment.get_build_command() + ['--internal', 'regencheck']
        cmd_templ = '''call %s > NUL
"%s" "%s"'''
        regen_command = cmd_templ % \
            (self.get_vcvars_command(), '" "'.join(regen_command), self.environment.get_scratch_dir())
        self.add_custom_build(root, 'regen', regen_command, deps=self.get_regen_filelist(),
                              outputs=[Vs2010Backend.get_regen_stampfile(self.environment.get_build_dir())],
                              msg='Checking whether solution needs to be regenerated.')
        ET.SubElement(root, 'Import', Project=r'$(VCTargetsPath)\Microsoft.Cpp.targets')
        ET.SubElement(root, 'ImportGroup', Label='ExtensionTargets')
        self._prettyprint_vcxproj_xml(ET.ElementTree(root), ofname)

    def gen_testproj(self, target_name, ofname):
        guid = self.environment.coredata.test_guid
        (root, type_config) = self.create_basic_project(target_name,
                                                        temp_dir='test-temp',
                                                        guid=guid)

        action = ET.SubElement(root, 'ItemDefinitionGroup')
        midl = ET.SubElement(action, 'Midl')
        ET.SubElement(midl, "AdditionalIncludeDirectories").text = '%(AdditionalIncludeDirectories)'
        ET.SubElement(midl, "OutputDirectory").text = '$(IntDir)'
        ET.SubElement(midl, 'HeaderFileName').text = '%(Filename).h'
        ET.SubElement(midl, 'TypeLibraryName').text = '%(Filename).tlb'
        ET.SubElement(midl, 'InterfaceIdentifierFilename').text = '%(Filename)_i.c'
        ET.SubElement(midl, 'ProxyFileName').text = '%(Filename)_p.c'
        # FIXME: No benchmarks?
        test_command = self.environment.get_build_command() + ['test', '--no-rebuild']
        if not self.environment.coredata.get_option(OptionKey('stdsplit')):
            test_command += ['--no-stdsplit']
        if self.environment.coredata.get_option(OptionKey('errorlogs')):
            test_command += ['--print-errorlogs']
        self.serialize_tests()
        self.add_custom_build(root, 'run_tests', '"%s"' % ('" "'.join(test_command)))
        ET.SubElement(root, 'Import', Project=r'$(VCTargetsPath)\Microsoft.Cpp.targets')
        self.add_regen_dependency(root)
        self._prettyprint_vcxproj_xml(ET.ElementTree(root), ofname)

    def gen_installproj(self, target_name, ofname):
        self.create_install_data_files()

        guid = self.environment.coredata.install_guid
        (root, type_config) = self.create_basic_project(target_name,
                                                        temp_dir='install-temp',
                                                        guid=guid)

        action = ET.SubElement(root, 'ItemDefinitionGroup')
        midl = ET.SubElement(action, 'Midl')
        ET.SubElement(midl, "AdditionalIncludeDirectories").text = '%(AdditionalIncludeDirectories)'
        ET.SubElement(midl, "OutputDirectory").text = '$(IntDir)'
        ET.SubElement(midl, 'HeaderFileName').text = '%(Filename).h'
        ET.SubElement(midl, 'TypeLibraryName').text = '%(Filename).tlb'
        ET.SubElement(midl, 'InterfaceIdentifierFilename').text = '%(Filename)_i.c'
        ET.SubElement(midl, 'ProxyFileName').text = '%(Filename)_p.c'
        install_command = self.environment.get_build_command() + ['install', '--no-rebuild']
        self.add_custom_build(root, 'run_install', '"%s"' % ('" "'.join(install_command)))
        ET.SubElement(root, 'Import', Project=r'$(VCTargetsPath)\Microsoft.Cpp.targets')
        self.add_regen_dependency(root)
        self._prettyprint_vcxproj_xml(ET.ElementTree(root), ofname)

    def add_custom_build(self, node, rulename, command, deps=None, outputs=None, msg=None, verify_files=True):
        igroup = ET.SubElement(node, 'ItemGroup')
        rulefile = os.path.join(self.environment.get_scratch_dir(), rulename + '.rule')
        if not os.path.exists(rulefile):
            with open(rulefile, 'w', encoding='utf-8') as f:
                f.write("# Meson regen file.")
        custombuild = ET.SubElement(igroup, 'CustomBuild', Include=rulefile)
        if msg:
            message = ET.SubElement(custombuild, 'Message')
            message.text = msg
        if not verify_files:
            ET.SubElement(custombuild, 'VerifyInputsAndOutputsExist').text = 'false'
        ET.SubElement(custombuild, 'Command').text = f'''setlocal
{command}
if %%errorlevel%% neq 0 goto :cmEnd
:cmEnd
endlocal & call :cmErrorLevel %%errorlevel%% & goto :cmDone
:cmErrorLevel
exit /b %%1
:cmDone
if %%errorlevel%% neq 0 goto :VCEnd'''
        if not outputs:
            # Use a nonexistent file to always consider the target out-of-date.
            outputs = [self.nonexistent_file(os.path.join(self.environment.get_scratch_dir(),
                                                          'outofdate.file'))]
        ET.SubElement(custombuild, 'Outputs').text = ';'.join(outputs)
        if deps:
            ET.SubElement(custombuild, 'AdditionalInputs').text = ';'.join(deps)

    @staticmethod
    def nonexistent_file(prefix):
        i = 0
        file = prefix
        while os.path.exists(file):
            file = '%s%d' % (prefix, i)
        return file

    def generate_debug_information(self, link):
        # valid values for vs2015 is 'false', 'true', 'DebugFastLink'
        ET.SubElement(link, 'GenerateDebugInformation').text = 'true'

    def add_regen_dependency(self, root):
        regen_vcxproj = os.path.join(self.environment.get_build_dir(), 'REGEN.vcxproj')
        self.add_project_reference(root, regen_vcxproj, self.environment.coredata.regen_guid)

    def generate_lang_standard_info(self, file_args, clconf):
        pass
