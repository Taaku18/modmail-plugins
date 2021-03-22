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
import base64
import json
import os
import time
import typing
import urllib.parse
import zlib
from base64 import b64decode
from collections import defaultdict

import lavalink

import discord
from discord import AllowedMentions
from discord.ext import commands, tasks

from ._music import *

from core import checks
from core.models import getLogger, PermissionLevel


logger = getLogger(__name__)
logger.spam = lambda *args, **kwargs: None
MUSIC_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music-states")
if not os.path.exists(MUSIC_STATE_PATH):
    os.mkdir(MUSIC_STATE_PATH)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._spotify: typing.Optional[Spotify] = None
        self.db = bot.api.get_plugin_partition(self)
        self._lyrics_api: typing.Optional[Lyrics] = None

        if not hasattr(self.bot, 'lavalink'):  # This ensures the client isn't overwritten during cog reloads.
            BOT_ID = int(b64decode(self.bot.token.split(".")[0]).decode())
            self.bot.lavalink = lavalink.Client(BOT_ID, player=Player)
            self.bot.lavalink_saved_states = {}
            for save_file in os.listdir(MUSIC_STATE_PATH):
                save_file = os.path.join(MUSIC_STATE_PATH, save_file)
                if not save_file.endswith('.json'):
                    continue
                # noinspection PyBroadException
                try:
                    with open(save_file, 'r') as f:
                        save = json.load(f)
                    if time.time() - save['timestamp'] > 1800:
                        logger.error("Save file timestamp older than 30 minutes, ignoring")
                        os.unlink(save_file)
                        continue
                    save_state = self.bot.lavalink_saved_states[save['node_name']] = {}

                    for gid, data in save['guilds'].items():
                        save_state[int(gid)] = data
                except Exception:
                    logger.warning("Failed to load save state %s", save_file, exc_info=True)
                    os.unlink(save_file)
            self.bot.add_listener(self.bot.lavalink.voice_update_handler, 'on_socket_response')
        else:
            import aiohttp
            if self.bot.lavalink._session.closed:
                self.bot.lavalink._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=30)
                )
        # noinspection PyTypeChecker
        lavalink.add_event_hook(self.track_hook)
        self.bot.loop.create_task(self.cog_load())

    @property
    def lyrics_api(self) -> typing.Optional[Lyrics]:
        return self._lyrics_api

    @property
    def spotify(self) -> typing.Optional[Spotify]:
        if not self._spotify or not self._spotify.token:
            return None
        return self._spotify

    async def cog_load(self):
        config = await self.db.find_one({'_id': 'music-config'})
        if config:
            SPOTIFY_CLIENT_ID = config.get('spotify_client_id')
            SPOTIFY_CLIENT_SECRET = config.get('spotify_client_secret')
            if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
                try:
                    self._spotify = Spotify(self.bot, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
                    await self._spotify.get_token()
                except SpotifyError as e:
                    self._spotify = None
                    logger.error('There was a problem initialising the connection to Spotify. '
                                 'Is your client ID and secret correct? Details: %s.', e)
                    await self.db.find_one_and_update(
                        {'_id': 'music-config'},
                        {'$set': {'spotify_client_id': None,
                                  'spotify_client_secret': None}},
                        upsert=True
                    )
            GENIUS_TOKEN = config.get("genius_token")
            if GENIUS_TOKEN:
                self._lyrics_api = Lyrics(GENIUS_TOKEN)
                if not await self._lyrics_api.test_token():
                    await self.db.find_one_and_update(
                        {'_id': 'music-config'},
                        {'$set': {'genius_token': None}},
                        upsert=True
                    )
                    self._lyrics_api = None

            LAVALINK_URI = config.get('lavalink')
            if LAVALINK_URI:
                if not isinstance(LAVALINK_URI, list):
                    await self.db.find_one_and_update(
                        {'_id': 'music-config'},
                        {'$set': {'lavalink': None}},
                        upsert=True
                    )
                else:
                    import secrets
                    BOT_ID = int(b64decode(self.bot.token.split(".")[0]).decode())

                    good_uri = []
                    for uri in LAVALINK_URI:
                        parsed = urllib.parse.urlparse(uri)
                        resume_key = secrets.token_hex(12)
                        name = f"{BOT_ID}-{resume_key}"
                        LAVALINK_HOST = parsed.hostname
                        LAVALINK_PORT = parsed.port
                        LAVALINK_PW = parsed.password
                        if not LAVALINK_PW:
                            LAVALINK_PW = parsed.username
                            LAVALINK_LOC = 'us'
                        else:
                            LAVALINK_LOC = parsed.username
                        if LAVALINK_HOST and LAVALINK_PORT and LAVALINK_PW:
                            self.bot.lavalink.add_node(
                                LAVALINK_HOST,
                                LAVALINK_PORT,
                                LAVALINK_PW,
                                LAVALINK_LOC,
                                name,  # Don't think resuming is necessary
                                resume_timeout=600,  # Since bot disconnects from vc automatically on term
                                reconnect_attempts=-1  # On-disconnect isn't handled yet < TODO
                            )
                            good_uri += [uri]
                    if len(good_uri) != len(LAVALINK_URI):
                        await self.db.find_one_and_update(
                            {'_id': 'music-config'},
                            {'$set': {'lavalink': good_uri or None}},
                            upsert=True
                        )

        await self.bot.wait_until_ready()
        self.auto_disconnect.start()

    def cleanup(self):
        logger.debug("Saving music states...")

        saves = defaultdict(dict)

        for gid, player in self.bot.lavalink.player_manager.players.items():
            player: Player
            if not player.is_connected:
                logger.info("Skipped saving %s", player)
                continue
            data = player.dump()
            saves[data['node_name']].setdefault('guilds', {})
            saves[data['node_name']]['guilds'][gid] = data
        for node_name, save in saves.items():
            save['timestamp'] = time.time()
            save['node_name'] = node_name
            logger.info("Saving lavalink save file for %s", node_name)
            with open(os.path.join(MUSIC_STATE_PATH, f"{node_name}.json"), 'w') as f:
                json.dump(save, f, indent=4, sort_keys=True)

        try:
            logger.info("Closing lavalink session.")
            # noinspection PyProtectedMember
            self.bot.loop.run_until_complete(self.bot.lavalink._session.close())
        except asyncio.CancelledError:
            pass

    @tasks.loop(seconds=20, reconnect=False)
    async def auto_disconnect(self):
        for player in self.bot.lavalink.player_manager.players.values():
            player: Player
            if player.is_connected:
                vc = self.bot.get_channel(int(player.channel_id))
                if not player.is_playing_a_track or (vc and not any(not m.bot for m in vc.members)):
                    logger.debug('Auto disconnecting from %s', player.guild_id)
                    player.disconnect_soon(self.bot)
            elif player.queue.position_timestamp - time.time() > 30:
                logger.warning("Idle player, destroy? %s", player)

    def cog_unload(self):
        self.auto_disconnect.cancel()
        # noinspection PyProtectedMember
        self.bot.lavalink._event_hooks.clear()
        self.cleanup()

    async def cog_before_invoke(self, ctx):
        # TODO: check bot connected
        if ctx.command.qualified_name in {'musicconfig', 'requestapi', 'aboutmusic'}:
            return
        if not self.bot.lavalink.node_manager.available_nodes:
            raise Failure(ctx, "Music isn't ready/configured yet, try again later...\n"
                               f"You can configure music with `{self.bot.prefix}musicconfig`. "
                               "If you already configured music with your API URI and it's still not working, "
                               "perhaps check logs to see the error.")
        await self.ensure_voice(ctx)

    async def ensure_voice(self, ctx):
        ctx.player = self.bot.lavalink.player_manager.create(ctx.guild.id, endpoint=str(ctx.guild.region))
        is_universal = ctx.command.qualified_name in {'search', 'lyrics'}
        if is_universal:
            return
        ctx.player.main_color = self.bot.main_color
        ctx.player.error_color = self.bot.error_color
        should_connect = ctx.command.qualified_name in {'play', 'join'}

        if not ctx.author.voice or not ctx.author.voice.channel:
            raise Failure(ctx, 'Join a voice channel first.')

        if not ctx.player.is_connected:
            if not should_connect:
                raise Failure(ctx, "I'm not playing anything.")

            permissions = ctx.author.voice.channel.permissions_for(ctx.me)

            if not permissions.connect or not permissions.speak:  # Check user limit too?
                raise Failure(ctx, 'I need the **connect** and **speak** permissions.')

            await self.connect_to(ctx.guild.id, ctx.author.voice.channel.id)
            opt = {}
            if ctx.guild.me.guild_permissions.mute_members:
                opt['mute'] = False
            if ctx.guild.me.guild_permissions.deafen_members:
                opt['deafen'] = True
            if opt:
                await ctx.guild.me.edit(**opt)
        else:
            if int(ctx.player.channel_id) != ctx.author.voice.channel.id and \
                    ctx.command.qualified_name != 'join':
                raise Failure(ctx, "You're not in my voice channel.")

        should_change_cmd_channel = ctx.command.qualified_name in {'play', 'next', 'back', 'stop', 'join'}
        if should_change_cmd_channel:
            ctx.player.command_channel = ctx.channel

    async def track_hook(self, event):
        if isinstance(event, lavalink.events.QueueEndEvent):
            player: Player = event.player
            # noinspection PyBroadException
            try:
                logger.debug("Queue ended")
                player.playing_message = None
            except Exception:
                logger.warning("Failed to disconnect / schedule clear queue", exc_info=True)

        elif isinstance(event, lavalink.events.WebSocketClosedEvent):
            # Need to handle?
            logger.debug('WS closed %s %s %s', event.by_remote, event.code, event.reason)

        elif isinstance(event, lavalink.events.NodeDisconnectedEvent):
            logger.warning('Node disconnected')

        elif isinstance(event, lavalink.events.NodeConnectedEvent):
            logger.warning('Node connected')
            if event.node.name in self.bot.lavalink_saved_states:
                async def reconnect(gid, data):
                    # noinspection PyBroadException
                    try:
                        logger.info("Recreating player for %s", gid)
                        await Player.load_dump(self.bot, gid, event.node, data)
                    except Exception:
                        logger.warning("Failed to reconnect %s", gid, exc_info=True)

                save = self.bot.lavalink_saved_states.pop(event.node.name)
                await self.bot.wait_until_ready()
                try:
                    await asyncio.gather(*[reconnect(gid, data) for gid, data in save.items()])
                finally:
                    logger.debug("Removing save file for %s", event.node.name)
                    save_file = os.path.join(MUSIC_STATE_PATH, f"{event.node.name}.json")
                    if os.path.exists(save_file):
                        os.unlink(save_file)

    async def connect_to(self, guild_id: int, channel_id: typing.Optional[int]) -> None:
        # noinspection PyProtectedMember
        ws = self.bot._connection._get_websocket(int(guild_id))
        if not channel_id:
            await ws.voice_state(guild_id, None)
        else:
            await ws.voice_state(guild_id, int(channel_id))

    # Don't want to cache too long, in case there's an update
    @utils.cache(500, expires_after=3600)  # 1 hour
    async def _req_spotify(self, query):
        return await self.spotify.process(query)

    @staticmethod
    def _format_url(music_url):
        logger.spam("URL matched %s", music_url)
        playlist = False
        try:
            url = urllib.parse.urlparse(music_url)
            if YOUTUBE_REGEX.findall(url.netloc):
                query = urllib.parse.parse_qs(url.query)
                if 'list' in query:
                    logger.debug("Youtube URL matched, normalising")
                    # noinspection PyTypeChecker
                    if 'v' in query:
                        # noinspection PyTypeChecker
                        music_url = f"https://www.youtube.com/watch?v={query['v'][0]}&list={query['list'][0]}"
                    else:
                        # noinspection PyTypeChecker
                        music_url = f"https://www.youtube.com/playlist?list={query['list'][0]}"
                    playlist = True
            elif 'open.spotify.com' in url.netloc:
                logger.spam("Spotify URL matched")
                music_url = 'spotify:' + ':'.join(url.path.split('/')[1:])
        except ValueError:
            pass
        return music_url, playlist

    @staticmethod
    def _try_youtube_mix(query):
        try:
            url = urllib.parse.urlparse(query)
            query = urllib.parse.parse_qs(url.query)
            # noinspection PyTypeChecker
            return f"https://www.youtube.com/watch?v={query['v'][0]}&list={query['list'][0]}"
        except (ValueError, KeyError):
            return None

    @staticmethod
    def _render(tracks):
        prefix = "```nim\n"
        suffix = "\n```"
        track_per_page = 10

        if not tracks:
            return [f"{prefix}No tracks found...{suffix}"]

        messages = []

        total_tracks = len(tracks)

        count_length = 1
        if total_tracks >= 10:
            count_length += 1

        # TODO: Pad duration too
        for i, track in enumerate(tracks, start=1):
            if (i - 1) % track_per_page == 0:
                messages += [""]

            if i == 91 and total_tracks >= 100:
                count_length += 1

            block_max_title_length = max(30, len(max(
                tracks[(i - 1) // track_per_page * track_per_page:
                       (i - 1) // track_per_page * track_per_page + track_per_page],
                key=lambda x: len(x.title)).title))
            title_length = min(39 - count_length, block_max_title_length)
            title = utils.trim(track.title if track.success else f"[failed] {track.title}",
                               title_length).ljust(title_length)

            if hasattr(track, 'duration'):
                duration = utils.seconds_to_time_string(track.duration / 1000,
                                                        int_seconds=True, format=2)
            else:
                duration = "  ???"
            messages[-1] += f"{i: >{count_length}}) {title} {duration}\n"

            remaining_tracks = total_tracks - i
            if i % track_per_page == 0 and remaining_tracks > 0:
                messages[-1] += f"\n{' ' * count_length}{remaining_tracks} more " \
                                f"{utils.plural(remaining_tracks, show_count=False):track}"

        for i in range(len(messages)):
            messages[i] = prefix + messages[i].replace('```', '``\u200b`').replace('@', '@\u200b') + suffix
        return messages

    @commands.cooldown(1, 10)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.OWNER)
    async def requestapi(self, ctx):
        """Request a free api URI

        Note: you will send include some data with your request, such as the bot ID and name,
        for tracking API usage purposes."""
        app = await self.bot.application_info()
        if app.team:
            owner_ids = [m.id for m in app.team.members]
        else:
            owner_ids = [app.owner.id]
        requester_id = ctx.author.id
        requester_name = str(ctx.author)
        bot_id = self.bot.user.id
        bot_name = self.bot.user.name
        guild_name = self.bot.guild.name
        guild_count = self.bot.guild.member_count
        data = json.dumps(dict(owner_ids=owner_ids, requester_id=requester_id, requester_name=requester_name, bot_id=bot_id, bot_name=bot_name, guild_name=guild_name, guild_count=guild_count))
        data = zlib.compress(data.encode(), 9)
        data = base64.b64encode(data).decode()
        try:
            await ctx.author.send("Join the Official Modmail Server if you haven't yet: https://discord.gg/F34cRU8. "
                                  "Send a DM to our Modmail bot (Modmail#4391) with the following message (copied exactly as-is):\n\n```"
                                  "Hello, I would like to request a free Music API URI.\n\n"
                                  f"Key:\n`#{data}#`\n```\n\nWe'll give you a free music API URI with courtesy of ¥¥lorenzo¥¥#0001!")
            await ctx.send(f"{ctx.author.mention} Please check your DM!")
        except discord.HTTPException:
            raise Failure(ctx, "I'll need to be able to DM you, please enable DM from this server.")

    @commands.cooldown(1, 10)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.OWNER)
    async def musicconfig(self, ctx, type: Str(lower=True), *, config: Str(remove_code=True)):
        """
        There are three valid config types: `api`, `spotify` and `genius`.

        Courtesy of ¥¥lorenzo¥¥#0001, you can request a **free** API URI from us. Run the `{prefix}requestapi` command to get your very own api URI.

        Spotify is for spotify support and genius is for lyrics search.

        Formats:
        ```
        api     - lavalink://location:password@hostname:port
        spotify - SPOTIFY_CLIENT_ID:SPOTIFY_CLIENT_SECRET
        genius  - GENIUS_TOKEN
        ```

        Examples (yours would definitely be different):
        ```
        {prefix}musicconfig api lavalink://us:verysecretpw@123.321.1.32:1234
        {prefix}musicconfig spotify bc8500a0bb59f4336393ae30e9a82930c:358500a0bb595536393ae30e9a82930d
        {prefix}musicconfig genius YtRxZDO3jcOId098iE49blkckKdj3oIdjOS2CAZEGDUiOT9Q4k3OR_p-Kdih93NL
        ```
        """
        if type == "spotify":
            parts = [c.strip() for c in config.split(':', maxsplit=1)]
            if len(parts) != 2:
                raise Failure(ctx, "The format for configuring spotify is `SPOTIFY_CLIENT_ID:SPOTIFY_CLIENT_SECRET`.")

            SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET = parts
            if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
                raise Failure(ctx, "The format for configuring spotify is `SPOTIFY_CLIENT_ID:SPOTIFY_CLIENT_SECRET`.")
            try:
                self._spotify = Spotify(self.bot, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
                await self._spotify.get_token()
            except SpotifyError as e:
                self._spotify = None
                logger.error('There was a problem initialising the connection to Spotify. '
                             'Is your client ID and secret correct? Details: %s.', e)
                await self.db.find_one_and_update(
                    {'_id': 'music-config'},
                    {'$set': {'spotify_client_id': None,
                              'spotify_client_secret': None}},
                    upsert=True
                )
                raise Failure(ctx, "Failed to connect to Spotify, is your client ID and secret correct?")
            else:
                await self.db.find_one_and_update(
                    {'_id': 'music-config'},
                    {'$set': {'spotify_client_id': SPOTIFY_CLIENT_ID,
                              'spotify_client_secret': SPOTIFY_CLIENT_SECRET}},
                    upsert=True
                )
            return await ctx.send("Successfully set and enabled spotify!")
        elif type == "genius":
            GENIUS_TOKEN = config
            self._lyrics_api = Lyrics(GENIUS_TOKEN)
            m = await ctx.send("Checking the token... please wait")
            if not await self._lyrics_api.test_token():
                await self.db.find_one_and_update(
                    {'_id': 'music-config'},
                    {'$set': {'genius_token': None}},
                    upsert=True
                )
                self._lyrics_api = None
                raise Failure(ctx, "It seems your Genius API token is invalid...")
            else:
                await self.db.find_one_and_update(
                    {'_id': 'music-config'},
                    {'$set': {'genius_token': GENIUS_TOKEN}},
                    upsert=True
                )
            return await m.edit(content="Successfully set and enabled genius lyrics!")
        elif type == 'api':
            import secrets
            BOT_ID = int(b64decode(self.bot.token.split(".")[0]).decode())
            parsed = urllib.parse.urlparse(config)
            resume_key = secrets.token_hex(12)
            name = f"{BOT_ID}-{resume_key}"
            LAVALINK_HOST = parsed.hostname
            LAVALINK_PORT = parsed.port
            LAVALINK_PW = parsed.password
            if not LAVALINK_PW:
                LAVALINK_PW = parsed.username
                LAVALINK_LOC = 'us'
            else:
                LAVALINK_LOC = parsed.username
            if LAVALINK_HOST and LAVALINK_PORT and LAVALINK_PW:
                self.bot.lavalink.add_node(
                    LAVALINK_HOST,
                    LAVALINK_PORT,
                    LAVALINK_PW,
                    LAVALINK_LOC,
                    name,  # Don't think resuming is necessary
                    resume_timeout=600,  # Since bot disconnects from vc automatically on term
                    reconnect_attempts=-1  # On-disconnect isn't handled yet < TODO
                )
            else:
                raise Failure(ctx, "Invalid API URI format, needs to be `lavalink://loc:password@hostname`")
            await self.db.find_one_and_update(
                {'_id': 'music-config'},
                {'$set': {'lavalink': [config]}},
                upsert=True
            )
            return await ctx.send("Successfully set and enabled music!")

    @commands.cooldown(1, 1.5)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def search(self, ctx, *, query: Str(remove_code=True)):
        """Search for a song"""
        player: Player = ctx.player

        raw_query = query = query.strip('<>')
        matches = URL_REGEX.search(query)
        is_youtube_playlist = False
        if matches:
            query, is_youtube_playlist = self._format_url(query)
        elif not IDENTIFIER_REGEX.match(query):
            # And not Direct URL
            logger.debug("Fallback on youtube search")
            query = f'ytsearch:{query}'

        logger.debug("Requesting query %s", query)

        if self.spotify and query.startswith('spotify:'):
            logger.spam("Processing spotify")
            try:
                titles, playlist_name, playlist_link, spotify_image = await self._req_spotify(query)
            except SpotifyError as e:
                logger.debug("Bad spotify %s", e)
                raise Failure(ctx, "It seems your Spotify link is invalid or is private.")
            if playlist_name:
                if not titles:
                    raise Failure(ctx, 'The spotify link is empty!')
                tracks = [LazyAudioTrack(f'ytsearch:{title}', title, ctx.author.id, duration=duration, spotify=True)
                          for title, duration in titles]
                await asyncio.gather(*[track.load(player) for track in tracks])
                pages = self._render(tracks)
                if len(pages) == 1:
                    return await ctx.send(pages[-1], allowed_mentions=AllowedMentions.none())
                session = PaginatorSession(ctx, *pages)
                return await session.run()

            track = LazyAudioTrack(f'ytsearch:{titles[0][0]}', titles[0][0], ctx.author.id,
                                   duration=titles[0][1], spotify=True)
            await track.load(player)
            pages = self._render([track])
            return await ctx.send(pages[-1], allowed_mentions=AllowedMentions.none())

        if is_youtube_playlist:
            try:
                result = await player.req_lavalink_playlist(query)
            except Exception as e:
                logger.warning("Unknown error while playing music %s", e)
                raise Failure(ctx, "An unknown error has occurred... try again later")
            if not result or not result['tracks']:
                logger.debug("Using a malformed mix")
                # A malformed mix
                query = self._try_youtube_mix(raw_query)
                if query:
                    result = await player.req_lavalink_playlist(query)
                if not result or not result['tracks']:
                    logger.debug("Bad req %s %s", query, result)
                    raise Failure(ctx, "This YouTube link is invalid!")
            if result['loadType'] == 'PLAYLIST_LOADED':
                tracks = []
                for track in result['tracks']:
                    # noinspection PyTypeChecker
                    tracks += [LazyAudioTrack.from_loaded(track, ctx.author.id)]

                pages = self._render(tracks)
                if len(pages) == 1:
                    return await ctx.send(pages[-1], allowed_mentions=AllowedMentions.none())
                session = PaginatorSession(ctx, *pages)
                return await session.run()

            else:
                logger.error("Shouldn't be here... %s", query)
                raise Failure(ctx, "An unknown error has occurred... try again later")

        try:
            result = await player.req_lavalink_track(query)
        except Exception:
            logger.error("Fetching track failed %s", self, exc_info=True)
            raise Failure(ctx, "An unknown error has occurred... try again later")

        if not result or not result['tracks']:
            logger.error("Fetching track failed %s %s", self, result)
            raise Failure(ctx, 'No matches found!')

        tracks = []
        for track in result['tracks'][:10]:
            tracks += [LazyAudioTrack.from_loaded(track, ctx.author.id)]

        pages = self._render(tracks)
        return await ctx.send(pages[-1], allowed_mentions=AllowedMentions.none())

    @commands.cooldown(1, 1.5, type=commands.BucketType.guild)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command(aliases=['enqueue'])
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def play(self, ctx, *, query: Str(remove_code=True) = None):
        """Play your chosen track or playlist"""

        player: Player = ctx.player

        if query is None:
            logger.spam("Playing track? %s", player.is_playing_a_track)
            logger.spam("Paused? %s", player.paused)
            if not player.is_playing_a_track:
                track = await player.play_previous()
                if not track:
                    raise Failure(ctx, "There's no songs in the queue!")
                if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
                    try:
                        return await ctx.message.add_reaction("👌")
                    except discord.HTTPException:
                        logger.debug("Failed to add reaction")
            elif player.paused:
                await player.set_pause(False)
                if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
                    try:
                        return await ctx.message.add_reaction("▶️")
                    except discord.HTTPException:
                        logger.debug("Failed to add reaction")
            return await ctx.send('Playing!')

        raw_query = track_title = query = query.strip('<>')
        matches = URL_REGEX.search(query)
        is_youtube_playlist = False
        if matches:
            query, is_youtube_playlist = self._format_url(query)
            track_title = query
        elif not IDENTIFIER_REGEX.match(query):
            # And not Direct URL
            logger.debug("Fallback on youtube search")
            query = f'ytsearch:{query}'

        tracks = []
        loaded_any_song = False
        logger.debug("Requesting query %s", query)

        if self.spotify and query.startswith('spotify:'):
            logger.spam("Processing spotify")
            try:
                titles, playlist_name, playlist_link, spotify_image = await self._req_spotify(query)
            except SpotifyError as e:
                logger.debug("Bad spotify %s", e)
                raise Failure(ctx, "It seems your Spotify link is invalid or is private.")
            if playlist_name:
                if not titles:
                    raise Failure(ctx, 'The spotify link is empty!')

                embed = discord.Embed(
                    description=f'Queued {utils.plural(len(titles)):track} from [{playlist_name}]({playlist_link})',
                    colour=self.bot.main_color
                )

                if spotify_image:
                    embed.set_thumbnail(url=spotify_image)
                await ctx.send(embed=embed)
                for title, duration in titles:
                    track = LazyAudioTrack(f'ytsearch:{title}', title, ctx.author.id,
                                           duration=duration, spotify=True)
                    await player.play_later(track=track, send_queue_message=False)
                    tracks += [track]
            else:
                track = LazyAudioTrack(f'ytsearch:{titles[0][0]}', titles[0][0], ctx.author.id,
                                       duration=titles[0][1], spotify=True)
                await player.play_later(track=track)
                tracks += [track]

        else:
            if is_youtube_playlist:
                try:
                    result = await player.req_lavalink_playlist(query)
                except Exception as e:
                    logger.warning("Unknown error while playing music %s", e)
                    raise Failure(ctx, "An unknown error has occurred... try again later")
                if not result or not result['tracks']:
                    logger.debug("Using a malformed mix")
                    # A malformed mix
                    query = self._try_youtube_mix(raw_query)
                    if query:
                        result = await player.req_lavalink_playlist(query)
                    if not result or not result['tracks']:
                        logger.debug("Bad req %s %s", query, result)
                        raise Failure(ctx, "This YouTube link is invalid!")

                # Valid loadTypes are:
                #   TRACK_LOADED    - single video/direct URL)
                #   PLAYLIST_LOADED - direct URL to playlist)
                #   SEARCH_RESULT   - query prefixed with either ytsearch: or scsearch:.
                #   NO_MATCHES      - query yielded no results
                #   LOAD_FAILED     - most likely, the video encountered an exception during loading.

                if result['loadType'] == 'PLAYLIST_LOADED':
                    embed = discord.Embed(
                        description=f"Queued {utils.plural(len(result['tracks'])):track}",
                        colour=self.bot.main_color
                    )
                    await ctx.send(embed=embed)
                    for track in result['tracks']:
                        # noinspection PyTypeChecker
                        track = LazyAudioTrack.from_loaded(track, ctx.author.id)
                        await player.play_later(track=track, send_queue_message=False)
                        if track.success:
                            loaded_any_song = True
                else:
                    logger.error("Shouldn't be here... %s", query)
                    raise Failure(ctx, "An unknown error has occurred... try again later")
            else:
                track = LazyAudioTrack(query, track_title, ctx.author.id)
                await player.play_later(track=track)
                tracks.append(track)

        if not is_youtube_playlist:
            # load first the first song of spotify, or the query song
            for track in tracks:
                if loaded_any_song:
                    break
                try:
                    await track.load(player)
                except Exception as e:
                    logger.warning("Unknown error while loading music %s", e)
                    continue
                if track.success:
                    loaded_any_song = True
                else:
                    player.queue.remove(track)

        player.load_next_few()

        if not loaded_any_song:
            raise Failure(ctx, 'No matches found!')

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def pause(self, ctx):
        """Pause the current track"""
        player: Player = ctx.player
        if not player.paused:
            await player.set_pause(True)
        if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
            try:
                return await ctx.message.add_reaction("⏸")
            except discord.HTTPException:
                logger.debug("Failed to add reaction")
        await ctx.send("Paused!")

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def resume(self, ctx):
        """Resume the paused track"""
        player: Player = ctx.player
        if player.paused:
            await player.set_pause(False)
        if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
            try:
                return await ctx.message.add_reaction("▶️")
            except discord.HTTPException:
                logger.debug("Failed to add reaction")
        await ctx.send('Now resuming!')

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command(aliases=['skip'])
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def next(self, ctx):
        """Skip to the next track"""
        player: Player = ctx.player
        was_playing = player.is_playing_a_track
        await player.play_next(force=True)
        if was_playing:
            if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
                try:
                    return await ctx.message.add_reaction("👌")
                except discord.HTTPException:
                    logger.debug("Failed to add reaction")
            return await ctx.send('Skipped!')
        else:
            if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
                try:
                    return await ctx.message.add_reaction("🚫")
                except discord.HTTPException:
                    logger.debug("Failed to add reaction")
            return await ctx.send('No more songs!')

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command(aliases=['prev', 'previous'])
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def back(self, ctx):
        """Return to the previous song"""
        player: Player = ctx.player
        if await player.play_previous():
            if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
                try:
                    return await ctx.message.add_reaction("👌")
                except discord.HTTPException:
                    logger.debug("Failed to add reaction")
            return await ctx.send('Backed!')
        else:
            if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
                try:
                    return await ctx.message.add_reaction("🚫")
                except discord.HTTPException:
                    logger.debug("Failed to add reaction")
            return await ctx.send('No more songs!')

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command(aliases=["summon"])
    @checks.has_permissions(PermissionLevel.SUPPORTER)
    async def join(self, ctx):
        """Summon me to your vc"""
        player: Player = ctx.player

        if int(player.channel_id) != ctx.author.voice.channel.id:
            await self.connect_to(ctx.guild.id, ctx.author.voice.channel.id)
        if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
            try:
                return await ctx.message.add_reaction("👌")
            except discord.HTTPException:
                logger.debug("Failed to add reaction")
        return await ctx.send('Joined!')

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def clear(self, ctx):
        """Clears the queue"""
        player: Player = ctx.player
        await player.queue.clear()
        if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
            try:
                return await ctx.message.add_reaction("👌")
            except discord.HTTPException:
                logger.debug("Failed to add reaction")
        return await ctx.send(f'{ctx.author.mention} cleared the queue!')

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def queue(self, ctx):
        """Displays the queue"""
        player: Player = ctx.player
        pages, current_track = player.queue.rendered
        if len(pages) == 1:
            return await ctx.send(pages[0], allowed_mentions=AllowedMentions.none())
        session = utils.PaginatorSession(ctx, *pages)
        if current_track:
            await session.show_page(current_track)
        await session.run()

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command(aliases=['dc'])
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def disconnect(self, ctx):
        """Disconnects me from your voice channel and clears the queue"""
        player: Player = ctx.player

        # Clear the queue to ensure old tracks don't start playing
        # when someone else queues something.
        await player.queue.clear()
        # Disconnect from the voice channel.
        await player.disconnect(self.bot)
        if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
            try:
                return await ctx.message.add_reaction("👋")
            except discord.HTTPException:
                logger.debug("Failed to add reaction")
        await ctx.send(f'Disconnected from {ctx.author.voice.channel}')

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def stop(self, ctx):
        """Stops the current song"""
        player: Player = ctx.player

        await player.queue.stop()
        if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
            try:
                return await ctx.message.add_reaction("🛑")
            except discord.HTTPException:
                logger.debug("Failed to add reaction")
        return await ctx.send(f'{ctx.author.mention} stopped this track!')

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def shuffle(self, ctx):
        """Shuffles the queue"""
        player: Player = ctx.player

        if not player.queue:
            raise Failure(ctx, "The queue is empty!")

        await player.shuffle()
        if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
            try:
                return await ctx.message.add_reaction("🔀")
            except discord.HTTPException:
                logger.debug("Failed to add reaction")
        return await ctx.send('Queue shuffled!')

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command(usage="<track or position> <new position>")
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def movequeue(self, ctx, *, move_query: str):
        """Move a song from the queue to a different position"""
        player: Player = ctx.player

        if not player.queue:
            raise Failure(ctx, "The queue is empty!")

        split = move_query.rsplit(" ", 1)
        if len(split) != 2:
            return await ctx.send_help(ctx.command)
        try:
            new_pos = int(split[1])
        except ValueError:
            return await ctx.send_help(ctx.command)
        track_or_pos = split[0].strip('"` ')
        if not player.queue:
            raise Failure(ctx, "The queue is empty!")
        resp = await player.queue.move(track_or_pos, new_pos)
        if isinstance(resp, str):
            raise Failure(ctx, resp)
        track, new_pos = resp
        embed = discord.Embed(
            description=f"Moved **{track.title}** to position **{new_pos}**",
            colour=self.bot.main_color
        )
        await ctx.send(embed=embed)

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command(usage="<track or position>")
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def jump(self, ctx, *, jump_to: str):
        """Jump to a position in the queue"""
        player: Player = ctx.player

        if not player.queue:
            raise Failure(ctx, "The queue is empty!")

        track_or_pos = jump_to.strip('"` ')
        resp = await player.queue.jump(track_or_pos)
        if isinstance(resp, str):
            raise Failure(ctx, resp)
        track, new_pos = resp
        if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
            try:
                return await ctx.message.add_reaction("👌")
            except discord.HTTPException:
                logger.debug("Failed to add reaction")
        embed = discord.Embed(
            description=f'Jumped to **{track.title}** at position **{new_pos}**!',
            colour=self.bot.main_color
        )
        return await ctx.send(embed=embed)

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command(usage="<track or position or range>")
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def remove(self, ctx, *, removing: str):
        """Remove track(s) from the queue

        Ranges can be specified with "start-end".
        """
        player: Player = ctx.player

        if not player.queue:
            raise Failure(ctx, "The queue is empty!")

        track_or_pos_or_range = removing.strip('"` ')
        resp = await player.queue.remove_track(track_or_pos_or_range)
        if isinstance(resp, str):
            raise Failure(ctx, resp)
        elif isinstance(resp, int):
            embed = discord.Embed(
                description=f'Removed {resp} tracks from queue!',
                colour=self.bot.main_color
            )
            return await ctx.send(embed=embed)
        track, pos = resp
        embed = discord.Embed(
            description=f'Removed **{track.title}** at position **{pos}**!',
            colour=self.bot.main_color
        )
        return await ctx.send(embed=embed)

    @staticmethod
    def _parse_duration(ctx, duration):
        if isinstance(duration, str):
            match = DURATION_REGEX.search(duration)
            if any(match.groups()):
                duration = float(match.group('hours') or 0) * 3600 + \
                           float(match.group('minutes') or 0) * 60 + \
                           float(match.group('seconds') or 0)
            else:
                raise Failure(ctx, "Invalid duration")
        else:
            duration = float(duration)
        return duration

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command(aliases=['ff'])
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def fastforward(self, ctx, *, duration: typing.Union[float, int, str]):
        """Fast forward the current track

        duration can be in seconds or in the format of `XHXMXS` (examples: 12M, 4M12S, 1H49S)"""

        player: Player = ctx.player
        if not player.queue:
            raise Failure(ctx, "The queue is empty!")
        if not player.is_playing_a_track:
            raise Failure(ctx, "Not playing anything right now...")

        duration = self._parse_duration(ctx, duration)
        await player.fastforward(duration)
        if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
            try:
                return await ctx.message.add_reaction("⏩")
            except discord.HTTPException:
                logger.debug("Failed to add reaction")
        await ctx.send("Fast forward!")

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command(aliases=['rw'])
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def rewind(self, ctx, *, duration: typing.Union[float, int, str]):
        """Rewind the current track

        duration can be in seconds or in the format of `XHXMXS` (examples: 12M, 4M12S, 1H49S)"""

        player: Player = ctx.player
        if not player.queue:
            raise Failure(ctx, "The queue is empty!")
        if not player.is_playing_a_track:
            raise Failure(ctx, "Not playing anything right now...")

        duration = self._parse_duration(ctx, duration)
        await player.rewind(duration)
        if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
            try:
                return await ctx.message.add_reaction("⏪")
            except discord.HTTPException:
                logger.debug("Failed to add reaction")
        await ctx.send("Rewind!")

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def seek(self, ctx, *, timestamp: typing.Union[float, int, str]):
        """Seek to a position in the track

        timestamp can be in seconds or in the format of `XHXMXS` (examples: 12M, 4M12S, 1H49S)"""

        player: Player = ctx.player
        if not player.queue:
            raise Failure(ctx, "The queue is empty!")
        if not player.is_playing_a_track:
            raise Failure(ctx, "Not playing anything right now...")

        timestamp = max(int(self._parse_duration(ctx, timestamp) * 1000), 0)
        if timestamp >= player.current.duration:
            await player.play_next()
        else:
            await player.seek(timestamp)
        if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
            try:
                return await ctx.message.add_reaction("👌")
            except discord.HTTPException:
                logger.debug("Failed to add reaction")
        await ctx.send("Seeked!")

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command(aliases=["song", 'np'])
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def nowplaying(self, ctx):
        """Shows the position of the current track"""
        player: Player = ctx.player

        if not player.is_playing_a_track:
            raise Failure(ctx, "Not playing anything right now...")

        embed = discord.Embed(
            description=f"**[{player.current.title}]({player.current.uri})** [<@!{player.current.requester}>]",
            colour=self.bot.main_color
        )
        progress = ["▬"] * 19
        current = player.position
        total = player.current.duration
        progress.insert(max(min(round(current/total*20), 20), 0), '🔵')
        progress = "".join(progress)
        footer = ""
        if player.paused and player.repeat == 'track':
            footer += "⏸🔁 "
        elif player.paused:
            footer += "⏸ "
        elif player.repeat == 'track':
            footer += "🔁 "
        footer += f"{progress} {utils.seconds_to_time_string(current / 1000, int_seconds=True, format=3)} " \
                  f"/ {utils.seconds_to_time_string(total / 1000, int_seconds=True, format=3)}"
        embed.set_footer(text=footer)
        await ctx.send(embed=embed)

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command(aliases=["vol"])
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def volume(self, ctx, *, new_volume: typing.Union[float, int, str] = 100):
        """Sets / resets the player volume

        Volume can be 1 (quietest) -> 200 (loudest), volume of 100 is the normal volume.
        """
        if isinstance(new_volume, str):
            try:
                new_volume = float(new_volume.strip('%'))
            except ValueError:
                return await ctx.send_help(ctx.command)

        if new_volume < 1 or new_volume > 200:
            raise Failure(ctx, "Volume needs to be between 1-200!")
        if new_volume > 100:
            # total 100-300: 200 diff
            # settable 100-200: 100 diff
            new_normalised_volume = int(100 + (new_volume - 100) / 100 * 200)
        else:
            new_normalised_volume = int(new_volume)

        player: Player = ctx.player
        if new_normalised_volume == player.volume:
            raise Failure(ctx, "I'm already playing at this volume!")
        elif new_normalised_volume > player.volume:
            emoji = "🔊"
        else:
            emoji = "🔉"
        await player.set_volume(new_normalised_volume)
        if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
            try:
                return await ctx.message.add_reaction(emoji)
            except discord.HTTPException:
                logger.debug("Failed to add reaction")
        await ctx.send(f"Volume changed to {new_volume}%!")

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command(aliases=["repeat"])
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def loop(self, ctx, *, track_or_queue: str.lower = None):
        """Loop the queue or the current track

        Can be `{prefix}loop track`, `{prefix}loop queue`, `{prefix}loop off`.
        By default I'll loop the entire queue!
        """

        if not track_or_queue:
            track_or_queue = 'queue'
        elif track_or_queue == 'song':
            track_or_queue = 'track'
        elif track_or_queue == 'off':
            track_or_queue = 'disable'
        elif track_or_queue not in {'queue', 'track', 'disable'}:
            raise Failure(ctx, f"I can only loop the current track or queue, not {track_or_queue}.")

        player: Player = ctx.player

        if track_or_queue == 'track':
            if not player.is_playing_a_track:
                raise Failure(ctx, "I'm not playing anything right now...")
            player.repeat = 'track'
            message = "Now looping the **current track**."
        elif track_or_queue == 'queue':
            if player.repeat == 'queue':
                player.repeat = None
                message = "Looping is now **disabled**."
            else:
                player.repeat = 'queue'
                message = "Now looping the **queue**."
        else:
            player.repeat = None
            message = "Looping is now **disabled**."
        await ctx.send(embed=discord.Embed(description=message, colour=self.bot.main_color))

    @commands.cooldown(1, 2)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command(aliases=["lyric"])
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def lyrics(self, ctx, *, song_name: Str(remove_code=True) = None):
        """Find the song lyrics for the current or any song"""
        player: Player = ctx.player
        if not self.lyrics_api:
            raise Failure(ctx, f"Genius API is not enabled, provide a GENIUS_TOKEN with the `{self.bot.prefix}musicconfig` command to enable this feature.")
        if not song_name:
            if player.current:
                if player.current.spotify:
                    song_name = player.current.og_title
                else:
                    song_name = player.current.title
            else:
                return await ctx.send_help(ctx.command)
        else:
            need_process = True
            query = song_name.strip('<>')
            matches = URL_REGEX.search(query)
            if matches:
                query, is_youtube_playlist = self._format_url(query)
                if is_youtube_playlist:
                    raise Failure(ctx, "Can't fetch lyrics for a playlist...")
            elif not IDENTIFIER_REGEX.match(query):
                song_name = query
                need_process = False

            if need_process:
                if self.spotify and query.startswith('spotify:'):
                    logger.spam("Processing spotify")
                    if 'track' not in query.split(":"):
                        raise Failure(ctx, "Can't fetch lyrics for a playlist...")

                    try:
                        titles, *_ = await self._req_spotify(query)
                    except SpotifyError as e:
                        logger.debug("Bad spotify %s", e)
                        raise Failure(ctx, "It seems your Spotify link is invalid or is private.")
                    song_name = titles[0][0]
                else:
                    try:
                        result = await player.req_lavalink_track(query)
                    except Exception:
                        logger.error("Fetching track failed %s", self, exc_info=True)
                        raise Failure(ctx, "An unknown error has occurred... try again later")

                    if not result or not result['tracks']:
                        logger.error("Fetching track failed %s %s", self, result)
                        raise Failure(ctx, 'No matches found!')
                    song_name = CLEAN_TITLE_RE.sub("", result['tracks'][0]['info']['title'])

        logger.debug("Fetching lyrics for %s", song_name)
        resp = await self.lyrics_api.fetch_lyrics(song_name)
        if not resp:
            raise Failure(ctx, f"No lyrics found for **{song_name}** :(")
        # noinspection PyShadowingNames
        lyrics = trim(resp.lyrics.strip(), 5500)
        if not lyrics:
            raise Failure(ctx, f"No lyrics found for **{song_name}** :(")

        paginator = WrappedPaginator(prefix="", suffix="", max_size=1024, force_wrap=True)
        for line in lyrics.splitlines():
            paginator.add_line(line)

        pages = paginator.pages
        embeds = []
        embed = discord.Embed(
            title=resp.title,
            description=resp.artist,
            colour=self.bot.main_color
        )
        embed.set_footer(text="Lyrics from genius.com")
        embed.add_field(name="\u200b", value=pages.pop(0))
        embeds += [embed]

        while pages:
            embed = discord.Embed(
                title=resp.title,
                colour=self.bot.main_color
            )
            embed.set_footer(text="Lyrics from genius.com")
            embed.add_field(name="\u200b", value=pages.pop(0))
            embeds += [embed]

        if len(embeds) == 1:
            return await ctx.send(embed=embeds[0])

        session = EmbedPaginatorSession(ctx, *embeds)
        await session.run()

    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def aboutmusic(self, ctx):
        """Shows the creator information of this music plugin"""
        embed = discord.Embed(
            description="This standalone Music Modmail plugin was created by @taku#3343.\n"
                        "Originally made for [uwubot](https://top.gg/bot/720334365661462710).",
            colour=0x8cffdb,
        )
        embed.add_field(name="Usage", value=f"To get started, request a free API URI with `{self.bot.prefix}requestapi` and once you have receive your API URI run `{self.bot.prefix}musicconfig api <APIURI>`.")
        embed.add_field(name="Donate ❤️", value="If you're feeling generous, you can donate to my Patreon at https://www.patreon.com/takubot to support this free Groovy-alternative music bot!")
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Music(bot))
