import asyncio
import ast
import time
import typing
import weakref
import operator as op
import os
import random
import itertools
import collections
import datetime

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


# supported operators
operators = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
             ast.Div: op.truediv, ast.USub: op.neg}

# From https://github.com/hugsy/stuff/blob/master/random-word/english-nouns.txt
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'words.txt')) as f:
    WORDLIST = set(map(lambda x: x.strip(), f.read().split('\n')))


class ChatGames(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        self._min_how_often = 5
        self._max_how_often = 15
        self.timeout = 60
        self._recent_words = collections.defaultdict(lambda: collections.deque(maxlen=50))
        self.enabled_channels = {}
        self._last_event_message = {}
        self.current_events_queue = weakref.WeakValueDictionary()

        asyncio.create_task(self.cog_load())

    @property
    def next_wait(self):
        if self._min_how_often == self._max_how_often:
            return self._min_how_often * 60
        return random.uniform(self._max_how_often * 60, self._max_how_often * 60)

    async def cog_load(self):
        config = await self.db.find_one({'_id': 'chatgames-config'})
        if config:
            min_how_often = config.get('min_how_often') or self._min_how_often
            max_how_often = config.get('max_how_often') or self._max_how_often
            timeout = config.get('timeout') or self.timeout
            if not timeout / 60 + 0.2 < min_how_often <= max_how_often:
                await self.db.find_one_and_update(
                    {'_id': 'chatgames-config'},
                    {'$set': {'min_how_often': None,
                              'max_how_often': None,
                              'timeout': None}},
                    upsert=True
                )
            else:
                self._min_how_often = min_how_often
                self._max_how_often = max_how_often
                self.timeout = timeout

            enabled_channels = config.get('enabled')
            if enabled_channels:
                self.enabled_channels = {c: None for c in enabled_channels}

            for channel_id in self.enabled_channels:
                event = asyncio.Event()
                self.enabled_channels[channel_id] = (self.bot.loop.call_later(self.next_wait,
                                                                             lambda c=channel_id, e=event: asyncio.create_task(
                                                                                 self.do_event(channel_id, e))), event)

    def cog_unload(self):
        for channel_id in self.enabled_channels:
            if self.enabled_channels[channel_id]:
                self.enabled_channels[channel_id][0].cancel()
                self.enabled_channels[channel_id][1].set()

    def _do_event_unscrabble(self, channel):
        recent_words = self._recent_words[channel.id]
        scrabbled_word = word = random.choice([w for w in WORDLIST if w not in recent_words])
        while scrabbled_word == word:
            list_word = list(word)
            random.shuffle(list_word)
            scrabbled_word = ''.join(list_word)
        embed = discord.Embed(
            description=f"**Unscrabble!**\n\nUnscrabble: `{scrabbled_word}`",
            colour=self.bot.main_color
        )
        answer_embed = discord.Embed(
            description=f"**Unscrabble!**\n\nUnscrabble: `{scrabbled_word}`\nSolution: `{word}`",
            colour=self.bot.main_color
        )
        return embed, word.casefold(), answer_embed

    def _do_event_quickmath(self):
        num_operands = random.choices([2, 3, 4, 5], [70, 20, 8, 2], k=1)[0]
        operations = random.choices(['+', '-', '*'], k=num_operands-1)
        operands = random.choices(range(0, 20), k=num_operands)
        equation = list(itertools.chain.from_iterable(itertools.zip_longest(operands, operations)))[:-1]
        for i, node in enumerate(equation):
            if node == '*':
                if equation[i-1] > 10 and equation[i+1] > 10:
                    if random.randint(1, 2) == 1:
                        equation[i-1] -= 10
                    else:
                        equation[i+1] -= 10

        equation = " ".join(map(str, equation))

        def eval_(node):
            if isinstance(node, ast.Num):  # <number>
                return node.n
            type_ = type(node.op)
            if type_ not in operators:
                raise TypeError(node)
            elif isinstance(node, ast.BinOp):  # <left> <operator> <right>
                return operators[type_](eval_(node.left), eval_(node.right))
            elif isinstance(node, ast.UnaryOp):  # <operator> <operand> e.g., -1
                return operators[type_](eval_(node.operand))

        answer = str(eval_(ast.parse(equation, mode='eval').body))
        equation = equation.replace("*", "✕").replace('-', '−')
        embed = discord.Embed(
            description=f"**Quick math!**\n\nSolve: `{equation}`",
            colour=self.bot.main_color
        )
        answer_embed = discord.Embed(
            description=f"**Quick math!**\n\nAnswer: `{equation} = {answer}`",
            colour=self.bot.main_color
        )
        return embed, answer.casefold(), answer_embed

    async def do_event(self, channel_id, cancel_event):
        channel = self.bot.guild.get_channel(channel_id)
        if not channel or not channel.permissions_for(channel.guild.me).read_messages or not channel.permissions_for(
            channel.guild.me).send_messages or not channel.permissions_for(channel.guild.me).embed_links:
            if self.enabled_channels[channel_id]:
                self.enabled_channels[channel_id][1].set()
                self.enabled_channels[channel_id][0].cancel()
            del self.enabled_channels[channel_id]
            await self.db.find_one_and_update(
                {'_id': 'chatgames-config'},
                {'$set': {'enabled': list(self.enabled_channels.keys())}},
                upsert=True
            )
            return

        try:
            await self._do_event(channel)
        except Exception:
            pass
        if not cancel_event.is_set():
            event = asyncio.Event()
            self.enabled_channels[channel_id] = (self.bot.loop.call_later(self.next_wait,
                                                                          lambda c=channel_id,
                                                                                 e=event: asyncio.create_task(
                                                                              self.do_event(channel_id, e))), event)

    async def _do_event(self, channel):
        last_event_message = self._last_event_message.get(channel.id)
        if last_event_message and channel.last_message_id == last_event_message:
            return

        queue = self.current_events_queue[channel.id] = asyncio.Queue()

        event_type = random.choice(['unscrabble', 'quickmath'])
        if event_type == 'unscrabble':
            embed, answer, answer_embed = self._do_event_unscrabble(channel)
        elif event_type == 'quickmath':
            embed, answer, answer_embed = self._do_event_quickmath()
        else:
            return

        m = await channel.send(embed=embed)
        self._last_event_message[channel.id] = m.id

        winners = []
        answer_embed.description += "\n\n"
        emojis = "🥇🥈🥉"
        start = now = time.process_time()
        while now - start <= self.timeout and len(winners) < 3:
            try:
                message = await asyncio.wait_for(queue.get(), start + self.timeout - now)
            except asyncio.TimeoutError:
                break
            now = time.process_time()
            if message.author.id in winners:
                continue
            if message.content.casefold() == answer:
                winners.append(message.author.id)
                if len(winners) <= 3:
                    total_secs = (message.created_at - m.created_at).total_seconds()
                    answer_embed.description += f"{emojis[len(winners)-1]} {message.author.mention} got the correct answer in `{round(total_secs, 2)}s`!\n"
                    await m.edit(embed=answer_embed)

        if len(winners) == 0:
            answer_embed.description += "No one got it this time :(\n"
            await m.edit(embed=answer_embed)
        else:
            data = {}
            if len(winners) >= 1:
                data['first_place'] = winners[0]
            if len(winners) >= 2:
                data['second_place'] = winners[1]
            if len(winners) >= 3:
                data['third_place'] = winners[2]
            data['participants'] = winners
            data.setdefault('first_place', None)
            data.setdefault('second_place', None)
            data.setdefault('third_place', None)
            data['timestamp'] = datetime.datetime.utcnow()
            data['type'] = event_type
            await self.db.find_one_and_update(
                {'_id': 'chatgames-config'},
                {'$push': {'events': data}},
                upsert=True
            )

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.author.bot and message.channel.id in self.current_events_queue:
            self.current_events_queue[message.channel.id].put_nowait(message)

    @commands.cooldown(1, 5)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def cgconfig(self, ctx, config: str.lower, *, value: typing.Union[discord.TextChannel, float] = None):
        """
        Configure chatgames

        Valid configs: `min`, `max`, `timeout`, `enable`, `disable`

        `min` = minimum separation in minutes between the chat game messages within a channel
        `max` = maximum separation in minutes between the chat game messages within a channel
        `timeout` = how long in seconds should users answer the question before timing out
        `enable` = enable a channel to receive chat games message
        `disable` = disable an enabled channel from receiving chat games message

        Note: `timeout` needs to be shorter than `min` by at least a minute.

        Run `{prefix}cgconfig show` to view the configs.
        """

        if config == 'show':
            enabled = ", ".join(f'<#{c}>' for c in self.enabled_channels) or "None"
            return await ctx.send(f"Min: {self._min_how_often} minute(s)\n"
                                  f"Max: {self._max_how_often} minute(s)\n"
                                  f"Timeout: {self.timeout} second(s)\n\n"
                                  f"Enabled Channels: {enabled}")
        if config == 'min':
            if not isinstance(value, float):
                return await ctx.send_help(ctx.command)
            if self.timeout / 60 + 0.2 > value:
                return await ctx.send(f"Failed. Min value needs to be at least a minute longer than timeout ({self.timeout}s).")
            if value > self._max_how_often:
                return await ctx.send(f"Failed. Min value needs to be at less than the max value ({self._max_how_often}m).")
            self._min_how_often = value
            await self.db.find_one_and_update(
                {'_id': 'chatgames-config'},
                {'$set': {'min_how_often': value}},
                upsert=True
            )
        elif config == 'max':
            if not isinstance(value, float):
                return await ctx.send_help(ctx.command)
            if value < self._min_how_often:
                return await ctx.send(f"Failed. Max value needs to be at larger than the min value ({self._min_how_often}m).")
            if value > 60*72:
                return await ctx.send("Failed. The maximum time is 3 days.")
            self._max_how_often = value
            await self.db.find_one_and_update(
                {'_id': 'chatgames-config'},
                {'$set': {'max_how_often': value}},
                upsert=True
            )
        elif config == 'timeout':
            if not isinstance(value, float):
                return await ctx.send_help(ctx.command)
            if value / 60 + 0.2 > self._min_how_often:
                return await ctx.send(f"Failed. Timeout can't to be longer than the min value ({self._min_how_often}m).")
            if value < 1:
                return await ctx.send("Failed. Timeout needs to be longer than 1 second.")
            self.timeout = value
            await self.db.find_one_and_update(
                {'_id': 'chatgames-config'},
                {'$set': {'timeout': value}},
                upsert=True
            )
        elif config == 'enable':
            if value is None:
                value = ctx.channel
            if not isinstance(value, discord.TextChannel):
                return await ctx.send_help(ctx.command)
            if value.id in self.enabled_channels:
                return await ctx.send("This channel is already enabled!")
            if not value.permissions_for(value.guild.me).read_messages or not value.permissions_for(value.guild.me).send_messages or not value.permissions_for(value.guild.me).embed_links:
                return await ctx.send("I need read, send, and embed permissions in that channel!")
            self.enabled_channels[value.id] = None
            await self.db.find_one_and_update(
                {'_id': 'chatgames-config'},
                {'$set': {'enabled': list(self.enabled_channels.keys())}},
                upsert=True
            )
        elif config == 'disable':
            if value is None:
                value = ctx.channel
            if not isinstance(value, discord.TextChannel):
                return await ctx.send_help(ctx.command)
            if value.id not in self.enabled_channels:
                return await ctx.send("This channel is not enabled!")
            if self.enabled_channels[value.id]:
                self.enabled_channels[value.id][1].set()
                self.enabled_channels[value.id][0].cancel()
            del self.enabled_channels[value.id]
            await self.db.find_one_and_update(
                {'_id': 'chatgames-config'},
                {'$set': {'enabled': list(self.enabled_channels.keys())}},
                upsert=True
            )
        else:
            return await ctx.send_help(ctx.command)

        for channel_id in self.enabled_channels:
            if self.enabled_channels[channel_id]:
                self.enabled_channels[channel_id][1].set()
                self.enabled_channels[channel_id][0].cancel()
            event = asyncio.Event()
            self.enabled_channels[channel_id] = (self.bot.loop.call_later(self.next_wait,
                                                                          lambda c=channel_id,
                                                                                 e=event: asyncio.create_task(
                                                                              self.do_event(channel_id, e))), event)

        await ctx.send(f"Success! Your change has been saved!")

    async def _fetch_place(self, pos):
        aggr = [
            {
                '$unwind': {
                    'path': '$events',
                    'preserveNullAndEmptyArrays': False
                }
            }, {
            '$group': {
                '_id': f'$events.{pos}_place',
                'count': {
                    '$sum': 1
                }
            }
        }, {
            '$sort': {
                'count': -1
            }
        }, {
            '$limit': 3
        }
        ]
        docs = []
        async for doc in self.db.aggregate(aggr):
            docs += [(doc['_id'], doc['count'])]
        return docs

    async def _fetch_all(self):
        aggr = [
            {
                '$project': {
                    'participants': '$events.participants'
                }
            }, {
            '$unwind': {
                'path': '$participants'
            }
        }, {
            '$unwind': {
                'path': '$participants'
            }
        }, {
            '$group': {
                '_id': '$participants',
                'count': {
                    '$sum': 1
                }
            }
        }, {
            '$sort': {
                'count': -1
            }
        }, {
            '$limit': 3
        }]
        docs = []
        async for doc in self.db.aggregate(aggr):
            docs += [(doc['_id'],  doc['count'])]
        return docs

    @staticmethod
    def records_to_value(records, default='No one!'):
        if not records:
            return default

        emoji = 0x1f947  # :first_place:
        return '\n'.join(f'{chr(emoji + i)}: <@!{r[0]}> ({r[1]} time{"s" if r[1] != 1 else ""})'
                         for i, r in enumerate(records))

    @commands.cooldown(1, 3)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def cgboard(self, ctx):
        """
        Check the current chat game leaderboard!
        """
        first_places = await self._fetch_place('first')
        second_places = await self._fetch_place('second')
        third_places = await self._fetch_place('third')
        participants = await self._fetch_all()
        embed = discord.Embed(
            title="Chat games leaderboard!",
            colour=self.bot.main_color,
            timestamp=ctx.message.created_at
        )
        embed.set_footer(text=f'Requested by {ctx.author}')
        value = self.records_to_value(first_places)
        embed.add_field(name='Top First PLace Winner', value=value, inline=False)
        value = self.records_to_value(second_places)
        embed.add_field(name='Top Second PLace Winner', value=value, inline=False)
        value = self.records_to_value(third_places)
        embed.add_field(name='Top Third PLace Winner', value=value, inline=False)
        value = self.records_to_value(participants)
        embed.add_field(name='Most Questions Completed', value=value, inline=False)
        return await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(ChatGames(bot))
