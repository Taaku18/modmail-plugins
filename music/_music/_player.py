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
import json
import typing
from time import time

import lavalink

import discord
from discord import TextChannel, Message

from core.models import getLogger

from .queue import Queue
from .audiotrack import LazyAudioTrack
from .exceptions import *
from .utils import *


logger = getLogger(__name__)
logger.spam = lambda *args, **kwargs: None


class Player(lavalink.BasePlayer):
    """
    Partial rewrite of lavalink's DefaultPlayer.
    """
    def __init__(self, guild_id, node):
        super().__init__(guild_id, node)
        self.guild_id: str
        self.channel_id: typing.Optional[str]
        self.ready = asyncio.Event()
        self.paused = False

        self.volume = 100
        self.equalizer = [0.0 for _ in range(15)]

        self.queue = Queue(player=self)

        self._disconnecting: typing.Optional[asyncio.TimerHandle] = None

        self._cmd_channel: typing.Optional[TextChannel] = None
        self._playing_message: typing.Optional[Message] = None

        self.main_color = discord.Colour.blurple()
        self.error_color = discord.Colour.red()

    @property
    def command_channel(self) -> typing.Optional[TextChannel]:
        if not self._cmd_channel:
            return None
        perm = self._cmd_channel.permissions_for(self._cmd_channel.guild.me)
        if not (perm.read_messages and perm.send_messages):
            logger.debug("No permission for music command channel")
            self._cmd_channel = None
        return self._cmd_channel

    @command_channel.setter
    def command_channel(self, channel: TextChannel):
        perm = channel.permissions_for(channel.guild.me)
        if perm.read_messages and perm.send_messages:
            self._cmd_channel = channel
        else:
            logger.debug("No permission for potential music command channel")

    @property
    def playing_message(self) -> typing.Optional[Message]:
        return self._playing_message

    @playing_message.setter
    def playing_message(self, value: Message):
        if self._playing_message:
            asyncio.create_task(self._playing_message.delete())
        self._playing_message = value

    async def send_playing_message(self, track):
        if not self.command_channel:
            return
        try:
            embed = discord.Embed(
                title="Now Playing",
                description=f"[{track.title}]({track.uri}) [<@!{track.requester}>]",
                colour=self.main_color
            )
            msg = await self.command_channel.send(embed=embed)
        except discord.HTTPException:
            msg = None
            logger.debug("Failed to send playing message")
        self.playing_message = msg

    @property
    def repeat(self) -> typing.Optional[str]:
        return self.queue.repeat

    @repeat.setter
    def repeat(self, value: typing.Optional[str]) -> None:
        self.queue.repeat = value

    @property
    def current(self) -> typing.Optional[LazyAudioTrack]:
        return self.queue.current

    @property
    def is_playing_a_track(self) -> bool:
        if not self.is_connected:
            return False
        return self.queue.is_playing_a_track

    @property
    def can_play_next(self) -> bool:
        return self.queue.can_play_next

    @property
    def is_connected(self) -> bool:
        return self.channel_id is not None

    @property
    def position(self) -> float:
        return self.queue.position

    @property
    def remaining(self) -> float:
        return self.queue.remaining

    def load_next_few(self) -> None:
        self.queue.load_next_few()

    # Don't want to cache too long, in case there's an update
    # noinspection PyShadowingNames
    @cache(100, ignore_kwargs=True, expires_after=21600)  # 6 hours
    async def req_lavalink_playlist(self, query):
        logger.debug(f"Fetching playlist {query}")
        retry = 3
        while retry > 0:
            resp = await self.node.get_tracks(query)
            if resp and resp.get('loadType') == 'LOAD_FAILED':
                logger.warning("Failed to fetch track for %s %s retry %s", query, resp, retry)
                retry -= 1
                continue
            break
        # noinspection PyUnboundLocalVariable
        return resp

    # noinspection PyShadowingNames
    @cache(1000, ignore_kwargs=True, expires_after=86400)  # 1 day
    async def req_lavalink_track(self, query):
        logger.debug(f"Fetching track {query}")
        retry = 3
        while retry > 0:
            resp = await self.node.get_tracks(query)
            if resp and resp.get('loadType') == 'LOAD_FAILED':
                logger.warning("Failed to fetch track for %s %s retry %s", query, resp, retry)
                retry -= 1
                continue
            break
        # noinspection PyUnboundLocalVariable
        return resp

    async def play_next(self, start_time: int = 0, end_time: int = 0, no_replace: bool = False, force: bool = False) \
            -> typing.Optional[LazyAudioTrack]:
        self.cancel_tasks()
        try:
            return await self.queue.play_next(start_time=start_time, end_time=end_time,
                                              no_replace=no_replace, force=force)
        except EndOfQueue:
            await self.queue.stop()
            return None

    async def play_current(self, start_time: int = 0, end_time: int = 0, no_replace: bool = False) \
            -> typing.Optional[LazyAudioTrack]:
        self.cancel_tasks()
        try:
            return await self.queue.play_current(start_time=start_time, end_time=end_time, no_replace=no_replace)
        except EndOfQueue:
            await self.queue.stop()
            return None

    async def play_later(self, track: LazyAudioTrack, send_queue_message=True) -> None:
        self.cancel_tasks()
        if not self.is_playing_a_track:
            self.queue.add(track)
            await self.play_next()
        else:
            self.queue.add(track)
            if send_queue_message and self.command_channel:
                await track.load(self)
                if track.success:
                    try:
                        embed = discord.Embed(
                            description=f"Queued [{track.title}]({track.uri}) [<@!{track.requester}>]",
                            colour=self.main_color
                        )
                        await self.command_channel.send(embed=embed)
                    except discord.HTTPException:
                        logger.debug("Failed to send queue message.")

    async def play_previous(self, start_time: int = 0, end_time: int = 0, no_replace: bool = False) \
            -> typing.Optional[LazyAudioTrack]:
        self.cancel_tasks()
        try:
            return await self.queue.play_previous(start_time=start_time, end_time=end_time, no_replace=no_replace)
        except EndOfQueue:
            await self.queue.stop()
            return None

    async def shuffle(self) -> None:
        await self.queue.shuffle()

    async def set_pause(self, pause: bool):
        logger.debug("Setting pause to %s", pause)
        # noinspection PyProtectedMember
        await self.node._send(op='pause', guildId=self.guild_id, pause=pause)
        self.paused = pause

    async def set_volume(self, vol: int):
        logger.debug("Setting volume to %s", vol)
        self.volume = max(min(vol, 1000), 0)
        # noinspection PyProtectedMember
        await self.node._send(op='volume', guildId=self.guild_id, volume=self.volume)

    async def seek(self, position: int):
        logger.debug("Setting pos to %s", position)
        # noinspection PyProtectedMember
        await self.node._send(op='seek', guildId=self.guild_id, position=position)

    async def fastforward(self, seconds: float) -> None:
        if not self.is_playing_a_track:
            return None
        ms = seconds * 1000
        new_pos = int(self.position + ms)
        if new_pos >= self.current.duration:
            await self.play_next()
        else:
            await self.seek(new_pos)
            await self._update_state({'position': new_pos, 'time': time()})

    async def rewind(self, seconds: float) -> None:
        if not self.is_playing_a_track:
            return None
        ms = seconds * 1000
        new_pos = max(int(self.position - ms), 0)
        await self.seek(new_pos)
        await self._update_state({'position': new_pos, 'time': time()})

    async def _handle_event(self, event: lavalink.Event) -> None:
        if isinstance(event, lavalink.TrackStartEvent):
            self.cancel_tasks()
            await self.send_playing_message(event.track)
        elif isinstance(event, lavalink.TrackStuckEvent):
            track = event.track
            logger.warning("Music bot stuck %s @ %sms", track, event.threshold)
            if self.command_channel:
                try:
                    embed = discord.Embed(
                        description=f"An error has occurred while playing this track: [{track.title}]({track.uri})",
                        colour=self.error_color
                    )
                    await self.command_channel.send(embed=embed)
                except discord.HTTPException:
                    logger.debug("Failed to send music error message.")
        elif isinstance(event, lavalink.events.TrackExceptionEvent):
            track = event.track
            logger.warning("Music bot error %s %s", event.exception, track)
            if self.command_channel:
                try:
                    embed = discord.Embed(
                        description=f"An error has occurred while playing this track: [{track.title}]({track.uri})",
                        colour=self.error_color
                    )
                    await self.command_channel.send(embed=embed)
                except discord.HTTPException:
                    logger.debug("Failed to send music error message.")

            # very very ugly code
            if self.node.available:
                # noinspection PyBroadException
                try:
                    await asyncio.sleep(2)  # lavalink might still respond to ping for 2s after term
                    # noinspection PyProtectedMember
                    await self.node._ws._ws._writer.ping()
                except Exception:
                    logger.debug("Failed ping test", exc_info=True)
                    # noinspection PyProtectedMember
                    if self.node._ws._ws._pong_response_cb is not None:
                        # noinspection PyProtectedMember
                        self.node._ws._ws._pong_response_cb.cancel()
                    # noinspection PyProtectedMember
                    self.node._ws._ws._pong_not_received()

            logger.debug("Node is still available? %s", self.node.available)
            if not self.node.available:
                logger.debug("Reconnecting soon...")
                asyncio.create_task(self.play_current(start_time=int(self.position)))
                return
            if self.repeat == "track":
                self.repeat = None

        if isinstance(event, (lavalink.TrackStuckEvent, lavalink.TrackExceptionEvent)) \
                or (isinstance(event, lavalink.TrackEndEvent) and event.reason in {'FINISHED', 'LOAD_FAILED'}):
            asyncio.create_task(self.play_next())

    async def _update_state(self, state: dict) -> None:
        await self.queue.update_state(state)

    async def change_node(self, node: lavalink.Node) -> None:
        if self.node.available:
            # noinspection PyProtectedMember
            await self.node._send(op='destroy', guildId=self.guild_id)

        logger.debug("Changing nodes for player %s", self)
        old_node = self.node
        self.node = node

        if self._voice_state:
            await self._dispatch_voice_update()

        if self.current:
            await self.play_current(start_time=int(self.position))
            if self.paused:
                await self.set_pause(True)

        if self.volume != 100:
            await self.set_volume(self.volume)

        if any(self.equalizer):  # If any bands of the equalizer was modified
            payload = [{'band': b, 'gain': g} for b, g in enumerate(self.equalizer)]
            # noinspection PyProtectedMember
            await self.node._send(op='equalizer', guildId=self.guild_id, bands=payload)

        # noinspection PyProtectedMember
        await self.node._dispatch_event(lavalink.NodeChangedEvent(self, old_node, node))

    async def _voice_server_update(self, data):
        logger.spam("Processing server state update... %s", data)
        current_region = self._voice_state.get('event', {}).get('endpoint')
        changed_region = current_region and current_region != data.get('endpoint')
        await super()._voice_server_update(data)
        if changed_region and self.is_playing_a_track:
            logger.debug("Processing server region change...")
            paused = self.paused
            position = int(self.position)
            await self.queue.stop()

            await self.play_current(start_time=position)
            if paused:
                await self.set_pause(True)

    async def _voice_state_update(self, data):
        self._voice_state.update({
            'sessionId': data['session_id']
        })

        logger.spam("Processing voice state update... %s", data)

        channel_switch = self.channel_id and data['channel_id'] and \
            self.channel_id != data['channel_id'] and self.is_playing_a_track
        if channel_switch:
            position = int(self.position)
            paused = self.paused
            await self.queue.stop()

        self.channel_id = data['channel_id']

        if not self.channel_id:  # We're disconnecting
            logger.debug('Disconnecting from %s...', self.guild_id)
            self._voice_state.clear()
            # noinspection PyBroadException
            await self.queue.stop()
            logger.debug("Clear queue for %s", self.guild_id)
            await self.queue.clear()
            if self.volume != 100:
                await self.set_volume(100)
            if self._disconnecting:
                self._disconnecting.cancel()
            self.queue.repeat = None
            self.playing_message = None
            self._disconnecting = None
            return

        await self._dispatch_voice_update()

        if channel_switch:
            # noinspection PyUnboundLocalVariable
            await self.play_current(start_time=position)
            # noinspection PyUnboundLocalVariable
            if paused:
                await self.set_pause(True)

    async def _dispatch_voice_update(self):
        if {'sessionId', 'event'} == self._voice_state.keys():
            self.ready.set()
        return await super()._dispatch_voice_update()

    async def disconnect(self, bot) -> None:
        if not self.is_connected or self.is_playing_a_track:
            if self.is_playing_a_track:
                vc = bot.get_channel(int(self.channel_id))
                if not vc or any(not m.bot for m in vc.members):
                    logger.debug("Not disconnecting for %s", self.guild_id)
                    return
                else:
                    logger.warning("Disconnecting because there's no one left in vc!")
                    if self.command_channel:
                        try:
                            embed = discord.Embed(
                                description="I left vc because there's no one left!",
                                colour=self.error_color
                            )
                            await self.command_channel.send(embed=embed)
                        except discord.HTTPException:
                            pass

        logger.debug("Disconnect %s", self.guild_id)
        # TODO: shard
        self._disconnecting = None
        # noinspection PyProtectedMember
        ws = bot._connection._get_websocket(int(self.guild_id))
        await ws.voice_state(int(self.guild_id), None)

    def disconnect_soon(self, bot) -> None:
        if self._disconnecting or not self.is_connected:
            return
        logger.debug("Scheduling disconnect for %s", self.guild_id)
        self._disconnecting = bot.loop.call_later(60*10, lambda: asyncio.create_task(self.disconnect(
            bot
        )))

    def cancel_tasks(self) -> None:
        if self._disconnecting:
            self._disconnecting.cancel()
            self._disconnecting = None

    def dump(self, jsonify=False):
        data = dict(
            channel_id=self.channel_id,
            paused=self.paused,
            volume=self.volume,
            equalizer=self.equalizer,
            queue=self.queue.dump(),
            _cmd_channel_id=self._cmd_channel.id if self._cmd_channel else None,
            _playing_message_id=self._playing_message.id if self._playing_message else None,
            node_name=self.node.name
        )
        return json.dumps(data) if jsonify else data

    @classmethod
    async def load_dump(cls, bot, guild_id, node, data):
        if isinstance(data, str):
            data = json.loads(data)

        _cmd_channel_id = data['_cmd_channel_id']
        if _cmd_channel_id:
            _cmd_channel = bot.get_channel(_cmd_channel_id)
            if _cmd_channel is None:
                try:
                    _cmd_channel = await bot.fetch_channel(_cmd_channel_id)
                except discord.HTTPException:
                    _cmd_channel = None
        else:
            _cmd_channel = None

        _playing_message_id = data['_playing_message_id']
        if _playing_message_id and _cmd_channel:
            try:
                _playing_message = await _cmd_channel.fetch_message(_playing_message_id)
            except discord.HTTPException:
                _playing_message = None
        else:
            _playing_message = None

        self = bot.lavalink.player_manager.create(guild_id, node=node)
        # noinspection PyProtectedMember
        ws = bot._connection._get_websocket(guild_id)
        await ws.voice_state(guild_id, int(data['channel_id']))
        self._cmd_channel = _cmd_channel
        self._playing_message = _playing_message
        self.queue = Queue.load_dump(self, data['queue'])
        self.volume = data['volume']
        paused = self.paused = data['paused']
        self.equalizer = data['equalizer']
        logger.debug("Waiting for ready... %s", guild_id)
        await self.ready.wait()
        if self.is_playing_a_track:
            logger.debug("Restarting player for %s", guild_id)
            await self.play_current(start_time=self.position)
            if paused:
                await self.set_pause(True)

        if self.volume != 100:
            await self.set_volume(self.volume)
        return self
