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
        return random.uniform(self._min_how_often * 60, self._max_how_often * 60)

    async def cog_load(self):
        config = await self.db.find_one({'_id': 'chatgames-config'})
        # await self.db.find_one_and_update(
        #     {'_id': 'chatgames-config', 'balance.user_id': 1234},
        #     {'$inc': {'balance.$.flowers': 4444}},
        #     upsert=True
        # )

        # await self.db.find_one_and_update(
        #     {'_id': 'chatgames-config'},
        #     {'setOnInsert': {'balance': []}},
        #     upsert=True
        # )

        if config:
            version = config.get('version')
            if version != 2:
                await self.db.delete_one({'_id': 'chatgames-config'})
                await self.db.find_one_and_update(
                    {'_id': 'chatgames-config'},
                    {'$set': {'version': 2}},
                    upsert=True
                )
            min_how_often = config.get('min_how_often') or self._min_how_often
            max_how_often = config.get('max_how_often') or self._max_how_often
            if not 0.2 <= min_how_often <= max_how_often:
                await self.db.find_one_and_update(
                    {'_id': 'chatgames-config'},
                    {'$set': {'min_how_often': None,
                              'max_how_often': None}},
                    upsert=True
                )
            else:
                self._min_how_often = min_how_often
                self._max_how_often = max_how_often

            timeout = config.get('timeout') or self.timeout
            if timeout < 1:
                await self.db.find_one_and_update(
                    {'_id': 'chatgames-config'},
                    {'$set': {'timeout': None}},
                    upsert=True
                )
            else:
                self.timeout = timeout
            enabled_channels = config.get('enabled')
            if enabled_channels:
                self.enabled_channels = {c: None for c in enabled_channels}

            for channel_id in self.enabled_channels:
                event = asyncio.Event()
                self.enabled_channels[channel_id] = (self.bot.loop.call_later(self.next_wait,
                                                                             lambda c=channel_id, e=event: asyncio.create_task(
                                                                                 self.do_event(c, e))), event)
        else:
            await self.db.find_one_and_update(
                {'_id': 'chatgames-config'},
                {'$set': {'version': 2}},
                upsert=True
            )

    def cog_unload(self):
        for channel_id in self.enabled_channels:
            if self.enabled_channels[channel_id]:
                if self.enabled_channels[channel_id][0]:
                    self.enabled_channels[channel_id][0].cancel()
                self.enabled_channels[channel_id][1].set()

    def _do_event_unscramble(self, channel):
        recent_words = self._recent_words[channel.id]
        scrambled_word = word = random.choice([w for w in WORDLIST if w not in recent_words])
        while scrambled_word == word:
            list_word = list(word)
            random.shuffle(list_word)
            scrambled_word = ''.join(list_word)
        embed = discord.Embed(
            description=f"**Unscramble!**\n\nUnscramble: `{scrambled_word}`",
            colour=self.bot.main_color
        )
        answer_embed = discord.Embed(
            description=f"**Unscramble!**\n\nUnscramble: `{scrambled_word}`\nSolution: `{word}`",
            colour=self.bot.main_color
        )
        return embed, word.casefold(), answer_embed, scrambled_word

    def _do_event_quickmath(self):
        num_operands = random.choices([2, 3, 4, 5], [60, 25, 13, 2], k=1)[0]
        operations = random.choices(['+', '-', '*'], k=num_operands-1)
        operands = random.choices(range(0, 35), k=num_operands)
        equation = list(itertools.chain.from_iterable(itertools.zip_longest(operands, operations)))[:-1]
        for i, node in enumerate(equation):
            if node == '*':
                if equation[i-1] > 10:
                    equation[i-1] %= 10
                if equation[i+1] > 10:
                    equation[i+1] %= 10

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
        return embed, answer.casefold(), answer_embed, equation

    async def do_event(self, channel_id, cancel_event):
        self.enabled_channels[channel_id] = (None, cancel_event)
        channel = self.bot.guild.get_channel(channel_id)
        if not channel or not channel.permissions_for(channel.guild.me).read_messages or not channel.permissions_for(
            channel.guild.me).send_messages or not channel.permissions_for(channel.guild.me).embed_links:
            cancel_event.set()
            del self.enabled_channels[channel_id]
            await self.db.find_one_and_update(
                {'_id': 'chatgames-config'},
                {'$set': {'enabled': list(self.enabled_channels.keys())}},
                upsert=True
            )
            return

        try:
            await self._do_event(channel)
        finally:
            if not cancel_event.is_set():
                event = asyncio.Event()
                self.enabled_channels[channel_id] = (self.bot.loop.call_later(self.next_wait,
                                                                              lambda c=channel_id,
                                                                                     e=event: asyncio.create_task(
                                                                                  self.do_event(c, e))), event)

    async def _do_event(self, channel, weight=1, event_type='random'):
        last_event_message = self._last_event_message.get(channel.id)
        if last_event_message and channel.last_message_id == last_event_message:
            return

        queue = self.current_events_queue[channel.id] = asyncio.Queue()

        if event_type == 'random':
            event_type = random.choice(['unscramble', 'quickmath'])
        if event_type == 'unscramble':
            embed, answer, answer_embed, question = self._do_event_unscramble(channel)
        elif event_type == 'quickmath':
            embed, answer, answer_embed, question = self._do_event_quickmath()
        else:
            return

        m = await channel.send(embed=embed)
        self._last_event_message[channel.id] = m.id

        winners = []
        embed.description += "\n\n"
        answer_embed.description += "\n\n"
        emojis = "🥇🥈🥉"

        start = now = time.time()
        remaining = start + self.timeout - now
        tries = collections.defaultdict(int)
        while remaining > 0 and len(winners) < 3:
            try:
                message = await asyncio.wait_for(queue.get(), remaining)
            except asyncio.TimeoutError:
                break
            now = time.time()
            remaining = min(start + self.timeout - now, remaining)
            if any(1 for w in winners if w[0] == message.author.id):
                continue
            tries[message.author.id] += 1
            if message.content.casefold() == answer:
                remaining = min(3, remaining)
                total_secs = now - start
                winners.append((message.author.id, total_secs))
                embed.description += f"{emojis[len(winners)-1]} {message.author.mention} got the correct answer in `{round(total_secs, 2)}s`!\n"
                answer_embed.description += f"{emojis[len(winners)-1]} {message.author.mention} got the correct answer in `{round(total_secs, 2)}s`!\n"
                await m.edit(embed=embed)

        if len(winners) == 0:
            answer_embed.description += "No one got it this time :(\n"
            await m.edit(embed=answer_embed)
        else:
            await m.edit(embed=answer_embed)
            data = {}
            if len(winners) >= 1:
                try:
                    data['first_place'] = {
                        "user_id": winners[0][0],
                        "tries": tries[winners[0][0]],
                        "time": winners[0][1]
                    }
                    data['second_place'] = {
                        "user_id": winners[1][0],
                        "tries": tries[winners[1][0]],
                        "time": winners[1][1]
                    }
                    data['third_place'] = {
                        "user_id": winners[2][0],
                        "tries": tries[winners[2][0]],
                        "time": winners[2][1]
                    }
                except IndexError:
                    pass
            data.setdefault('first_place', None)
            data.setdefault('second_place', None)
            data.setdefault('third_place', None)
            data['timestamp'] = m.created_at
            data['type'] = event_type
            data['question'] = question
            data['weight'] = weight
            data['channel'] = channel.id
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
            if 0.2 > value:
                return await ctx.send(f"Failed. Min value needs to be at least 12 seconds.")
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
                if self.enabled_channels[value.id][0]:
                    self.enabled_channels[value.id][0].cancel()
                self.enabled_channels[value.id][1].set()
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
                if self.enabled_channels[channel_id][0]:
                    self.enabled_channels[channel_id][0].cancel()
                self.enabled_channels[channel_id][1].set()
            event = asyncio.Event()
            self.enabled_channels[channel_id] = (self.bot.loop.call_later(self.next_wait,
                                                                          lambda c=channel_id,
                                                                                 e=event: asyncio.create_task(
                                                                              self.do_event(c, e))), event)

        await ctx.send(f"Success! Your change has been saved!")

    async def _fetch_place(self, pos, user_id=None, min_weight=1):
        if not user_id:
            name = {
                '$ne': None
            }
        else:
            name = {
                '$eq': user_id
            }

        aggr = [
            {
                '$unwind': {
                    'path': '$events'
                }
            }, {
                '$project': {
                    'name': f'$events.{pos}_place.user_id',
                    'weight': '$events.weight'
                }
            }, {
                '$match': {
                    'name': name,
                    'weight': {
                        '$gte': min_weight
                    }
                }
            }, {
                '$group': {
                    '_id': '$name',
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

    async def _fetch_all(self, user_id=None, min_weight=1):
        if not user_id:
            names = {
                '$ne': None
            }
        else:
            names = {
                '$eq': user_id
            }
        aggr = [
            {
                '$unwind': {
                    'path': '$events'
                }
            }, {
                '$project': {
                    'names': [
                        '$events.first_place.user_id', '$events.second_place.user_id', '$events.third_place.user_id'
                    ],
                    'weight': '$events.weight'
                }
            }, {
                '$unwind': {
                    'path': '$names'
                }
            }, {
                '$match': {
                    'names': names,
                    'weight': {
                        '$gte': min_weight
                    }
                }
            },  {
                '$group': {
                    '_id': '$names',
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
            docs += [(doc['_id'],  doc['count'])]
        return docs

    @staticmethod
    def records_to_value(records, default='No one!'):
        if not records:
            return default

        emoji = 0x1f947  # :first_place:
        return '\n'.join(f'{chr(emoji + i)}: <@!{r[0]}> ({r[1]} time{"s" if r[1] != 1 else ""})'
                         for i, r in enumerate(records))

    @staticmethod
    def double_records_to_value(records1, records2, default='No wins!'):
        if not (records1 or records2):
            return default
        if records1:
            records1 = records1[0]
        else:
            records1 = [records2[0][0], 0]

        if records2:
            records2 = records2[0]
        else:
            records2 = [records1[0], 0]

        return f'<@!{records1[0]}> {records1[1]} win{"s" if records1[1] != 1 else ""} ({records2[1]} ranked)'

    @commands.cooldown(1, 3)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def cgboard(self, ctx, param: typing.Union[discord.Member, discord.User, str.lower] = None):
        """
        Check the current chat game leaderboard!

        Use `{prefix}cgboard all` to see the leaderboard for all games (includes command-invoked games)
        Use `{prefix}cgboard @user/me` to see the stats for a user or yourself
        """
        if param == 'me':
            param = ctx.author

        if isinstance(param, discord.abc.User):
            user_id = param.id
            title = f"Chat games stats for {param}"
            r_first_places = await self._fetch_place('first', user_id=user_id, min_weight=1)
            r_second_places = await self._fetch_place('second', user_id=user_id, min_weight=1)
            r_third_places = await self._fetch_place('third', user_id=user_id, min_weight=1)
            r_participants = await self._fetch_all(user_id=user_id, min_weight=1)
            first_places = await self._fetch_place('first', user_id=user_id, min_weight=0)
            second_places = await self._fetch_place('second', user_id=user_id, min_weight=0)
            third_places = await self._fetch_place('third', user_id=user_id, min_weight=0)
            participants = await self._fetch_all(user_id=user_id, min_weight=0)
            embed = discord.Embed(
                title=title,
                colour=self.bot.main_color,
                timestamp=ctx.message.created_at
            )
            embed.set_footer(text=f'Requested by {ctx.author}')
            value = self.double_records_to_value(first_places, r_first_places)
            embed.add_field(name='First Places', value=value, inline=False)
            value = self.double_records_to_value(second_places, r_second_places)
            embed.add_field(name='Second Places', value=value, inline=False)
            value = self.double_records_to_value(third_places, r_third_places)
            embed.add_field(name='Third Places', value=value, inline=False)
            value = self.double_records_to_value(participants, r_participants)
            embed.add_field(name='Overall Wins', value=value, inline=False)
            return await ctx.send(embed=embed)

        if param == 'all':
            weight = 0
            title = "Chat games leaderboard!"
        else:
            weight = 1
            title = "Chat games leaderboard (ranked)!"
        first_places = await self._fetch_place('first', min_weight=weight)
        second_places = await self._fetch_place('second', min_weight=weight)
        third_places = await self._fetch_place('third', min_weight=weight)
        participants = await self._fetch_all(min_weight=weight)
        embed = discord.Embed(
            title=title,
            colour=self.bot.main_color,
            timestamp=ctx.message.created_at
        )
        embed.set_footer(text=f'Requested by {ctx.author}')
        value = self.records_to_value(first_places)
        embed.add_field(name='Top First Place Winner', value=value, inline=False)
        value = self.records_to_value(second_places)
        embed.add_field(name='Top Second Place Winner', value=value, inline=False)
        value = self.records_to_value(third_places)
        embed.add_field(name='Top Third Place Winner', value=value, inline=False)
        value = self.records_to_value(participants)
        embed.add_field(name='Most Overall Wins', value=value, inline=False)
        return await ctx.send(embed=embed)

    async def _start_game(self, ctx, event_type):
        if ctx.channel.id in self.enabled_channels and self.enabled_channels[ctx.channel.id]:
            if self.enabled_channels[ctx.channel.id][0] is None:
                return await ctx.send("There's an unfinished game still going on in this channel, "
                                      "please wait until it finishes!")
            self.enabled_channels[ctx.channel.id][0].cancel()
            self.enabled_channels[ctx.channel.id][1].set()
            self.enabled_channels[ctx.channel.id] = (None, asyncio.Event())

        try:
            await self._do_event(ctx.channel, weight=0, event_type=event_type)
        finally:
            if ctx.channel.id in self.enabled_channels:
                if not self.enabled_channels[ctx.channel.id] or not self.enabled_channels[ctx.channel.id][1].is_set():
                    event = asyncio.Event()
                    self.enabled_channels[ctx.channel.id] = (self.bot.loop.call_later(self.next_wait,
                                                                                  lambda c=ctx.channel.id,
                                                                                         e=event: asyncio.create_task(
                                                                                      self.do_event(c, e))), event)

    @commands.cooldown(1, 3)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def unscramble(self, ctx):
        """Starts a game on unscramble in the channel"""
        await self._start_game(ctx, 'unscramble')

    @commands.cooldown(1, 3)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def quickmath(self, ctx):
        """Starts a game on quick math in the channel"""
        await self._start_game(ctx, 'quickmath')

    @commands.command(hidden=True)
    @checks.has_permissions(PermissionLevel.OWNER)
    async def cgrestart(self, ctx):
        """Log out bot"""
        await ctx.send("Restarting the bot...")
        await self.bot.logout()


def setup(bot):
    bot.add_cog(ChatGames(bot))
