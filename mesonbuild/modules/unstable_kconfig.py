# Copyright 2017, 2019 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from . import ExtensionModule

from .. import mesonlib
from ..mesonlib import typeslistify
from ..interpreterbase import FeatureNew, noKwargs
from ..interpreter import InvalidCode

import os

class KconfigModule(ExtensionModule):

    @FeatureNew('Kconfig Module', '0.51.0')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.snippets.add('load')

    def _load_file(self, path_to_config):
        result = dict()
        try:
            with open(path_to_config) as f:
                for line in f:
                    if '#' in line:
                        comment_idx = line.index('#')
                        line = line[:comment_idx]
                    line = line.strip()
                    try:
                        name, val = line.split('=', 1)
                    except ValueError:
                        continue
                    val = val.strip()
                    # Unquote strings
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                    result[name.strip()] = val
        except IOError as e:
            raise mesonlib.MesonException('Failed to load {}: {}'.format(path_to_config, e))

        return result

    @noKwargs
    def load(self, interpreter, state, args, kwargs):
        sources = typeslistify(args, (str, mesonlib.File))
        if len(sources) != 1:
            raise InvalidCode('load takes only one file input.')

        s = sources[0]
        is_built = False
        if isinstance(s, mesonlib.File):
            if s.is_built:
                FeatureNew('kconfig.load() of built files', '0.52.0').use(state.subproject)
                is_built = True
            s = s.absolute_path(interpreter.environment.source_dir, interpreter.environment.build_dir)
        else:
            s = os.path.join(interpreter.environment.source_dir, s)

        if s not in interpreter.build_def_files and not is_built:
            interpreter.build_def_files.append(s)

        return self._load_file(s)


def initialize(*args, **kwargs):
    return KconfigModule(*args, **kwargs)
