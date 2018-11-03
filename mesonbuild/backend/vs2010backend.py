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

import os
import pickle
import xml.dom.minidom
import xml.etree.ElementTree as ET
import uuid
from pathlib import Path, PurePath

from . import backends
from .. import build
from .. import dependencies
from .. import mlog
from .. import compilers
from ..compilers import CompilerArgs
from ..mesonlib import MesonException, File, python_command
from ..environment import Environment

def autodetect_vs_version(build):
    vs_version = os.getenv('VisualStudioVersion', None)
    vs_install_dir = os.getenv('VSINSTALLDIR', None)
    if not vs_install_dir:
        raise MesonException('Could not detect Visual Studio: Environment variable VSINSTALLDIR is not set!\n'
                             'Are you running meson from the Visual Studio Developer Command Prompt?')
    # VisualStudioVersion is set since Visual Studio 12.0, but sometimes
    # vcvarsall.bat doesn't set it, so also use VSINSTALLDIR
    if vs_version == '14.0' or 'Visual Studio 14' in vs_install_dir:
        from mesonbuild.backend.vs2015backend import Vs2015Backend
        return Vs2015Backend(build)
    if vs_version == '15.0' or 'Visual Studio 17' in vs_install_dir or \
       'Visual Studio\\2017' in vs_install_dir:
        from mesonbuild.backend.vs2017backend import Vs2017Backend
        return Vs2017Backend(build)
    if 'Visual Studio 10.0' in vs_install_dir:
        return Vs2010Backend(build)
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

class RegenInfo:
    def __init__(self, source_dir, build_dir, depfiles):
        self.source_dir = source_dir
        self.build_dir = build_dir
        self.depfiles = depfiles

class Vs2010Backend(backends.Backend):
    def __init__(self, build):
        super().__init__(build)
        self.name = 'vs2010'
        self.project_file_version = '10.0.30319.1'
        self.platform_toolset = None
        self.vs_version = '2010'
        self.windows_target_platform_version = None
        self.subdirs = {}

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
                exe_arr = self.exe_object_to_cmd_array(exe)
                idgroup = ET.SubElement(parent_node, 'ItemGroup')
                for i in range(len(infilelist)):
                    if len(infilelist) == len(outfilelist):
                        sole_output = os.path.join(target_private_dir, outfilelist[i])
                    else:
                        sole_output = ''
                    curfile = infilelist[i]
                    infilename = os.path.join(down, curfile.rel_to_builddir(self.build_to_src))
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
                    if generator.capture:
                        exe_data = self.serialize_executable(
                            'generator ' + cmd[0],
                            cmd[0],
                            cmd[1:],
                            self.environment.get_build_dir(),
                            capture=outfiles[0]
                        )
                        cmd = self.environment.get_build_command() + ['--internal', 'exe', exe_data]
                        abs_pdir = os.path.join(self.environment.get_build_dir(), self.get_target_dir(target))
                        os.makedirs(abs_pdir, exist_ok=True)
                    cbs = ET.SubElement(idgroup, 'CustomBuild', Include=infilename)
                    ET.SubElement(cbs, 'Command').text = ' '.join(self.quote_arguments(cmd))
                    ET.SubElement(cbs, 'Outputs').text = ';'.join(outfiles)
        return generator_output_files, custom_target_output_files, custom_target_include_dirs

    def generate(self, interp):
        self.interpreter = interp
        target_machine = self.interpreter.builtin['target_machine'].cpu_family_method(None, None)
        if target_machine.endswith('64'):
            # amd64 or x86_64
            self.platform = 'x64'
        elif target_machine == 'x86':
            # x86
            self.platform = 'Win32'
        elif 'arm' in target_machine.lower():
            self.platform = 'ARM'
        else:
            raise MesonException('Unsupported Visual Studio platform: ' + target_machine)
        self.buildtype = self.environment.coredata.get_builtin_option('buildtype')
        sln_filename = os.path.join(self.environment.get_build_dir(), self.build.project_name + '.sln')
        projlist = self.generate_projects()
        self.gen_testproj('RUN_TESTS', os.path.join(self.environment.get_build_dir(), 'RUN_TESTS.vcxproj'))
        self.gen_installproj('RUN_INSTALL', os.path.join(self.environment.get_build_dir(), 'RUN_INSTALL.vcxproj'))
        self.gen_regenproj('REGEN', os.path.join(self.environment.get_build_dir(), 'REGEN.vcxproj'))
        self.generate_solution(sln_filename, projlist)
        self.generate_regen_info()
        Vs2010Backend.touch_regen_timestamp(self.environment.get_build_dir())

    @staticmethod
    def get_regen_stampfile(build_dir):
        return os.path.join(os.path.join(build_dir, Environment.private_dir), 'regen.stamp')

    @staticmethod
    def touch_regen_timestamp(build_dir):
        with open(Vs2010Backend.get_regen_stampfile(build_dir), 'w'):
            pass

    def generate_regen_info(self):
        deps = self.get_regen_filelist()
        regeninfo = RegenInfo(self.environment.get_source_dir(),
                              self.environment.get_build_dir(),
                              deps)
        filename = os.path.join(self.environment.get_scratch_dir(),
                                'regeninfo.dump')
        with open(filename, 'wb') as f:
            pickle.dump(regeninfo, f)

    def get_obj_target_deps(self, obj_list):
        result = {}
        for o in obj_list:
            if isinstance(o, build.ExtractedObjects):
                result[o.target.get_id()] = o.target
        return result.items()

    def get_target_deps(self, t, recursive=False):
        all_deps = {}
        for target in t.values():
            if isinstance(target, build.CustomTarget):
                for d in target.get_target_dependencies():
                    all_deps[d.get_id()] = d
            elif isinstance(target, build.RunTarget):
                for d in [target.command] + target.args:
                    if isinstance(d, (build.BuildTarget, build.CustomTarget)):
                        all_deps[d.get_id()] = d
            elif isinstance(target, build.BuildTarget):
                for ldep in target.link_targets:
                    all_deps[ldep.get_id()] = ldep
                for ldep in target.link_whole_targets:
                    all_deps[ldep.get_id()] = ldep
                for obj_id, objdep in self.get_obj_target_deps(target.objects):
                    all_deps[obj_id] = objdep
                for gendep in target.get_generated_sources():
                    if isinstance(gendep, build.CustomTarget):
                        all_deps[gendep.get_id()] = gendep
                    elif isinstance(gendep, build.CustomTargetIndex):
                        all_deps[gendep.target.get_id()] = gendep.target
                    else:
                        gen_exe = gendep.generator.get_exe()
                        if isinstance(gen_exe, build.Executable):
                            all_deps[gen_exe.get_id()] = gen_exe
            else:
                raise MesonException('Unknown target type for target %s' % target)
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
                identifier = str(uuid.uuid4()).upper()
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
        with open(sln_filename, 'w', encoding='utf-8') as ofile:
            ofile.write('Microsoft Visual Studio Solution File, Format '
                        'Version 11.00\n')
            ofile.write('# Visual Studio ' + self.vs_version + '\n')
            prj_templ = 'Project("{%s}") = "%s", "%s", "{%s}"\n'
            for prj in projlist:
                coredata = self.environment.coredata
                if coredata.get_builtin_option('layout') == 'mirror':
                    self.generate_solution_dirs(ofile, prj[1].parents)
                target = self.build.targets[prj[0]]
                lang = 'default'
                if hasattr(target, 'compilers') and target.compilers:
                    for (lang_out, _) in target.compilers.items():
                        lang = lang_out
                        break
                prj_line = prj_templ % (
                    self.environment.coredata.lang_guids[lang],
                    prj[0], prj[1], prj[2])
                ofile.write(prj_line)
                target_dict = {target.get_id(): target}
                # Get direct deps
                all_deps = self.get_target_deps(target_dict)
                # Get recursive deps
                recursive_deps = self.get_target_deps(
                    target_dict, recursive=True)
                ofile.write('\tProjectSection(ProjectDependencies) = '
                            'postProject\n')
                regen_guid = self.environment.coredata.regen_guid
                ofile.write('\t\t{%s} = {%s}\n' % (regen_guid, regen_guid))
                for dep in all_deps.keys():
                    guid = self.environment.coredata.target_guids[dep]
                    ofile.write('\t\t{%s} = {%s}\n' % (guid, guid))
                ofile.write('\tEndProjectSection\n')
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
                # Add to the list of projects in this solution
                ofile.write('\t\t{%s}.%s|%s.ActiveCfg = %s|%s\n' %
                            (p[2], self.buildtype, self.platform,
                             self.buildtype, self.platform))
                if p[0] in default_projlist and \
                   not isinstance(self.build.targets[p[0]], build.RunTarget):
                    # Add to the list of projects to be built
                    ofile.write('\t\t{%s}.%s|%s.Build.0 = %s|%s\n' %
                                (p[2], self.buildtype, self.platform,
                                 self.buildtype, self.platform))
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
                        ofile.write("\t\t{%s} = {%s}\n" % (p[2], self.subdirs[p[1].parent][0]))
                for (_, subdir) in self.subdirs.items():
                    if subdir[1]:
                        ofile.write("\t\t{%s} = {%s}\n" % (subdir[0], subdir[1]))
                ofile.write('\tEndGlobalSection\n')
            ofile.write('EndGlobal\n')

    def generate_projects(self):
        startup_project = self.environment.coredata.backend_options['backend_startup_project'].value
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
            projlist.append((name, relname, proj_uuid))

        # Put the startup project first in the project list
        if startup_idx:
            projlist = [projlist[startup_idx]] + projlist[0:startup_idx] + projlist[startup_idx + 1:-1]

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

    def add_project_reference(self, root, include, projid):
        ig = ET.SubElement(root, 'ItemGroup')
        pref = ET.SubElement(ig, 'ProjectReference', Include=include)
        ET.SubElement(pref, 'Project').text = '{%s}' % projid

    def create_basic_crap(self, target):
        project_name = target.name
        root = ET.Element('Project', {'DefaultTargets': "Build",
                                      'ToolsVersion': '4.0',
                                      'xmlns': 'http://schemas.microsoft.com/developer/msbuild/2003'})
        confitems = ET.SubElement(root, 'ItemGroup', {'Label': 'ProjectConfigurations'})
        prjconf = ET.SubElement(confitems, 'ProjectConfiguration',
                                {'Include': self.buildtype + '|' + self.platform})
        p = ET.SubElement(prjconf, 'Configuration')
        p.text = self.buildtype
        pl = ET.SubElement(prjconf, 'Platform')
        pl.text = self.platform
        globalgroup = ET.SubElement(root, 'PropertyGroup', Label='Globals')
        guidelem = ET.SubElement(globalgroup, 'ProjectGuid')
        guidelem.text = '{%s}' % self.environment.coredata.test_guid
        kw = ET.SubElement(globalgroup, 'Keyword')
        kw.text = self.platform + 'Proj'
        p = ET.SubElement(globalgroup, 'Platform')
        p.text = self.platform
        pname = ET.SubElement(globalgroup, 'ProjectName')
        pname.text = project_name
        if self.windows_target_platform_version:
            ET.SubElement(globalgroup, 'WindowsTargetPlatformVersion').text = self.windows_target_platform_version
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.Default.props')
        type_config = ET.SubElement(root, 'PropertyGroup', Label='Configuration')
        ET.SubElement(type_config, 'ConfigurationType')
        ET.SubElement(type_config, 'CharacterSet').text = 'MultiByte'
        ET.SubElement(type_config, 'UseOfMfc').text = 'false'
        if self.platform_toolset:
            ET.SubElement(type_config, 'PlatformToolset').text = self.platform_toolset
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.props')
        direlem = ET.SubElement(root, 'PropertyGroup')
        fver = ET.SubElement(direlem, '_ProjectFileVersion')
        fver.text = self.project_file_version
        outdir = ET.SubElement(direlem, 'OutDir')
        outdir.text = '.\\'
        intdir = ET.SubElement(direlem, 'IntDir')
        intdir.text = target.get_id() + '\\'
        tname = ET.SubElement(direlem, 'TargetName')
        tname.text = target.name
        return root

    def gen_run_target_vcxproj(self, target, ofname, guid):
        root = self.create_basic_crap(target)
        action = ET.SubElement(root, 'ItemDefinitionGroup')
        customstep = ET.SubElement(action, 'PostBuildEvent')
        cmd_raw = [target.command] + target.args
        cmd = python_command + \
            [os.path.join(self.environment.get_script_dir(), 'commandrunner.py'),
             self.environment.get_build_dir(),
             self.environment.get_source_dir(),
             self.get_target_dir(target)] + self.environment.get_build_command()
        for i in cmd_raw:
            if isinstance(i, build.BuildTarget):
                cmd.append(os.path.join(self.environment.get_build_dir(), self.get_target_filename(i)))
            elif isinstance(i, dependencies.ExternalProgram):
                cmd += i.get_command()
            elif isinstance(i, File):
                relfname = i.rel_to_builddir(self.build_to_src)
                cmd.append(os.path.join(self.environment.get_build_dir(), relfname))
            else:
                cmd.append(i)
        cmd_templ = '''"%s" ''' * len(cmd)
        ET.SubElement(customstep, 'Command').text = cmd_templ % tuple(cmd)
        ET.SubElement(customstep, 'Message').text = 'Running custom command.'
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.targets')
        self._prettyprint_vcxproj_xml(ET.ElementTree(root), ofname)

    def gen_custom_target_vcxproj(self, target, ofname, guid):
        root = self.create_basic_crap(target)
        action = ET.SubElement(root, 'ItemDefinitionGroup')
        customstep = ET.SubElement(action, 'CustomBuildStep')
        # We need to always use absolute paths because our invocation is always
        # from the target dir, not the build root.
        target.absolute_paths = True
        (srcs, ofilenames, cmd) = self.eval_custom_target_command(target, True)
        depend_files = self.get_custom_target_depend_files(target, True)
        # Always use a wrapper because MSBuild eats random characters when
        # there are many arguments.
        tdir_abs = os.path.join(self.environment.get_build_dir(), self.get_target_dir(target))
        extra_bdeps = target.get_transitive_build_target_deps()
        extra_paths = self.determine_windows_extra_paths(target.command[0], extra_bdeps)
        exe_data = self.serialize_executable(target.name, target.command[0], cmd[1:],
                                             # All targets run from the target dir
                                             tdir_abs,
                                             extra_paths=extra_paths,
                                             capture=ofilenames[0] if target.capture else None)
        wrapper_cmd = self.environment.get_build_command() + ['--internal', 'exe', exe_data]
        ET.SubElement(customstep, 'Command').text = ' '.join(self.quote_arguments(wrapper_cmd))
        ET.SubElement(customstep, 'Outputs').text = ';'.join(ofilenames)
        ET.SubElement(customstep, 'Inputs').text = ';'.join([exe_data] + srcs + depend_files)
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.targets')
        self.generate_custom_generator_commands(target, root)
        self._prettyprint_vcxproj_xml(ET.ElementTree(root), ofname)

    @classmethod
    def lang_from_source_file(cls, src):
        ext = src.split('.')[-1]
        if ext in compilers.c_suffixes:
            return 'c'
        if ext in compilers.cpp_suffixes:
            return 'cpp'
        raise MesonException('Could not guess language from source file %s.' % src)

    def add_pch(self, inc_cl, proj_to_src_dir, pch_sources, source_file):
        if len(pch_sources) <= 1:
            # We only need per file precompiled headers if we have more than 1 language.
            return
        lang = Vs2010Backend.lang_from_source_file(source_file)
        header = os.path.join(proj_to_src_dir, pch_sources[lang][0])
        pch_file = ET.SubElement(inc_cl, 'PrecompiledHeaderFile')
        pch_file.text = header
        pch_include = ET.SubElement(inc_cl, 'ForcedIncludeFiles')
        pch_include.text = header + ';%(ForcedIncludeFiles)'
        pch_out = ET.SubElement(inc_cl, 'PrecompiledHeaderOutputFile')
        pch_out.text = '$(IntDir)$(TargetName)-%s.pch' % lang

    def is_argument_with_msbuild_xml_entry(self, entry):
        # Remove arguments that have a top level XML entry so
        # they are not used twice.
        # FIXME add args as needed.
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
        return '"{}"'.format(option)

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
            for lang, c in self.environment.coredata.compilers.items():
                if lang in ('c', 'cpp'):
                    return c
        raise MesonException('Could not find a C or C++ compiler. MSVC can only build C/C++ projects.')

    def _prettyprint_vcxproj_xml(self, tree, ofname):
        tree.write(ofname, encoding='utf-8', xml_declaration=True)
        # ElementTree can not do prettyprinting so do it manually
        doc = xml.dom.minidom.parse(ofname)
        with open(ofname, 'w', encoding='utf-8') as of:
            of.write(doc.toprettyxml())

    def gen_vcxproj(self, target, ofname, guid):
        mlog.debug('Generating vcxproj %s.' % target.name)
        entrypoint = 'WinMainCRTStartup'
        subsystem = 'Windows'
        if isinstance(target, build.Executable):
            conftype = 'Application'
            if not target.gui_app:
                subsystem = 'Console'
                entrypoint = 'mainCRTStartup'
        elif isinstance(target, build.StaticLibrary):
            conftype = 'StaticLibrary'
        elif isinstance(target, build.SharedLibrary):
            conftype = 'DynamicLibrary'
            entrypoint = '_DllMainCrtStartup'
        elif isinstance(target, build.CustomTarget):
            return self.gen_custom_target_vcxproj(target, ofname, guid)
        elif isinstance(target, build.RunTarget):
            return self.gen_run_target_vcxproj(target, ofname, guid)
        else:
            raise MesonException('Unknown target type for %s' % target.get_basename())
        # Prefix to use to access the build root from the vcxproj dir
        down = self.target_to_build_root(target)
        # Prefix to use to access the source tree's root from the vcxproj dir
        proj_to_src_root = os.path.join(down, self.build_to_src)
        # Prefix to use to access the source tree's subdir from the vcxproj dir
        proj_to_src_dir = os.path.join(proj_to_src_root, self.get_target_dir(target))
        (sources, headers, objects, languages) = self.split_sources(target.sources)
        if self.is_unity(target):
            sources = self.generate_unity_files(target, sources)
        compiler = self._get_cl_compiler(target)
        buildtype_args = compiler.get_buildtype_args(self.buildtype)
        buildtype_link_args = compiler.get_buildtype_linker_args(self.buildtype)
        vscrt_type = self.environment.coredata.base_options['b_vscrt']
        project_name = target.name
        target_name = target.name
        root = ET.Element('Project', {'DefaultTargets': "Build",
                                      'ToolsVersion': '4.0',
                                      'xmlns': 'http://schemas.microsoft.com/developer/msbuild/2003'})
        confitems = ET.SubElement(root, 'ItemGroup', {'Label': 'ProjectConfigurations'})
        prjconf = ET.SubElement(confitems, 'ProjectConfiguration',
                                {'Include': self.buildtype + '|' + self.platform})
        p = ET.SubElement(prjconf, 'Configuration')
        p.text = self.buildtype
        pl = ET.SubElement(prjconf, 'Platform')
        pl.text = self.platform
        # Globals
        globalgroup = ET.SubElement(root, 'PropertyGroup', Label='Globals')
        guidelem = ET.SubElement(globalgroup, 'ProjectGuid')
        guidelem.text = '{%s}' % guid
        kw = ET.SubElement(globalgroup, 'Keyword')
        kw.text = self.platform + 'Proj'
        ns = ET.SubElement(globalgroup, 'RootNamespace')
        ns.text = target_name
        p = ET.SubElement(globalgroup, 'Platform')
        p.text = self.platform
        pname = ET.SubElement(globalgroup, 'ProjectName')
        pname.text = project_name
        if self.windows_target_platform_version:
            ET.SubElement(globalgroup, 'WindowsTargetPlatformVersion').text = self.windows_target_platform_version
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.Default.props')
        # Start configuration
        type_config = ET.SubElement(root, 'PropertyGroup', Label='Configuration')
        ET.SubElement(type_config, 'ConfigurationType').text = conftype
        ET.SubElement(type_config, 'CharacterSet').text = 'MultiByte'
        if self.platform_toolset:
            ET.SubElement(type_config, 'PlatformToolset').text = self.platform_toolset
        try:
            use_lto = 'true' if self.environment.coredata.base_options['b_lto'].value else 'false'
        except KeyError:
            use_lto = 'false'
        ET.SubElement(type_config, 'WholeProgramOptimization').text = use_lto
        # Let VS auto-set the RTC level
        ET.SubElement(type_config, 'BasicRuntimeChecks').text = 'Default'
        o_flags = split_o_flags_args(buildtype_args)
        if '/Oi' in o_flags:
            ET.SubElement(type_config, 'IntrinsicFunctions').text = 'true'
        if '/Ob1' in o_flags:
            ET.SubElement(type_config, 'InlineFunctionExpansion').text = 'OnlyExplicitInline'
        elif '/Ob2' in o_flags:
            ET.SubElement(type_config, 'InlineFunctionExpansion').text = 'AnySuitable'
        # Size-preserving flags
        if '/Os' in o_flags:
            ET.SubElement(type_config, 'FavorSizeOrSpeed').text = 'Size'
        else:
            ET.SubElement(type_config, 'FavorSizeOrSpeed').text = 'Speed'
        # Incremental linking increases code size
        if '/INCREMENTAL:NO' in buildtype_link_args:
            ET.SubElement(type_config, 'LinkIncremental').text = 'false'
        # CRT type; debug or release
        if vscrt_type.value == 'from_buildtype':
            if self.buildtype == 'debug' or self.buildtype == 'debugoptimized':
                ET.SubElement(type_config, 'UseDebugLibraries').text = 'true'
                ET.SubElement(type_config, 'RuntimeLibrary').text = 'MultiThreadedDebugDLL'
            else:
                ET.SubElement(type_config, 'UseDebugLibraries').text = 'false'
                ET.SubElement(type_config, 'RuntimeLibrary').text = 'MultiThreaded'
        elif vscrt_type.value == 'mdd':
            ET.SubElement(type_config, 'UseDebugLibraries').text = 'true'
            ET.SubElement(type_config, 'RuntimeLibrary').text = 'MultiThreadedDebugDLL'
        elif vscrt_type.value == 'mt':
            # FIXME, wrong
            ET.SubElement(type_config, 'UseDebugLibraries').text = 'false'
            ET.SubElement(type_config, 'RuntimeLibrary').text = 'MultiThreaded'
        elif vscrt_type.value == 'mtd':
            # FIXME, wrong
            ET.SubElement(type_config, 'UseDebugLibraries').text = 'true'
            ET.SubElement(type_config, 'RuntimeLibrary').text = 'MultiThreadedDebug'
        else:
            ET.SubElement(type_config, 'UseDebugLibraries').text = 'false'
            ET.SubElement(type_config, 'RuntimeLibrary').text = 'MultiThreadedDLL'
        # Debug format
        if '/ZI' in buildtype_args:
            ET.SubElement(type_config, 'DebugInformationFormat').text = 'EditAndContinue'
        elif '/Zi' in buildtype_args:
            ET.SubElement(type_config, 'DebugInformationFormat').text = 'ProgramDatabase'
        elif '/Z7' in buildtype_args:
            ET.SubElement(type_config, 'DebugInformationFormat').text = 'OldStyle'
        # Runtime checks
        if '/RTC1' in buildtype_args:
            ET.SubElement(type_config, 'BasicRuntimeChecks').text = 'EnableFastChecks'
        elif '/RTCu' in buildtype_args:
            ET.SubElement(type_config, 'BasicRuntimeChecks').text = 'UninitializedLocalUsageCheck'
        elif '/RTCs' in buildtype_args:
            ET.SubElement(type_config, 'BasicRuntimeChecks').text = 'StackFrameRuntimeCheck'
        # Optimization flags
        if '/Ox' in o_flags:
            ET.SubElement(type_config, 'Optimization').text = 'Full'
        elif '/O2' in o_flags:
            ET.SubElement(type_config, 'Optimization').text = 'MaxSpeed'
        elif '/O1' in o_flags:
            ET.SubElement(type_config, 'Optimization').text = 'MinSpace'
        elif '/Od' in o_flags:
            ET.SubElement(type_config, 'Optimization').text = 'Disabled'
        # End configuration
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.props')
        generated_files, custom_target_output_files, generated_files_include_dirs = self.generate_custom_generator_commands(target, root)
        (gen_src, gen_hdrs, gen_objs, gen_langs) = self.split_sources(generated_files)
        (custom_src, custom_hdrs, custom_objs, custom_langs) = self.split_sources(custom_target_output_files)
        gen_src += custom_src
        gen_hdrs += custom_hdrs
        gen_langs += custom_langs
        # Project information
        direlem = ET.SubElement(root, 'PropertyGroup')
        fver = ET.SubElement(direlem, '_ProjectFileVersion')
        fver.text = self.project_file_version
        outdir = ET.SubElement(direlem, 'OutDir')
        outdir.text = '.\\'
        intdir = ET.SubElement(direlem, 'IntDir')
        intdir.text = target.get_id() + '\\'
        tfilename = os.path.splitext(target.get_filename())
        ET.SubElement(direlem, 'TargetName').text = tfilename[0]
        ET.SubElement(direlem, 'TargetExt').text = tfilename[1]

        # Build information
        compiles = ET.SubElement(root, 'ItemDefinitionGroup')
        clconf = ET.SubElement(compiles, 'ClCompile')
        # Arguments, include dirs, defines for all files in the current target
        target_args = []
        target_defines = []
        target_inc_dirs = []
        # Arguments, include dirs, defines passed to individual files in
        # a target; perhaps because the args are language-specific
        #
        # file_args is also later split out into defines and include_dirs in
        # case someone passed those in there
        file_args = dict((lang, CompilerArgs(comp)) for lang, comp in target.compilers.items())
        file_defines = dict((lang, []) for lang in target.compilers)
        file_inc_dirs = dict((lang, []) for lang in target.compilers)
        # The order in which these compile args are added must match
        # generate_single_compile() and generate_basic_compiler_args()
        for l, comp in target.compilers.items():
            if l in file_args:
                file_args[l] += compilers.get_base_compile_args(self.get_base_options_for_target(target), comp)
                file_args[l] += comp.get_option_compile_args(self.environment.coredata.compiler_options)

        # Add compile args added using add_project_arguments()
        for l, args in self.build.projects_args.get(target.subproject, {}).items():
            if l in file_args:
                file_args[l] += args
        # Add compile args added using add_global_arguments()
        # These override per-project arguments
        for l, args in self.build.global_args.items():
            if l in file_args:
                file_args[l] += args
        if not target.is_cross:
            # Compile args added from the env: CFLAGS/CXXFLAGS, etc. We want these
            # to override all the defaults, but not the per-target compile args.
            for key, opt in self.environment.coredata.compiler_options.items():
                l, suffix = key.split('_', 1)
                if suffix == 'args' and l in file_args:
                    file_args[l] += opt.value
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
                    args.append('-I' + self.relpath(curdir, target.subdir)) # build dir
                    args.append('-I' + os.path.join(proj_to_src_root, curdir)) # src dir
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
                t_inc_dirs += ['.']
            if target.implicit_include_directories:
                t_inc_dirs += [proj_to_src_dir]
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
                    if define in file_defines[l]:
                        file_defines[l].remove(define)
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

        # Split compile args needed to find external dependencies
        # Link args are added while generating the link command
        for d in reversed(target.get_external_deps()):
            # Cflags required by external deps might have UNIX-specific flags,
            # so filter them out if needed
            if isinstance(d, dependencies.OpenMPDependency):
                d_compile_args = compiler.openmp_flags()
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
        if len(target_args) > 0:
            target_args.append('%(AdditionalOptions)')
            ET.SubElement(clconf, "AdditionalOptions").text = ' '.join(target_args)

        target_inc_dirs.append('%(AdditionalIncludeDirectories)')
        ET.SubElement(clconf, 'AdditionalIncludeDirectories').text = ';'.join(target_inc_dirs)
        target_defines.append('%(PreprocessorDefinitions)')
        ET.SubElement(clconf, 'PreprocessorDefinitions').text = ';'.join(target_defines)
        ET.SubElement(clconf, 'MinimalRebuild').text = 'true'
        ET.SubElement(clconf, 'FunctionLevelLinking').text = 'true'
        pch_node = ET.SubElement(clconf, 'PrecompiledHeader')
        # Warning level
        warning_level = self.get_option_for_target('warning_level', target)
        ET.SubElement(clconf, 'WarningLevel').text = 'Level' + str(1 + int(warning_level))
        if self.get_option_for_target('werror', target):
            ET.SubElement(clconf, 'TreatWarningAsError').text = 'true'
        # Note: SuppressStartupBanner is /NOLOGO and is 'true' by default
        pch_sources = {}
        for lang in ['c', 'cpp']:
            pch = target.get_pch(lang)
            if not pch:
                continue
            pch_node.text = 'Use'
            if compiler.id == 'msvc':
                if len(pch) != 2:
                    raise MesonException('MSVC requires one header and one source to produce precompiled headers.')
                pch_sources[lang] = [pch[0], pch[1], lang]
            else:
                # I don't know whether its relevant but let's handle other compilers
                # used with a vs backend
                pch_sources[lang] = [pch[0], None, lang]
        if len(pch_sources) == 1:
            # If there is only 1 language with precompiled headers, we can use it for the entire project, which
            # is cleaner than specifying it for each source file.
            pch_source = list(pch_sources.values())[0]
            header = os.path.join(proj_to_src_dir, pch_source[0])
            pch_file = ET.SubElement(clconf, 'PrecompiledHeaderFile')
            pch_file.text = header
            pch_include = ET.SubElement(clconf, 'ForcedIncludeFiles')
            pch_include.text = header + ';%(ForcedIncludeFiles)'
            pch_out = ET.SubElement(clconf, 'PrecompiledHeaderOutputFile')
            pch_out.text = '$(IntDir)$(TargetName)-%s.pch' % pch_source[2]

        resourcecompile = ET.SubElement(compiles, 'ResourceCompile')
        ET.SubElement(resourcecompile, 'PreprocessorDefinitions')

        # Linker options
        link = ET.SubElement(compiles, 'Link')
        extra_link_args = CompilerArgs(compiler)
        # FIXME: Can these buildtype linker args be added as tags in the
        # vcxproj file (similar to buildtype compiler args) instead of in
        # AdditionalOptions?
        extra_link_args += compiler.get_buildtype_linker_args(self.buildtype)
        # Generate Debug info
        if self.buildtype.startswith('debug'):
            self.generate_debug_information(link)
        if not isinstance(target, build.StaticLibrary):
            if isinstance(target, build.SharedModule):
                options = self.environment.coredata.base_options
                extra_link_args += compiler.get_std_shared_module_link_args(options)
            # Add link args added using add_project_link_arguments()
            extra_link_args += self.build.get_project_link_args(compiler, target.subproject, target.is_cross)
            # Add link args added using add_global_link_arguments()
            # These override per-project link arguments
            extra_link_args += self.build.get_global_link_args(compiler, target.is_cross)
            if not target.is_cross:
                # Link args added from the env: LDFLAGS. We want these to
                # override all the defaults but not the per-target link args.
                extra_link_args += self.environment.coredata.get_external_link_args(compiler.get_language())
            # Only non-static built targets need link args and link dependencies
            extra_link_args += target.link_args
            # External deps must be last because target link libraries may depend on them.
            for dep in target.get_external_deps():
                # Extend without reordering or de-dup to preserve `-L -l` sets
                # https://github.com/mesonbuild/meson/issues/1718
                if isinstance(dep, dependencies.OpenMPDependency):
                    extra_link_args.extend_direct(compiler.openmp_flags())
                else:
                    extra_link_args.extend_direct(dep.get_link_args())
            for d in target.get_dependencies():
                if isinstance(d, build.StaticLibrary):
                    for dep in d.get_external_deps():
                        if isinstance(dep, dependencies.OpenMPDependency):
                            extra_link_args.extend_direct(compiler.openmp_flags())
                        else:
                            extra_link_args.extend_direct(dep.get_link_args())
        # Add link args for c_* or cpp_* build options. Currently this only
        # adds c_winlibs and cpp_winlibs when building for Windows. This needs
        # to be after all internal and external libraries so that unresolved
        # symbols from those can be found here. This is needed when the
        # *_winlibs that we want to link to are static mingw64 libraries.
        extra_link_args += compiler.get_option_link_args(self.environment.coredata.compiler_options)
        (additional_libpaths, additional_links, extra_link_args) = self.split_link_args(extra_link_args.to_native())

        # Add more libraries to be linked if needed
        for t in target.get_dependencies():
            lobj = self.build.targets[t.get_id()]
            linkname = os.path.join(down, self.get_target_filename_for_linking(lobj))
            if t in target.link_whole_targets:
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
                self.add_project_reference(root, tvcxproj, tid)
            else:
                # Other libraries go into AdditionalDependencies
                if linkname not in additional_links:
                    additional_links.append(linkname)
        for lib in self.get_custom_target_provided_libraries(target):
            additional_links.append(self.relpath(lib, self.get_target_dir(target)))
        additional_objects = []
        for o in self.flatten_object_list(target, down):
            assert(isinstance(o, str))
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
        ofile.text = '$(OutDir)%s' % target.get_filename()
        subsys = ET.SubElement(link, 'SubSystem')
        subsys.text = subsystem
        if (isinstance(target, build.SharedLibrary) or isinstance(target, build.Executable)) and target.get_import_filename():
            # DLLs built with MSVC always have an import library except when
            # they're data-only DLLs, but we don't support those yet.
            ET.SubElement(link, 'ImportLibrary').text = target.get_import_filename()
        if isinstance(target, build.SharedLibrary):
            # Add module definitions file, if provided
            if target.vs_module_defs:
                relpath = os.path.join(down, target.vs_module_defs.rel_to_builddir(self.build_to_src))
                ET.SubElement(link, 'ModuleDefinitionFile').text = relpath
        if '/ZI' in buildtype_args or '/Zi' in buildtype_args:
            pdb = ET.SubElement(link, 'ProgramDataBaseFileName')
            pdb.text = '$(OutDir}%s.pdb' % target_name
        if isinstance(target, build.Executable):
            ET.SubElement(link, 'EntryPointSymbol').text = entrypoint
        targetmachine = ET.SubElement(link, 'TargetMachine')
        targetplatform = self.platform.lower()
        if targetplatform == 'win32':
            targetmachine.text = 'MachineX86'
        elif targetplatform == 'x64':
            targetmachine.text = 'MachineX64'
        elif targetplatform == 'arm':
            targetmachine.text = 'MachineARM'
        else:
            raise MesonException('Unsupported Visual Studio target machine: ' + targetmachine)

        extra_files = target.extra_files
        if len(headers) + len(gen_hdrs) + len(extra_files) > 0:
            inc_hdrs = ET.SubElement(root, 'ItemGroup')
            for h in headers:
                relpath = os.path.join(down, h.rel_to_builddir(self.build_to_src))
                ET.SubElement(inc_hdrs, 'CLInclude', Include=relpath)
            for h in gen_hdrs:
                ET.SubElement(inc_hdrs, 'CLInclude', Include=h)
            for h in target.extra_files:
                relpath = os.path.join(down, h.rel_to_builddir(self.build_to_src))
                ET.SubElement(inc_hdrs, 'CLInclude', Include=relpath)

        if len(sources) + len(gen_src) + len(pch_sources) > 0:
            inc_src = ET.SubElement(root, 'ItemGroup')
            for s in sources:
                relpath = os.path.join(down, s.rel_to_builddir(self.build_to_src))
                inc_cl = ET.SubElement(inc_src, 'CLCompile', Include=relpath)
                lang = Vs2010Backend.lang_from_source_file(s)
                self.add_pch(inc_cl, proj_to_src_dir, pch_sources, s)
                self.add_additional_options(lang, inc_cl, file_args)
                self.add_preprocessor_defines(lang, inc_cl, file_defines)
                self.add_include_dirs(lang, inc_cl, file_inc_dirs)
                ET.SubElement(inc_cl, 'ObjectFileName').text = "$(IntDir)" + self.object_filename_from_source(target, s)
            for s in gen_src:
                inc_cl = ET.SubElement(inc_src, 'CLCompile', Include=s)
                lang = Vs2010Backend.lang_from_source_file(s)
                self.add_pch(inc_cl, proj_to_src_dir, pch_sources, s)
                self.add_additional_options(lang, inc_cl, file_args)
                self.add_preprocessor_defines(lang, inc_cl, file_defines)
                self.add_include_dirs(lang, inc_cl, file_inc_dirs)
            for lang in pch_sources:
                header, impl, suffix = pch_sources[lang]
                if impl:
                    relpath = os.path.join(proj_to_src_dir, impl)
                    inc_cl = ET.SubElement(inc_src, 'CLCompile', Include=relpath)
                    pch = ET.SubElement(inc_cl, 'PrecompiledHeader')
                    pch.text = 'Create'
                    pch_out = ET.SubElement(inc_cl, 'PrecompiledHeaderOutputFile')
                    pch_out.text = '$(IntDir)$(TargetName)-%s.pch' % suffix
                    pch_file = ET.SubElement(inc_cl, 'PrecompiledHeaderFile')
                    # MSBuild searches for the header relative from the implementation, so we have to use
                    # just the file name instead of the relative path to the file.
                    pch_file.text = os.path.basename(header)
                    self.add_additional_options(lang, inc_cl, file_args)
                    self.add_preprocessor_defines(lang, inc_cl, file_defines)
                    self.add_include_dirs(lang, inc_cl, file_inc_dirs)

        if self.has_objects(objects, additional_objects, gen_objs):
            inc_objs = ET.SubElement(root, 'ItemGroup')
            for s in objects:
                relpath = os.path.join(down, s.rel_to_builddir(self.build_to_src))
                ET.SubElement(inc_objs, 'Object', Include=relpath)
            for s in additional_objects:
                ET.SubElement(inc_objs, 'Object', Include=s)
            self.add_generated_objects(inc_objs, gen_objs)

        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.targets')
        # Reference the regen target.
        regen_vcxproj = os.path.join(self.environment.get_build_dir(), 'REGEN.vcxproj')
        self.add_project_reference(root, regen_vcxproj, self.environment.coredata.regen_guid)
        self._prettyprint_vcxproj_xml(ET.ElementTree(root), ofname)

    def gen_regenproj(self, project_name, ofname):
        root = ET.Element('Project', {'DefaultTargets': 'Build',
                                      'ToolsVersion': '4.0',
                                      'xmlns': 'http://schemas.microsoft.com/developer/msbuild/2003'})
        confitems = ET.SubElement(root, 'ItemGroup', {'Label': 'ProjectConfigurations'})
        prjconf = ET.SubElement(confitems, 'ProjectConfiguration',
                                {'Include': self.buildtype + '|' + self.platform})
        p = ET.SubElement(prjconf, 'Configuration')
        p.text = self.buildtype
        pl = ET.SubElement(prjconf, 'Platform')
        pl.text = self.platform
        globalgroup = ET.SubElement(root, 'PropertyGroup', Label='Globals')
        guidelem = ET.SubElement(globalgroup, 'ProjectGuid')
        guidelem.text = '{%s}' % self.environment.coredata.test_guid
        kw = ET.SubElement(globalgroup, 'Keyword')
        kw.text = self.platform + 'Proj'
        p = ET.SubElement(globalgroup, 'Platform')
        p.text = self.platform
        pname = ET.SubElement(globalgroup, 'ProjectName')
        pname.text = project_name
        if self.windows_target_platform_version:
            ET.SubElement(globalgroup, 'WindowsTargetPlatformVersion').text = self.windows_target_platform_version
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.Default.props')
        type_config = ET.SubElement(root, 'PropertyGroup', Label='Configuration')
        ET.SubElement(type_config, 'ConfigurationType').text = "Utility"
        ET.SubElement(type_config, 'CharacterSet').text = 'MultiByte'
        ET.SubElement(type_config, 'UseOfMfc').text = 'false'
        if self.platform_toolset:
            ET.SubElement(type_config, 'PlatformToolset').text = self.platform_toolset
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.props')
        direlem = ET.SubElement(root, 'PropertyGroup')
        fver = ET.SubElement(direlem, '_ProjectFileVersion')
        fver.text = self.project_file_version
        outdir = ET.SubElement(direlem, 'OutDir')
        outdir.text = '.\\'
        intdir = ET.SubElement(direlem, 'IntDir')
        intdir.text = 'regen-temp\\'
        tname = ET.SubElement(direlem, 'TargetName')
        tname.text = project_name

        action = ET.SubElement(root, 'ItemDefinitionGroup')
        midl = ET.SubElement(action, 'Midl')
        ET.SubElement(midl, "AdditionalIncludeDirectories").text = '%(AdditionalIncludeDirectories)'
        ET.SubElement(midl, "OutputDirectory").text = '$(IntDir)'
        ET.SubElement(midl, 'HeaderFileName').text = '%(Filename).h'
        ET.SubElement(midl, 'TypeLibraryName').text = '%(Filename).tlb'
        ET.SubElement(midl, 'InterfaceIdentifierFilename').text = '%(Filename)_i.c'
        ET.SubElement(midl, 'ProxyFileName').text = '%(Filename)_p.c'
        regen_command = self.environment.get_build_command() + ['--internal', 'regencheck']
        private_dir = self.environment.get_scratch_dir()
        cmd_templ = '''setlocal
"%s" "%s"
if %%errorlevel%% neq 0 goto :cmEnd
:cmEnd
endlocal & call :cmErrorLevel %%errorlevel%% & goto :cmDone
:cmErrorLevel
exit /b %%1
:cmDone
if %%errorlevel%% neq 0 goto :VCEnd'''
        igroup = ET.SubElement(root, 'ItemGroup')
        rulefile = os.path.join(self.environment.get_scratch_dir(), 'regen.rule')
        if not os.path.exists(rulefile):
            with open(rulefile, 'w', encoding='utf-8') as f:
                f.write("# Meson regen file.")
        custombuild = ET.SubElement(igroup, 'CustomBuild', Include=rulefile)
        message = ET.SubElement(custombuild, 'Message')
        message.text = 'Checking whether solution needs to be regenerated.'
        ET.SubElement(custombuild, 'Command').text = cmd_templ % \
            ('" "'.join(regen_command), private_dir)
        ET.SubElement(custombuild, 'Outputs').text = Vs2010Backend.get_regen_stampfile(self.environment.get_build_dir())
        deps = self.get_regen_filelist()
        ET.SubElement(custombuild, 'AdditionalInputs').text = ';'.join(deps)
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.targets')
        ET.SubElement(root, 'ImportGroup', Label='ExtensionTargets')
        self._prettyprint_vcxproj_xml(ET.ElementTree(root), ofname)

    def gen_testproj(self, target_name, ofname):
        project_name = target_name
        root = ET.Element('Project', {'DefaultTargets': "Build",
                                      'ToolsVersion': '4.0',
                                      'xmlns': 'http://schemas.microsoft.com/developer/msbuild/2003'})
        confitems = ET.SubElement(root, 'ItemGroup', {'Label': 'ProjectConfigurations'})
        prjconf = ET.SubElement(confitems, 'ProjectConfiguration',
                                {'Include': self.buildtype + '|' + self.platform})
        p = ET.SubElement(prjconf, 'Configuration')
        p.text = self.buildtype
        pl = ET.SubElement(prjconf, 'Platform')
        pl.text = self.platform
        globalgroup = ET.SubElement(root, 'PropertyGroup', Label='Globals')
        guidelem = ET.SubElement(globalgroup, 'ProjectGuid')
        guidelem.text = '{%s}' % self.environment.coredata.test_guid
        kw = ET.SubElement(globalgroup, 'Keyword')
        kw.text = self.platform + 'Proj'
        p = ET.SubElement(globalgroup, 'Platform')
        p.text = self.platform
        pname = ET.SubElement(globalgroup, 'ProjectName')
        pname.text = project_name
        if self.windows_target_platform_version:
            ET.SubElement(globalgroup, 'WindowsTargetPlatformVersion').text = self.windows_target_platform_version
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.Default.props')
        type_config = ET.SubElement(root, 'PropertyGroup', Label='Configuration')
        ET.SubElement(type_config, 'ConfigurationType')
        ET.SubElement(type_config, 'CharacterSet').text = 'MultiByte'
        ET.SubElement(type_config, 'UseOfMfc').text = 'false'
        if self.platform_toolset:
            ET.SubElement(type_config, 'PlatformToolset').text = self.platform_toolset
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.props')
        direlem = ET.SubElement(root, 'PropertyGroup')
        fver = ET.SubElement(direlem, '_ProjectFileVersion')
        fver.text = self.project_file_version
        outdir = ET.SubElement(direlem, 'OutDir')
        outdir.text = '.\\'
        intdir = ET.SubElement(direlem, 'IntDir')
        intdir.text = 'test-temp\\'
        tname = ET.SubElement(direlem, 'TargetName')
        tname.text = target_name

        action = ET.SubElement(root, 'ItemDefinitionGroup')
        midl = ET.SubElement(action, 'Midl')
        ET.SubElement(midl, "AdditionalIncludeDirectories").text = '%(AdditionalIncludeDirectories)'
        ET.SubElement(midl, "OutputDirectory").text = '$(IntDir)'
        ET.SubElement(midl, 'HeaderFileName').text = '%(Filename).h'
        ET.SubElement(midl, 'TypeLibraryName').text = '%(Filename).tlb'
        ET.SubElement(midl, 'InterfaceIdentifierFilename').text = '%(Filename)_i.c'
        ET.SubElement(midl, 'ProxyFileName').text = '%(Filename)_p.c'
        postbuild = ET.SubElement(action, 'PostBuildEvent')
        ET.SubElement(postbuild, 'Message')
        # FIXME: No benchmarks?
        test_command = self.environment.get_build_command() + ['test', '--no-rebuild']
        if not self.environment.coredata.get_builtin_option('stdsplit'):
            test_command += ['--no-stdsplit']
        if self.environment.coredata.get_builtin_option('errorlogs'):
            test_command += ['--print-errorlogs']
        cmd_templ = '''setlocal
"%s"
if %%errorlevel%% neq 0 goto :cmEnd
:cmEnd
endlocal & call :cmErrorLevel %%errorlevel%% & goto :cmDone
:cmErrorLevel
exit /b %%1
:cmDone
if %%errorlevel%% neq 0 goto :VCEnd'''
        self.serialize_tests()
        ET.SubElement(postbuild, 'Command').text =\
            cmd_templ % ('" "'.join(test_command))
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.targets')
        self._prettyprint_vcxproj_xml(ET.ElementTree(root), ofname)

    def gen_installproj(self, target_name, ofname):
        self.create_install_data_files()
        project_name = target_name
        root = ET.Element('Project', {'DefaultTargets': "Build",
                                      'ToolsVersion': '4.0',
                                      'xmlns': 'http://schemas.microsoft.com/developer/msbuild/2003'})
        confitems = ET.SubElement(root, 'ItemGroup', {'Label': 'ProjectConfigurations'})
        prjconf = ET.SubElement(confitems, 'ProjectConfiguration',
                                {'Include': self.buildtype + '|' + self.platform})
        p = ET.SubElement(prjconf, 'Configuration')
        p.text = self.buildtype
        pl = ET.SubElement(prjconf, 'Platform')
        pl.text = self.platform
        globalgroup = ET.SubElement(root, 'PropertyGroup', Label='Globals')
        guidelem = ET.SubElement(globalgroup, 'ProjectGuid')
        guidelem.text = '{%s}' % self.environment.coredata.install_guid
        kw = ET.SubElement(globalgroup, 'Keyword')
        kw.text = self.platform + 'Proj'
        p = ET.SubElement(globalgroup, 'Platform')
        p.text = self.platform
        pname = ET.SubElement(globalgroup, 'ProjectName')
        pname.text = project_name
        if self.windows_target_platform_version:
            ET.SubElement(globalgroup, 'WindowsTargetPlatformVersion').text = self.windows_target_platform_version
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.Default.props')
        type_config = ET.SubElement(root, 'PropertyGroup', Label='Configuration')
        ET.SubElement(type_config, 'ConfigurationType')
        ET.SubElement(type_config, 'CharacterSet').text = 'MultiByte'
        ET.SubElement(type_config, 'UseOfMfc').text = 'false'
        if self.platform_toolset:
            ET.SubElement(type_config, 'PlatformToolset').text = self.platform_toolset
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.props')
        direlem = ET.SubElement(root, 'PropertyGroup')
        fver = ET.SubElement(direlem, '_ProjectFileVersion')
        fver.text = self.project_file_version
        outdir = ET.SubElement(direlem, 'OutDir')
        outdir.text = '.\\'
        intdir = ET.SubElement(direlem, 'IntDir')
        intdir.text = 'install-temp\\'
        tname = ET.SubElement(direlem, 'TargetName')
        tname.text = target_name

        action = ET.SubElement(root, 'ItemDefinitionGroup')
        midl = ET.SubElement(action, 'Midl')
        ET.SubElement(midl, "AdditionalIncludeDirectories").text = '%(AdditionalIncludeDirectories)'
        ET.SubElement(midl, "OutputDirectory").text = '$(IntDir)'
        ET.SubElement(midl, 'HeaderFileName').text = '%(Filename).h'
        ET.SubElement(midl, 'TypeLibraryName').text = '%(Filename).tlb'
        ET.SubElement(midl, 'InterfaceIdentifierFilename').text = '%(Filename)_i.c'
        ET.SubElement(midl, 'ProxyFileName').text = '%(Filename)_p.c'
        postbuild = ET.SubElement(action, 'PostBuildEvent')
        ET.SubElement(postbuild, 'Message')
        # FIXME: No benchmarks?
        test_command = self.environment.get_build_command() + ['install', '--no-rebuild']
        cmd_templ = '''setlocal
"%s"
if %%errorlevel%% neq 0 goto :cmEnd
:cmEnd
endlocal & call :cmErrorLevel %%errorlevel%% & goto :cmDone
:cmErrorLevel
exit /b %%1
:cmDone
if %%errorlevel%% neq 0 goto :VCEnd'''
        ET.SubElement(postbuild, 'Command').text =\
            cmd_templ % ('" "'.join(test_command))
        ET.SubElement(root, 'Import', Project='$(VCTargetsPath)\Microsoft.Cpp.targets')
        self._prettyprint_vcxproj_xml(ET.ElementTree(root), ofname)

    def generate_debug_information(self, link):
        # valid values for vs2015 is 'false', 'true', 'DebugFastLink'
        ET.SubElement(link, 'GenerateDebugInformation').text = 'true'
