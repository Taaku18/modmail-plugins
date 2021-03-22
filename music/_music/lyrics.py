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

import asyncio
import os
import typing
from concurrent import futures

from lyricsgenius import Genius
from lyricsgenius.types.song import Song

from .utils import cache

__all__ = ["Lyrics"]


class Lyrics:
    def __init__(self, GENIUS_TOKEN):
        self._executor = futures.ThreadPoolExecutor(max_workers=3)
        self.GENIUS_TOKEN = GENIUS_TOKEN

    async def test_token(self) -> bool:
        loop = asyncio.get_event_loop()
        genius = Genius(self.GENIUS_TOKEN, verbose=False)
        import requests
        try:
            await loop.run_in_executor(self._executor, genius.search_song, "chevy uwu")
            return True
        except requests.exceptions.HTTPError:
            return False

    def _fetch_lyrics(self, query: str) -> typing.Optional[Song]:
        genius = Genius(self.GENIUS_TOKEN, verbose=False)
        return genius.search_song(query, get_full_info=False)

    @cache(512)
    async def fetch_lyrics(self, query: str) -> typing.Optional[Song]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._fetch_lyrics, query)
