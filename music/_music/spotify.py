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

Partial attribution for this file—"spotify.py" goes to https://github.com/Just-Some-Bots/MusicBot
"""

import asyncio
import base64
import time

from .exceptions import SpotifyError

__all__ = ['Spotify']


class Spotify:
    OAUTH_TOKEN_URL = 'https://accounts.spotify.com/api/token'
    API_BASE = 'https://api.spotify.com/v1/'

    def __init__(self, bot, client_id, client_secret):
        self.bot = bot
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None

    @staticmethod
    def _make_token_auth(client_id, client_secret):
        auth_header = base64.b64encode((client_id + ':' + client_secret).encode('ascii'))
        return {'Authorization': 'Basic %s' % auth_header.decode('ascii')}

    async def get_track(self, uri):
        return await self.make_spotify_req(self.API_BASE + 'tracks/{0}'.format(uri))

    async def get_album(self, uri):
        return await self.make_spotify_req(self.API_BASE + 'albums/{0}'.format(uri))

    async def get_playlist(self, uri):
        return await self.make_spotify_req(self.API_BASE + 'playlists/{0}'.format(uri))

    async def make_spotify_req(self, url):
        token = await self.get_token()
        return await self.make_get(url, headers={'Authorization': 'Bearer {0}'.format(token)})

    async def make_get(self, url, headers=None):
        async with self.bot.session.get(url, headers=headers) as r:
            if r.status != 200:
                raise SpotifyError('Failed to make GET request to {0}: [{1.status}] {2}'.format(url, r, await r.json()))
            return await r.json()

    async def make_post(self, url, payload, headers=None):
        async with self.bot.session.post(url, data=payload, headers=headers) as r:
            if r.status != 200:
                raise SpotifyError('Failed to make POST request to {0}: [{1.status}] {2}'.format(url, r, await r.json()))
            return await r.json()

    async def get_token(self):
        if self.token and not await self.check_token(self.token):
            return self.token['access_token']

        token = await self.request_token()
        if token is None:
            raise SpotifyError('Requested a token from Spotify, did not end up getting one')
        token['expires_at'] = time.time() + token['expires_in']
        self.token = token
        return self.token['access_token']

    @staticmethod
    async def check_token(token):
        now = time.time()
        return token['expires_at'] - now < 60

    async def request_token(self):
        payload = {'grant_type': 'client_credentials'}
        headers = self._make_token_auth(self.client_id, self.client_secret)
        r = await self.make_post(self.OAUTH_TOKEN_URL, payload=payload, headers=headers)
        return r

    async def process(self, spotify_link):
        spotify_link_parts = spotify_link.split(":")
        playlist_name = None
        playlist_link = None
        image = None

        song_names = []
        try:
            if 'track' in spotify_link_parts:
                track_resp = await self.get_track(spotify_link_parts[-1])
                song_names = [(f"{track_resp['artists'][0]['name']} {track_resp['name']}", track_resp['duration_ms'])]

            elif 'album' in spotify_link_parts:
                album_resp = await self.get_album(spotify_link_parts[-1])
                tracks = album_resp['tracks']['items']
                for track in tracks:
                    song_names += [(f"{track['artists'][0]['name']} {track['name']}", track['duration_ms'])]
                playlist_name = album_resp['name']
                playlist_link = album_resp['external_urls']['spotify']
                images = album_resp['images']
                if images:
                    # most square, largest
                    image = min(images,
                                key=lambda img: ((abs(img.get('height') or 9999) - (img.get('width') or -99999)),
                                                 99999 - (img.get('height') or 1) * (img.get('width') or 1)))['url']

            elif 'playlist' in spotify_link_parts:
                playlist_resp = await self.get_playlist(spotify_link_parts[-1])
                tracks = (playlist_resp['tracks'] or {}).get('items', [])
                for track in tracks:
                    song_names += [(f"{track['track']['artists'][0]['name']} {track['track']['name']}",
                                    track['track']['duration_ms'])]
                playlist_name = playlist_resp['name']
                playlist_link = playlist_resp['external_urls']['spotify']
                images = playlist_resp['images']
                if images:
                    # most square, largest
                    image = min(images,
                                key=lambda img: ((abs(img.get('height') or 9999) - (img.get('width') or -99999)),
                                                 99999 - (img.get('height') or 1) * (img.get('width') or 1)))['url']

            else:
                raise SpotifyError('That is not a supported Spotify URI.')
        except SpotifyError:
            raise
        except Exception as e:
            raise SpotifyError(str(e)) from e
        return song_names, playlist_name, playlist_link, image
