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
import difflib
import json
import random
import time
import typing
from typing import List

import lavalink

import discord

from .audiotrack import LazyAudioTrack
from .exceptions import EndOfQueue, QueueError
from .utils import *

from core.models import getLogger

__all__ = ['Queue']

logger = getLogger(__name__)
logger.spam = lambda *args, **kwargs: None


class Queue:
    def __init__(self, player):
        self.player = player
        self.cursor = 0

        self.repeat: typing.Optional[str] = None
        self._queue: List[LazyAudioTrack] = []
        self._current = None
        self._stopped = True

        self._last_update = 0
        self._last_position = 0
        self.position_timestamp = 0

    @property
    def can_play_next(self):
        cursor = self.cursor + 1 if self.current and self.repeat != 'track' else self.cursor
        if cursor >= len(self._queue):
            return self.repeat == 'queue' and self._queue
        return True

    async def clear(self):
        self.cursor = 0
        self._queue.clear()
        if self.repeat == 'track':
            self.repeat = None
        self._current = None
        await self.stop()

    @property
    def current(self) -> typing.Optional[LazyAudioTrack]:
        return self._current

    @property
    def is_playing_a_track(self) -> bool:
        logger.spam("Is playing track %s %s", self._stopped, self._current)
        return not self._stopped and self._current

    @property
    def position(self) -> float:
        if not self.is_playing_a_track:
            return 0

        if self.player.paused:
            return min(self._last_position, self.current.duration)

        difference = time.time() * 1000 - self._last_update  # should be less than 5
        if difference > 15:
            # TODO: do smt when it somehow disconnects
            logger.debug("Something is wrong here...")
        current_playing_time = self._last_position + difference
        return min(current_playing_time, self.current.duration)

    @property
    def remaining(self):
        if not self.is_playing_a_track:
            return -1
        return self.current.duration - self.position

    async def _play(self, *, start_time, end_time, no_replace) -> LazyAudioTrack:
        self.load_next_few()
        track = self._queue[self.cursor]
        if not track.loaded or not track.success:
            logger.error("Shouldn't be here!")
            raise ValueError("Should be loaded and success here")

        options = {}
        if start_time:
            if 0 > start_time or start_time > track.duration:
                raise QueueError("start_time can't be less than 0 or longer than the track's duration")
            options['startTime'] = start_time

        if end_time:
            if 0 > end_time or end_time > track.duration:
                raise QueueError("end_time can't be less than 0 or longer than the track's duration")
            options['endTime'] = end_time

        if no_replace:
            options['noReplace'] = no_replace

        self._stopped = False
        self._current = track
        self.position_timestamp = time.time()
        self._last_update = self.position_timestamp * 1000
        self._last_position = start_time

        # noinspection PyProtectedMember
        if not self.player.node._manager.available_nodes:
            logger.debug("No available nodes to play this track, waiting...")
            if self.player.command_channel:
                try:
                    embed = discord.Embed(
                        description="Music API is currently down, will try to re-connect for the next few minutes...",
                        colour=self.player.error_color
                    )
                    await self.player.command_channel.send(embed=embed)
                except discord.HTTPException:
                    logger.debug("Failed to send cmd message")
            # wait at most 5 minutes
            retry = 60 * 5 // 2
            # noinspection PyProtectedMember
            while retry > 0 and not self.player.node._manager.available_nodes:
                await asyncio.sleep(2)
                retry -= 1
            # noinspection PyProtectedMember
            if not self.player.node._manager.available_nodes:
                logger.warning("Failed to resume track at node disconnect")
                raise EndOfQueue

        self.player.paused = False
        # noinspection PyProtectedMember
        await self.player.node._send(op='play', guildId=self.player.guild_id, track=track.track, **options)
        event = lavalink.TrackStartEvent(self.player, track)
        # noinspection PyProtectedMember
        await asyncio.gather(
            self.player.node._dispatch_event(event),
            self.player._handle_event(event)
        )
        return track

    def _reset_stats(self):
        self._last_update = 0
        self._last_position = 0
        self.position_timestamp = 0

    async def _load_next(self, load=5, *, start_from=None) -> int:
        cursor = start_from if start_from else \
            (self.cursor + 1 if self.current and self.repeat != 'track' else self.cursor)
        loaded = 0

        while loaded < load and cursor < len(self._queue):
            track = self._queue[cursor]
            cursor += 1
            try:
                await track.load(self.player)
            except Exception as e:
                logger.warning("Unknown error while loading track %s", e)
                continue
            if track.success:
                loaded += 1

        for i in range(min(3, len(self._queue))):
            if not self._queue[i].loaded:
                try:
                    await self._queue[i].load(self.player)
                except Exception as e:
                    logger.warning("Unknown error while loading music %s", e)
                    continue
        return loaded

    def load_next_few(self):
        asyncio.create_task(self._load_next())

    async def play_next(self, start_time: int = 0, end_time: int = 0,
                        no_replace: bool = False, force: bool = False) -> LazyAudioTrack:
        self._reset_stats()
        playable = False
        cursor = self.cursor + 1 if (self.current and self.repeat != 'track') or force else self.cursor

        while not playable:
            if not self._queue:
                logger.debug("Ended queue pos %s %s", cursor, self._queue)
                # noinspection PyProtectedMember
                await self.player.node._dispatch_event(lavalink.QueueEndEvent(self.player))
                raise EndOfQueue

            if cursor >= len(self._queue):
                if self.repeat != 'queue':
                    logger.debug("Ended queue pos %s %s", cursor, self._queue)
                    # noinspection PyProtectedMember
                    await self.player.node._dispatch_event(lavalink.QueueEndEvent(self.player))
                    raise EndOfQueue
                cursor = 0

            current = self._queue[cursor]
            if not current.loaded:
                await current.load(self.player)
            if not current.success:
                if self.player.command_channel:
                    try:
                        embed = discord.Embed(
                            description=f"Failed to load track **{current.title}**, skipping...",
                            colour=self.player.error_color,
                        )
                        await self.player.command_channel.send(embed=embed)
                    except discord.HTTPException:
                        logger.debug("Command channel not found.")
                logger.debug("removing track from queue %s", current)
                try:
                    self._queue.remove(current)
                except ValueError:
                    # not sure why
                    logger.debug("Failed to remove track from queue %s %s", current, self._queue)
            else:
                playable = True

        self.cursor = cursor
        return await self._play(start_time=start_time, end_time=end_time, no_replace=no_replace)

    async def play_current(self, start_time: int = 0, end_time: int = 0, no_replace: bool = False) -> LazyAudioTrack:
        self._current = None
        return await self.play_next(start_time, end_time, no_replace)

    async def play_previous(self, start_time: int = 0, end_time: int = 0, no_replace: bool = False) \
            -> LazyAudioTrack:
        if self.cursor > 0 and not self._stopped:
            self.cursor -= 1
        playable = False
        while not playable:
            if not self._queue:
                # noinspection PyProtectedMember
                await self.player.node._dispatch_event(lavalink.QueueEndEvent(self.player))
                raise EndOfQueue

            if self.cursor >= len(self._queue):
                self.cursor = len(self._queue) - 1

            current = self._queue[self.cursor]
            if not current.loaded:
                await current.load(self.player)
            if not current.success:
                if self.player.command_channel:
                    try:
                        embed = discord.Embed(
                            description=f"Failed to load track **{current.title}**, skipping...",
                            colour=self.player.error_color
                        )
                        await self.player.command_channel.send(embed=embed)
                    except discord.HTTPException:
                        logger.debug("Command channel not found.")
                logger.debug("removing track from queue %s", current)
                self._queue.remove(current)
            else:
                playable = True

        return await self._play(start_time=start_time, end_time=end_time, no_replace=no_replace)

    def add(self, track: LazyAudioTrack) -> None:
        self._queue.append(track)

    def remove(self, track: LazyAudioTrack) -> None:
        try:
            self._queue.remove(track)
        except ValueError:
            pass

    async def stop(self) -> None:
        if not self._stopped:
            self._reset_stats()
            self._stopped = True
            # noinspection PyBroadException
            try:
                if self.player.node.available:
                    # noinspection PyProtectedMember
                    await self.player.node._send(op='stop', guildId=self.player.guild_id)
                else:
                    logger.warning("ws not available to send stop")
            except Exception:
                logger.warning("ws not available to send stop", exc_info=True)

    async def update_state(self, state: dict):
        self._last_update = time.time() * 1000
        self._last_position = state.get('position', 0)
        self.position_timestamp = state.get('time', 0)

        event = lavalink.events.PlayerUpdateEvent(self.player, self._last_position, self.position_timestamp)
        # noinspection PyProtectedMember
        await self.player.node._dispatch_event(event)

    async def shuffle(self) -> None:
        random.shuffle(self._queue)
        self.cursor = 0
        paused = self.player.paused
        if self.repeat == 'track':
            self.repeat = None
        await self.play_current()
        if paused:
            await self.player.set_pause(True)

    def _match_pos_from_name(self, name: str) -> typing.Optional[int]:
        old_song_or_pos = name.casefold()
        queue_tracks = {}
        for pos, track in enumerate(self._queue):
            queue_tracks.setdefault(track.query.casefold().split(':', 1)[-1], pos)
            queue_tracks.setdefault(track.title.casefold(), pos)
        logger.debug("Matching %s from %s", name, queue_tracks)
        song = difflib.get_close_matches(old_song_or_pos, queue_tracks.keys(), n=1, cutoff=0.5)
        if song:
            return queue_tracks[song[0]]
        return None

    async def move(self, old_song_or_pos: str, new_pos: int) \
            -> typing.Union[str, typing.Tuple[LazyAudioTrack, int]]:
        new_pos -= 1
        if new_pos >= len(self._queue):
            new_pos = len(self._queue) - 1

        if old_song_or_pos.strip().isdigit():
            pos = int(old_song_or_pos.strip()) - 1
        else:
            pos = self._match_pos_from_name(old_song_or_pos)
            if pos is None:
                return f'No track matches your search **{old_song_or_pos}**, use the position number instead!'

        if pos < 0 or pos >= len(self._queue):
            return f"There's no track at position **{pos + 1}** in queue!"
        if pos == new_pos:
            return f"**{self._queue[pos].title}** is already at position **{pos + 1}**!"

        self._queue.insert(new_pos, self._queue.pop(pos))
        if self.cursor == pos:
            paused = self.player.paused
            await self.play_current()
            if paused:
                await self.player.set_pause(True)

        elif pos < self.cursor <= new_pos:
            self.cursor -= 1
        elif pos > self.cursor >= new_pos:
            self.cursor += 1

        return self._queue[new_pos], new_pos + 1

    async def jump(self, track_or_pos: str) -> typing.Union[str, typing.Tuple[LazyAudioTrack, int]]:
        if track_or_pos.strip().isdigit():
            pos = int(track_or_pos.strip()) - 1
        else:
            pos = self._match_pos_from_name(track_or_pos)
            if pos is None:
                return f'No track matches your search **{track_or_pos}**, use the position number instead!'
        if pos < 0 or pos >= len(self._queue):
            return f"There's no track at position **{pos + 1}** in queue!"
        if pos == self.cursor:
            return f"I'm already playing **{self._queue[pos].title}** at position **{pos + 1}**!"
        self.cursor = pos
        paused = self.player.paused
        await self.play_current()
        if paused:
            await self.player.set_pause(True)
        return self._queue[pos], pos + 1

    async def remove_range(self, start: int, end: int) -> typing.Union[str, int]:
        if start < 0 or start >= end or end > len(self._queue):
            return "Invalid start / end range!"
        self._queue = self._queue[:start] + self._queue[end:]
        diff = max(min(self.cursor - start, end - start), 0)
        removed = start <= self.cursor < end
        if diff:
            self.cursor -= diff
        if removed:
            paused = self.player.paused
            try:
                await self.play_current()
            except EndOfQueue:
                await self.stop()
                self.cursor = max(len(self._queue) - 1, 0)
            else:
                if paused:
                    await self.player.set_pause(True)
        return end - start

    async def remove_track(self, pos_track_or_range: str) \
            -> typing.Union[str, typing.Optional[typing.Tuple[LazyAudioTrack, int]]]:
        track_range = pos_track_or_range.split('-', maxsplit=1)
        if len(track_range) == 2 and track_range[0].strip().isdigit() and track_range[1].strip().isdigit():
            return await self.remove_range(int(track_range[0].strip()) - 1, int(track_range[1].strip()))
        if pos_track_or_range.strip().isdigit():
            pos = int(pos_track_or_range.strip()) - 1
        else:
            pos = self._match_pos_from_name(pos_track_or_range)
            if pos is None:
                return f'No track matches your search **{pos_track_or_range}**, ' \
                       f'use the position number instead!'
        if pos < 0 or pos >= len(self._queue):
            return f"There's no track at position **{pos + 1}** in queue!"
        removed = self._queue.pop(pos)
        logger.debug("Removing track %s at %s cursor %s", removed, pos, self.cursor)
        if pos == self.cursor:
            paused = self.player.paused
            try:
                await self.play_current()
            except EndOfQueue:
                await self.stop()
                self.cursor = max(len(self._queue) - 1, 0)
            else:
                if paused:
                    await self.player.set_pause(True)
        elif pos < self.cursor:
            self.cursor -= 1
        return removed, pos + 1

    @property
    def rendered(self) -> typing.Tuple[typing.List[str], typing.Optional[int]]:
        prefix = "```nim\n"
        suffix = "\n```"
        track_per_page = 10

        if not self._queue:
            return [f"{prefix}The queue is empty...{suffix}"], None

        messages = []
        current_page = None

        total_tracks = len(self._queue)

        count_length = 1
        if total_tracks >= 10:
            count_length += 1

        for i, track in enumerate(self._queue, start=1):
            if (i-1) % track_per_page == 0:
                messages += [""]

            if i == 91 and total_tracks >= 100:
                count_length += 1

            block_max_title_length = max(30, len(max(
                self._queue[(i - 1) // track_per_page * track_per_page:
                            (i - 1) // track_per_page * track_per_page + track_per_page],
                key=lambda x: len(x.title)).title))
            title_length = min(39 - count_length, block_max_title_length)
            title = trim(track.title, title_length).ljust(title_length)

            if track == self.current and self.player.is_playing_a_track:
                repeat = ' (loop)' if self.repeat == 'track' else ''
                left = seconds_to_time_string(self.remaining / 1000, int_seconds=True, format=2)
                messages[-1] += f"{' ' * (count_length + 3)}⬐ current track{repeat}\n" \
                                f"{i: >{count_length}}) {title} {left} left\n" \
                                f"{' ' * (count_length + 3)}⬑ current track{repeat}\n"
                current_page = (i-1) // track_per_page
            else:
                if hasattr(track, 'duration'):
                    duration = seconds_to_time_string(track.duration / 1000,
                                                      int_seconds=True, format=2)
                else:
                    duration = "  ???"
                messages[-1] += f"{i: >{count_length}}) {title} {duration}\n"

            remaining_tracks = total_tracks - i
            if i % track_per_page == 0 and remaining_tracks > 0:
                messages[-1] += f"\n{' ' * count_length}{remaining_tracks} more " \
                                f"{plural(remaining_tracks, show_count=False):track}"

        messages[-1] += "\n"
        if self.repeat == 'queue':
            messages[-1] += f"{' ' * (count_length + 2)}This queue is on a loop!"
        else:
            messages[-1] += f"{' ' * (count_length + 2)}This is the end of the queue!"
        for i in range(len(messages)):
            messages[i] = prefix + messages[i].replace('```', '``\u200b`').replace('@', '@\u200b') + suffix
        return messages, current_page

    def __len__(self):
        return len(self._queue)

    def __iter__(self):
        return self._queue.__iter__()

    def dump(self, jsonify=False):
        tracks = [track.dump() for track in self._queue]

        data = dict(
            tracks=tracks,
            cursor=self.cursor,
            repeat=self.repeat,
            has_current=self._current is not None,
            _stopped=self._stopped,
            position=self.position
        )
        return json.dumps(data) if jsonify else data

    @classmethod
    def load_dump(cls, player, data):
        logger.debug("Loading queue from dump %s", data)
        if isinstance(data, str):
            data = json.loads(data)

        self = cls(player)
        self.cursor = data['cursor']
        self.repeat = data['repeat']
        self._queue = [LazyAudioTrack.load_dump(track) for track in data['tracks']]
        self._current = self._queue[self.cursor] if data['has_current'] else None
        self._stopped = data['_stopped']
        self._last_position = data['position']
        self.position_timestamp = time.time()
        self._last_update = self.position_timestamp * 1000
        return self
