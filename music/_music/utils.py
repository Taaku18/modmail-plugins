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
import inspect
import time
import typing
from functools import wraps

from cachetools import LRUCache

import discord
from discord.ext import commands


__all__ = ['cache', 'trim', 'seconds_to_time_string', 'plural', 'Str',
           'PaginatorSession', 'WrappedPaginator', 'EmbedPaginatorSession']


def _wrap_and_store_coroutine(cache_, key, coro):
    async def func():
        value = await coro
        cache_[key] = (value, time.time())
        return value
    return func()


def _wrap_new_coroutine(value):
    async def new_coroutine():
        return value
    return new_coroutine()


def _true_repr(o):
    if o.__class__.__repr__ is object.__repr__:
        return f'<{o.__class__.__module__}.{o.__class__.__name__}>'
    return repr(o)


def cache(maxsize=2048, ignore_kwargs=False, *, expires_after=None):
    def decorator(func):
        _internal_cache = LRUCache(maxsize)

        def _make_key(args, kwargs):
            key = [f'{func.__module__}.{func.__name__}']
            key.extend(_true_repr(o) for o in args)
            if not ignore_kwargs:
                for k, v in kwargs.items():
                    key.append(f"{_true_repr(k)}\x01{_true_repr(v)}")
            return '\x02'.join(key)

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = _make_key(args, kwargs)
            try:
                value, created_at = _internal_cache[key]
            except KeyError:
                pass
            else:
                if expires_after and time.time() - created_at >= expires_after:
                    try:
                        del _internal_cache[key]
                    except KeyError:
                        pass
                else:
                    if asyncio.iscoroutinefunction(func):
                        return _wrap_new_coroutine(value)
                    return value

            value = func(*args, **kwargs)

            if inspect.isawaitable(value):
                return _wrap_and_store_coroutine(_internal_cache, key, value)

            _internal_cache[key] = (value, time.time())
            return value
        return wrapper
    return decorator


def trim(s, max_length):
    if len(s) <= max_length:
        return s
    return s[:max_length-3] + '...'


# noinspection PyPep8Naming
class plural:
    def __init__(self, value, show_count=True):
        self.value = value
        self.show_count = show_count

    def __format__(self, format_spec):
        v = self.value
        singular, sep, p = format_spec.partition('|')
        p = p or f'{singular}s'
        if not self.show_count:
            return p if abs(v) != 1 else singular
        if abs(v) != 1:
            return f'{v} {p}'
        return f'{v} {singular}'


def seconds_to_time_string(total_seconds, *, int_seconds=False, format=1):
    days = int(total_seconds // 86400)
    rest = total_seconds % 86400
    hours = int(rest // 3600)
    rest = rest % 3600
    minutes = int(rest // 60)
    seconds = rest % 60
    if days == hours == minutes == 0 and not int_seconds:
        seconds = round(seconds, 1)
        if seconds == 0:
            seconds = 1
    else:
        seconds = int(seconds)

    # noinspection PyShadowingNames
    time = ""
    if format == 1:
        if days:
            time += f"{plural(days):day} "
        if hours:
            time += f"{plural(hours):hour} "
        if minutes:
            time += f"{plural(minutes):minute} "
        if seconds or not time:
            time += f"{plural(seconds):second}"
    elif format == 2:
        if days:
            time += f"{plural(days): day}, "
        if days or hours:
            time += f"{hours: >2}:"
            time += f"{minutes:0>2}:"
        else:
            time += f"{minutes: >2}:"
        time += f"{seconds:0>2}"
    else:
        if days:
            time += f"{days}d "
        if hours:
            time += f"{hours}h "
        if minutes:
            time += f"{minutes}m "
        if seconds or not time:
            time += f"{seconds}s"
    return time.rstrip()


class Str(commands.Converter):
    trans_quo = str.maketrans({'“': '"', '”': '"'})

    def __init__(self, remove_code=False, lower=False):
        self.remove_code = remove_code
        self.lower = lower

    # noinspection PyUnusedLocal
    async def convert(self, ctx, argument: str):
        argument = argument.strip().translate(self.trans_quo)
        while argument.startswith('"') and argument.endswith('"'):
            argument = argument[1:-1]
        if self.remove_code:
            while argument.startswith('`') and argument.endswith('`'):
                argument = argument[1:-1]
        if self.lower:
            argument = argument.lower()
        return argument


class PaginatorSession:
    def __init__(self, ctx: commands.Context, *pages, **options):
        self.ctx = ctx
        self.timeout: int = options.get("timeout", 210)
        self.max_timeout = 600
        self.running = False
        self.handle = ctx.bot.loop.call_later(self.max_timeout, self.cancel)

        self.base: typing.Optional[discord.Message] = None
        self.current = 0
        self.pages = list(pages)
        self.destination = options.get("destination", ctx)
        self.reaction_map = {
            "⏮": self.first_page,
            "◀": self.previous_page,
            "▶": self.next_page,
            "⏭": self.last_page,
        }

    def cancel(self):
        self.running = False

    def add_page(self, item) -> None:

        if isinstance(item, str):
            self.pages.append(item)
        else:
            raise TypeError("Page must be a str object.")

    async def create_base(self, item) -> None:
        await self._create_base(item)

        if len(self.pages) == 1:
            self.running = False
            return

        self.running = True
        for reaction in self.reaction_map:
            if len(self.pages) == 2 and reaction in "⏮⏭":
                continue
            await self.base.add_reaction(reaction)

    async def _create_base(self, item) -> None:
        self.base = await self.destination.send(item, allowed_mentions=discord.AllowedMentions.none())

    async def show_page(self, index: int) -> None:
        if not 0 <= index < len(self.pages):
            return

        self.current = index
        page = self.pages[index]

        if self.running:
            await self._show_page(page)
        else:
            await self.create_base(page)

    async def _show_page(self, page):
        await self.base.edit(content=page)

    def react_check(self, reaction: discord.Reaction, user: discord.User) -> bool:
        return (
            reaction.message.id == self.base.id
            and user.id == self.ctx.author.id
            and reaction.emoji in self.reaction_map.keys()
        )

    async def run(self):
        if not self.running:
            await self.show_page(self.current)
        while self.running:
            try:
                reaction, user = await self.ctx.bot.wait_for(
                    "reaction_add", check=self.react_check, timeout=self.timeout
                )
            except asyncio.TimeoutError:
                break
            if not self.running:
                break
            action = self.reaction_map.get(reaction.emoji)
            await action()
            try:
                await self.base.remove_reaction(reaction, user)  # TODO: Add check
            except discord.HTTPException:
                pass

        self.handle.cancel()
        try:
            await self.base.clear_reactions()
        except discord.HTTPException:
            pass

    async def previous_page(self) -> None:
        await self.show_page(self.current - 1)

    async def next_page(self) -> None:
        await self.show_page(self.current + 1)

    async def first_page(self) -> None:
        await self.show_page(0)

    async def last_page(self) -> None:
        await self.show_page(len(self.pages) - 1)


class WrappedPaginator(commands.Paginator):
    def __init__(self, *args, wrap_on=('\n', ' '), include_wrapped=True, force_wrap=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.wrap_on = wrap_on
        self.include_wrapped = include_wrapped
        self.force_wrap = force_wrap

    def add_line(self, line='', *, empty=False):
        true_max_size = self.max_size - self._prefix_len - self._suffix_len - 2
        original_length = len(line)

        while len(line) > true_max_size:
            search_string = line[0:true_max_size - 1]
            wrapped = False

            for delimiter in self.wrap_on:
                position = search_string.rfind(delimiter)

                if position > 0:
                    super().add_line(line[0:position], empty=empty)
                    wrapped = True

                    if self.include_wrapped:
                        line = line[position:]
                    else:
                        line = line[position + len(delimiter):]

                    break

            if not wrapped:
                if self.force_wrap:
                    super().add_line(line[0:true_max_size - 1])
                    line = line[true_max_size - 1:]
                else:
                    raise ValueError(
                        f"Line of length {original_length} had sequence of {len(line)} characters"
                        f" (max is {true_max_size}) that WrappedPaginator could not wrap with"
                        f" delimiters: {self.wrap_on}"
                    )

        super().add_line(line, empty=empty)


class EmbedPaginatorSession(PaginatorSession):
    def __init__(self, ctx: commands.Context, *embeds, **options):
        super().__init__(ctx, *embeds, **options)

        if len(self.pages) > 1:
            for i, embed in enumerate(self.pages):
                footer_text = f"Page {i + 1} of {len(self.pages)}"
                if embed.footer.text:
                    footer_text = footer_text + " • " + embed.footer.text
                embed.set_footer(text=footer_text, icon_url=embed.footer.icon_url)

    def add_page(self, item: discord.Embed) -> None:
        if isinstance(item, discord.Embed):
            self.pages.append(item)
        else:
            raise TypeError("Page must be an Embed object.")

    async def _create_base(self, item: discord.Embed) -> None:
        self.base = await self.destination.send(embed=item)

    async def _show_page(self, page):
        await self.base.edit(embed=page)
