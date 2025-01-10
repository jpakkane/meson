# Copyright 2019 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import os, re, sys

from ..mesonlib import Popen_safe

def isenvset(cmd):
    return bool(re.fullmatch('^[a-zA-Z_][a-zA-Z0-9_]*=.*$', cmd))

def run(args):
    argp = argparse.ArgumentParser()
    argp.add_argument('--MD', action='store_true',
                      help='See GCC documentation for -MD')
    argp.add_argument('--MMD', action='store_true',
                      help='See GCC documentation for -MMD')
    argp.add_argument('--MQ', type=str,
                      help='See GCC documentation for -MQ target')
    argp.add_argument('--MF', type=str,
                      help='See GCC documentation for -MF file')
    argp.add_argument('args', nargs=argparse.REMAINDER)
    args = argp.parse_args(args[1:])

    finalcmd = args.args
    if args.MD or args.MMD or args.MQ is not None or args.MF is not None:

        # We run NVCC with a --dryrun flag that causes it to print out what NVCC
        # would have done, rather than doing it.
        # We also contaminate the command-line with findable arguments.

        COMPILEHACK = '---MESONCOMPILEFINDMEHACK'
        LINKHACK = '---MESONLINKFINDMEHACK'
        dryruncmd = finalcmd[:1] + [
            '-dryrun',
            '-Xcompiler', COMPILEHACK,
            '-Xlinker', LINKHACK,
        ] + finalcmd[1:]

        pc, stdo, stde = Popen_safe(dryruncmd)
        if pc.returncode != 0:
            sys.stdout.write(stdo)
            sys.stderr.write(stde)
            return pc.returncode

        # At this point, stde is essentially the contents of a script that should
        # be executed in the shell to perform what nvcc performs.
        #
        # Oddly, however, every line is prefixed with '#$ ', and the first several
        # lines appear to only be set-environment-variable commands.

        cmds = stde.split('\n')
        cmds = [re.sub('^#\\$ ', '', cmd) for cmd in cmds]
        cmds = [cmd for cmd in cmds if cmd]
        envs = dict([cmd.split('=', 1) for cmd in cmds if isenvset(cmd)])
        cmdx = [cmd for cmd in cmds if not isenvset(cmd)]
        cmdf = []

        # We now attempt to parse out important commands, edit them with the
        # extra flags, and add them to the cmdf list.
        for cmd in cmdx:
            if re.search(r'^cicc|^cudafe|^ptxas|^fatbinary|^nvlink|^rm', cmd):
                continue
            if COMPILEHACK not in cmd:
                continue
            if LINKHACK in cmd:
                continue

            # There are several reasons why the compiler might be invoked:
            #
            #    1) To preprocess the file for a given GPU architecture. This
            #       is what we're interested in.
            #    2) To preprocess the file for the host. This is what we're
            #       interested in.
            #    3) To compile filtered C or C++ code to an object file. This
            #       is not helpful in telling us the preprocessor dependencies
            #       we'll have, so we eliminate that.
            cmdslice = cmd[:cmd.find(COMPILEHACK)]
            if ' -c ' in cmdslice:
                continue
            if ' -E ' not in cmdslice:
                continue
            cmdf.append(cmd)

        # We now invoke each of the filtered, modified commands.
        for i, cmd in enumerate(cmdf):
            # For each selected compiler preprocessor command, remove the ugly
            # hack and replace it with the correct extra arguments.
            depargs = []
            if args.MMD:
                depargs += ['-MMD']
            if args.MD:
                depargs += ['-MD']
            if args.MQ is not None:
                depargs += ['-MQ', args.MQ]
            if args.MF is not None:
                depargs += ['-MF', args.MF + '.' + str(i)]
            depargs = ' '.join(depargs)
            cmd = re.sub(' ---MESONCOMPILEFINDMEHACK', depargs, cmd)

            pc, stdo, stde = Popen_safe(cmd, shell=True, env=envs)
            if pc.returncode != 0:
                sys.stdout.write(stdo)
                sys.stderr.write(stde)
                return pc.returncode

        # Lastly, if the -MF flag was specified, we know where to find the
        # dependency files, so we can read them back and recombine them.
        if args.MF is not None:
            depfiles = [args.MF + '.' + str(i) for i in range(len(cmdf))]
            depstrs = []
            for depfile in depfiles:
                with open(depfile, 'r') as f:
                    depstr = f.read()
                    depstr = re.sub('\\s+\\\\\\s*\\n\\s*', ' ', depstr, flags=re.A)
                    depstrs.append(depstr)
                os.unlink(depfile)

            # BUG: Should lex the quoted target the same way Make does!
            quotedtarget = depstrs[0].split(':', 1)[0]
            deplist = []
            for depstr in depstrs:
                # BUG: Should lex the dependencies the same way Make does!
                deplist += depstr.split(':', 1)[1].strip().split(' ')
            deplist = sorted(list(set(deplist)))

            # Write out the actual, fused dependency file.
            depstr = quotedtarget + ': ' + ' \\\n  '.join(deplist)
            with open(args.MF, 'w') as f:
                f.write(depstr)

    # Now, execute what were were supposed to execute in the first place.
    return os.execvp(finalcmd[0], finalcmd)

if __name__ == '__main__':
    sys.exit(run(sys.argv))
