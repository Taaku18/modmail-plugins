"""
As substantial work has been placed—a few months of development—to make this fully featured music bot free for public use, please refrain from discrediting author or falsely claiming this open source work.

BSD 3-Clause License

Copyright (c) 2021, taku#3343 (Discord)
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""

import re as _re

from .audiotrack import *
from .exceptions import *
from ._player import Player
from .queue import Queue
from .spotify import *
from .lyrics import *
from . import utils
from .utils import *

URL_REGEX = _re.compile(r'(https?://(?:www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.'
                        r'[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_+.~#?&/=]*))', _re.I)
YOUTUBE_REGEX = _re.compile(r'youtube\.com|youtu\.be', _re.I)
IDENTIFIER_REGEX = _re.compile(r'^(scsearch:|ytsearch:|spotify:)')
DURATION_REGEX = _re.compile(r"(?:(?P<hours>\d+(?:\.\d+)?)h)?"
                             r"(?:(?P<minutes>\d+(?:\.\d+)?)m)?"
                             r"(?:(?P<seconds>\d+(?:\.\d+)?)s)?",
                             _re.I)
