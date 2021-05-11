"""This is a server specific plugin, adding to your bot doesn't do anything"""

import asyncio
import typing

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


class Parkour(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        self._req_channel_id = None
        self._ping_role_id = None
        asyncio.create_task(self.cog_load())

    async def cog_load(self):
        config = await self.db.find_one({'_id': 'parkour-config'})
        if config:
            channel_id = config.get('channel_id')
            if channel_id:
                self._req_channel_id = int(channel_id)
                if not self.bot.get_channel(self._req_channel_id):
                    try:
                        await self.bot.fetch_channel(self._req_channel_id)
                    except discord.HTTPException:
                        print("unsetting channel id")
                        await self.db.find_one_and_update(
                            {'_id': 'parkour-config'},
                            {'$set': {'channel_id': None}},
                            upsert=True
                        )
                        self._req_channel_id = None
            self._ping_role_id = config.get('role_id')
            if self._ping_role_id:
                self._ping_role_id = int(self._ping_role_id)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @commands.command(aliases=['parkourconfig'])
    async def parkoursetup(self, ctx, *, channel_or_role: typing.Union[discord.TextChannel, discord.Role] = None):
        """
        Configure where parkour skip requests are sent to and the staff ping role
        """
        if channel_or_role is None:
            channel_or_role = ctx.channel
        if isinstance(channel_or_role, discord.TextChannel):
            self._req_channel_id = channel_or_role.id
            await self.db.find_one_and_update(
                {'_id': 'parkour-config'},
                {'$set': {'channel_id': self._req_channel_id}},
                upsert=True
            )
            await ctx.send(f"Skip request channel set to {channel_or_role.mention}.")
        else:
            self._ping_role_id = channel_or_role.id
            await self.db.find_one_and_update(
                {'_id': 'parkour-config'},
                {'$set': {'role_id': self._ping_role_id}},
                upsert=True
            )
            await ctx.send(f"Staff ping role set to {channel_or_role.name}.")

    @checks.has_permissions(PermissionLevel.REGULAR)
    @commands.command(aliases=['parkourcoords'])
    async def pcoords(self, ctx, *, level: str.lower):
        """Get the cords of a parkour level

        Level 1-176, start, end
        Floor 1: 1-63
        Floor 2: 64-118
        Floor 3: 119-176
        """
        if not level.isdigit():
            if level not in {'start', 'end'}:
                return await ctx.send("Not a valid level!")
            level = -1 if level == 'start' else -2
        else:
            level = int(level)
            if not 1 <= level <= 176:
                return await ctx.send("There's only 1-176 levels!")
        if level == -1:
            return await ctx.send("The start coords is:\n```\n/tp 41 97 -35```")
        elif level == -2:
            return await ctx.send("The end coords is:\n```\n/tp -43 125 -26```")
        if 1 <= level < 64:
            y = 97
        elif 64 <= level < 119:
            y = 109
        else:
            y = 127

        level_offset = 0
        if level >= 99:
            level_offset += 1
        if level >= 158:
            level_offset += 1
        if level >= 171:
            level_offset += 3

        if 1 <= level < 64:
            x = 41 - 12 * ((level + level_offset) // 8)
        elif 64 <= level < 119:
            x = 40 - 14 * ((level + level_offset - 64) // 8)
        else:
            x = 41 - 12 * ((level + level_offset - 119) // 8)

        if level < 119:
            if ((level + level_offset) // 8) % 2 == 0:
                z = -36 + 12 * ((level + level_offset) % 8)
            else:
                z = 60 - 12 * ((level + level_offset) % 8)
        else:
            if ((level + level_offset) // 8) % 2 != 0:
                z = -36 + 12 * ((level + level_offset) % 8)
            else:
                z = 60 - 12 * ((level + level_offset) % 8)

        if level in {64, 119}:
            z += 1

        return await ctx.send(f"The coords for level **{level}** is:\n```\n/tp {x} {y} {z}```")

    async def has_open_req(self, ign, requester_id=None):
        aggr = [
            {
                '$match': {
                    '_id': 'parkour-config'
                }
            }, {
                '$project': {
                    'requests': {
                        '$filter': {
                            'input': '$requests',
                            'as': 'request',
                            'cond': {
                                '$eq': [
                                    '$$request.ign', ign.lower()
                                ]
                            }
                        }
                    },
                    '_id': 0
                }
            }, {
                '$unwind': {
                    'path': '$requests'
                }
            }, {
                '$sort': {
                    'requests.timestamp': -1
                }
            }, {
                '$limit': 1
            }
        ]
        req = None
        async for doc in self.db.aggregate(aggr):
            req = doc
            break

        if not req or not req['requests']:
            return False
        if requester_id and requester_id != int(req['requests']['user_id']):
            return None

        msg_id = int(req['requests']['msg_id'])
        channel = self.bot.get_channel(self._req_channel_id)
        if not channel:
            try:
                await self.bot.fetch_channel(self._req_channel_id)
            except discord.HTTPException:
                print("unsetting channel id")
                await self.db.find_one_and_update(
                    {'_id': 'parkour-config'},
                    {'$set': {'channel_id': None}},
                    upsert=True
                )
                self._req_channel_id = None
                return False

        try:
            message = await channel.fetch_message(msg_id)
        except discord.HTTPException:
            return False
        for rxn in message.reactions:
            if str(rxn) == "\N{WHITE HEAVY CHECK MARK}":
                if discord.utils.get(await rxn.users().flatten(), id=self.bot.user.id):
                    break
        else:
            print("Already resolved")
            return False
        return message

    async def get_past_skips(self, ign):
        aggr = [
            {
                '$match': {
                    '_id': 'parkour-config'
                }
            }, {
                '$project': {
                    'requests': {
                        '$filter': {
                            'input': '$requests',
                            'as': 'request',
                            'cond': {
                                '$eq': [
                                    '$$request.ign', ign.lower()
                                ]
                            }
                        }
                    },
                    '_id': 0
                }
            }, {
                '$project': {
                    'requests': {
                        '$size': '$requests'
                    }
                }
            }
        ]
        req = None
        async for doc in self.db.aggregate(aggr):
            req = doc
            break

        return req['requests']

    @checks.has_permissions(PermissionLevel.REGULAR)
    @commands.command(name="reqskip", aliases=['requestskip', 'skiprequest', 'skipreq'])
    @commands.cooldown(1, 15)
    async def request_skip(self, ctx, ign: str = None, level: typing.Union[int, str] = None):
        """Request a weewoo parkour skip if you're stuck on a level

        Abusing this command will result in a mute.
        """
        if not self._req_channel_id:
            return await ctx.send("Parkour skip requests isn't setup yet.")

        channel = self.bot.get_channel(self._req_channel_id)
        if not channel:
            try:
                await self.bot.fetch_channel(self._req_channel_id)
            except discord.HTTPException:
                print("unsetting channel id")
                await self.db.find_one_and_update(
                    {'_id': 'parkour-config'},
                    {'$set': {'channel_id': None}},
                    upsert=True
                )
                self._req_channel_id = None
                return await ctx.send("Parkour skip requests isn't setup yet.")

        if not ign or isinstance(level, str):
            def _check(m):
                if m.author.id != ctx.author.id or m.channel.id != ctx.channel.id:
                    return False
                if m.content.lower() == 'cancel':
                    raise ValueError
                if not m.content:
                    return False
                return True

            try:
                embed = discord.Embed(description="What is your IGN?", colour=self.bot.main_color)
                await ctx.send(embed=embed)
                m = await ctx.bot.wait_for('message', check=_check, timeout=60)
                ign = m.content
            except ValueError:
                await ctx.send(f'{ctx.author.mention} Cancelled.')
                return
            except asyncio.TimeoutError:
                await ctx.send(f'{ctx.author.mention} Timed out.')
                return

        if not isinstance(level, int) or level <= 0:
            def _check(m):
                if m.author.id != ctx.author.id or m.channel.id != ctx.channel.id:
                    return False
                if m.content.lower() == 'cancel':
                    raise ValueError
                if not m.content.isdigit():
                    return False
                return True

            try:
                embed = discord.Embed(description="Which level are you stuck on?", colour=self.bot.main_color)
                await ctx.send(embed=embed)
                m = await ctx.bot.wait_for('message', check=_check, timeout=60)
                level = int(m.content)
            except ValueError:
                await ctx.send(f'{ctx.author.mention} Cancelled.')
                return
            except asyncio.TimeoutError:
                await ctx.send(f'{ctx.author.mention} Timed out.')
                return

        if not 0 < level <= 176:
            return await ctx.send("There are only 176 levels!")
        if level == 176:
            return await ctx.send("You're already on the last level!")

        if await self.has_open_req(ign):
            return await ctx.send(f"There is already a pending skip request for {ign}!")

        embed = discord.Embed(colour=discord.Colour.gold(),
                              description=f"IGN: **{ign}**\nCurrent level: **{level}**",
                              timestamp=ctx.message.created_at)

        past_skips = await self.get_past_skips(ign)

        embed.set_author(name=f"{ctx.author}'s #{past_skips+1} parkour skip request")
        embed.set_footer(text="Status: pending")
        if self._ping_role_id:
            msg = await channel.send(f"<@&{self._ping_role_id}>", embed=embed)
        else:
            msg = await channel.send(embed=embed)
        await msg.add_reaction("\N{WHITE HEAVY CHECK MARK}")
        await msg.add_reaction("\N{CROSS MARK}")

        await self.db.find_one_and_update(
            {'_id': 'parkour-config'},
            {'$push': {'requests': {
                'msg_id': msg.id,
                'req_channel_id': ctx.channel.id,
                'user_id': ctx.author.id,
                'ign': ign.lower(),
                'level': level,
                'type': 'skip',
                'timestamp': ctx.message.created_at
            }}},
            upsert=True
        )

        await ctx.send(
            f"{ctx.author.mention} Your skip request was submitted successfully. Staff will process your request shortly!\n\nIGN: `{ign}`\nCurrent level: `{level}`")

    @checks.has_permissions(PermissionLevel.REGULAR)
    @commands.command(name="reqjump", aliases=['requestjump', 'jumprequest', 'jumpreq'])
    @commands.cooldown(1, 15)
    async def request_jump(self, ctx, ign: str = None):
        """Request a jump to a different weewoo parkour level

        Abusing this command will result in a mute.
        """
        if not self._req_channel_id:
            return await ctx.send("Parkour skip requests isn't setup yet.")

        channel = self.bot.get_channel(self._req_channel_id)
        if not channel:
            try:
                await self.bot.fetch_channel(self._req_channel_id)
            except discord.HTTPException:
                print("unsetting channel id")
                await self.db.find_one_and_update(
                    {'_id': 'parkour-config'},
                    {'$set': {'channel_id': None}},
                    upsert=True
                )
                self._req_channel_id = None
                return await ctx.send("Parkour skip requests isn't setup yet.")

        if not ign:
            def _check(m):
                if m.author.id != ctx.author.id or m.channel.id != ctx.channel.id:
                    return False
                if m.content.lower() == 'cancel':
                    raise ValueError
                if not m.content:
                    return False
                return True

            try:
                embed = discord.Embed(description="What is your IGN?", colour=self.bot.main_color)
                await ctx.send(embed=embed)
                m = await ctx.bot.wait_for('message', check=_check, timeout=60)
                ign = m.content
            except ValueError:
                await ctx.send(f'{ctx.author.mention} Cancelled.')
                return
            except asyncio.TimeoutError:
                await ctx.send(f'{ctx.author.mention} Timed out.')
                return

        def _check(m):
            if m.author.id != ctx.author.id or m.channel.id != ctx.channel.id:
                return False
            if m.content.lower() == 'cancel':
                raise ValueError
            if not m.content.isdigit():
                return False
            return True

        try:
            embed = discord.Embed(description="Which level are you currently on?", colour=self.bot.main_color)
            await ctx.send(embed=embed)
            m = await ctx.bot.wait_for('message', check=_check, timeout=60)
            current_level = int(m.content)
        except ValueError:
            await ctx.send(f'{ctx.author.mention} Cancelled.')
            return
        except asyncio.TimeoutError:
            await ctx.send(f'{ctx.author.mention} Timed out.')
            return

        try:
            embed = discord.Embed(description="Which level do you want to jump to?", colour=self.bot.main_color)
            await ctx.send(embed=embed)
            m = await ctx.bot.wait_for('message', check=_check, timeout=60)
            target_level = int(m.content)
        except ValueError:
            await ctx.send(f'{ctx.author.mention} Cancelled.')
            return
        except asyncio.TimeoutError:
            await ctx.send(f'{ctx.author.mention} Timed out.')
            return

        if not (0 < current_level <= 176 and 0 < target_level <= 176):
            return await ctx.send("There are only 176 levels!")
        if current_level == 176:
            return await ctx.send("You're already on the last level!")
        if current_level >= target_level:
            return await ctx.send("Destination level needs to be after your current level!")
        if current_level + 1 == target_level:
            return await ctx.send(f"Use the `{self.bot.prefix}reqskip` command to request a skip!")

        def _check(m):
            if m.author.id != ctx.author.id or m.channel.id != ctx.channel.id:
                return False
            if m.content.lower() == 'cancel':
                raise ValueError
            if not m.content:
                return False
            return True

        try:
            embed = discord.Embed(description="Why are you requesting this jump?", colour=self.bot.main_color)
            await ctx.send(embed=embed)
            m = await ctx.bot.wait_for('message', check=_check, timeout=60)
            reason = m.content
        except ValueError:
            await ctx.send(f'{ctx.author.mention} Cancelled.')
            return
        except asyncio.TimeoutError:
            await ctx.send(f'{ctx.author.mention} Timed out.')
            return

        if len(reason) > 1500:
            return await ctx.send(f'{ctx.author.mention} Reason too long.')

        if await self.has_open_req(ign):
            return await ctx.send(f"There is already a pending skip request for {ign}!")

        embed = discord.Embed(colour=discord.Colour.gold(),
                              description=f"IGN: **{ign}**\nCurrent level: **{current_level}**\nDestination level: **{target_level}**\nReason: {reason}",
                              timestamp=ctx.message.created_at)
        past_skips = await self.get_past_skips(ign)

        embed.set_author(name=f"{ctx.author}'s #{past_skips + 1} parkour jump request")
        embed.set_footer(text="Status: pending")
        if self._ping_role_id:
            msg = await channel.send(f"<@&{self._ping_role_id}>", embed=embed)
        else:
            msg = await channel.send(embed=embed)
        await msg.add_reaction("\N{WHITE HEAVY CHECK MARK}")
        await msg.add_reaction("\N{CROSS MARK}")

        await self.db.find_one_and_update(
            {'_id': 'parkour-config'},
            {'$push': {'requests': {
                'msg_id': msg.id,
                'req_channel_id': ctx.channel.id,
                'user_id': ctx.author.id,
                'ign': ign.lower(),
                'level': current_level,
                'target_level': target_level,
                'type': 'jump',
                'reason': reason,
                'timestamp': ctx.message.created_at
            }}},
            upsert=True
        )

        await ctx.send(
            f"{ctx.author.mention} Your jump request was submitted successfully. Staff will process your request shortly!\n\nIGN: `{ign}`\nCurrent level: `{current_level}`\nDestination level: `{target_level}`")

    @checks.has_permissions(PermissionLevel.REGULAR)
    @commands.command(name="reqcancel", aliases=['requestcancel', 'cancelrequest', 'cancelreq'])
    @commands.cooldown(1, 15)
    async def request_cancel(self, ctx, ign: str = None):
        """Cancel a skip or jump request

        Abusing this command will result in a mute.
        """
        if not self._req_channel_id:
            return await ctx.send("Parkour skip requests isn't setup yet.")

        channel = self.bot.get_channel(self._req_channel_id)
        if not channel:
            try:
                await self.bot.fetch_channel(self._req_channel_id)
            except discord.HTTPException:
                print("unsetting channel id")
                await self.db.find_one_and_update(
                    {'_id': 'parkour-config'},
                    {'$set': {'channel_id': None}},
                    upsert=True
                )
                self._req_channel_id = None
                return await ctx.send("Parkour skip requests isn't setup yet.")

        if not ign:
            def _check(m):
                if m.author.id != ctx.author.id or m.channel.id != ctx.channel.id:
                    return False
                if m.content.lower() == 'cancel':
                    raise ValueError
                if not m.content:
                    return False
                return True

            try:
                embed = discord.Embed(description="What is your IGN?", colour=self.bot.main_color)
                await ctx.send(embed=embed)
                m = await ctx.bot.wait_for('message', check=_check, timeout=60)
                ign = m.content
            except ValueError:
                await ctx.send(f'{ctx.author.mention} Cancelled.')
                return
            except asyncio.TimeoutError:
                await ctx.send(f'{ctx.author.mention} Timed out.')
                return

        message = await self.has_open_req(ign, ctx.author.id)
        if not message:
            if message is None:
                return await ctx.send(f"You did not start the skip request for {ign}.")
            return await ctx.send("You have no pending skip request.")
        e = message.embeds[0]
        e.colour = discord.Colour.red()
        e.set_footer(text=f"Status: cancelled")

        await message.edit(embed=e)
        await message.clear_reactions()
        return await ctx.send("Your latest skip request has been cancelled.")

    @checks.has_permissions(PermissionLevel.REGULAR)
    @commands.command(aliases=['pastrequests'])
    async def pastreqs(self, ctx, *, ign):
        """Get the past parkour skip requests for an IGN"""
        if not self._req_channel_id:
            return await ctx.send("Parkour skip requests isn't setup yet.")

        channel = self.bot.get_channel(self._req_channel_id)
        if not channel:
            try:
                await self.bot.fetch_channel(self._req_channel_id)
            except discord.HTTPException:
                print("unsetting channel id")
                await self.db.find_one_and_update(
                    {'_id': 'parkour-config'},
                    {'$set': {'channel_id': None}},
                    upsert=True
                )
                self._req_channel_id = None
                return await ctx.send("Parkour skip requests isn't setup yet.")

        if ctx.channel.id != self._req_channel_id:
            return await ctx.send(f"This is a staff only command and this command only works in {channel.mention}.")

        aggr = [
            {
                '$match': {
                    '_id': 'parkour-config'
                }
            }, {
                '$project': {
                    'requests': {
                        '$filter': {
                            'input': '$requests',
                            'as': 'request',
                            'cond': {
                                '$eq': [
                                    '$$request.ign', ign.lower()
                                ]
                            }
                        }
                    },
                    '_id': 0
                }
            }
        ]
        req = None
        async for doc in self.db.aggregate(aggr):
            req = doc
            break

        past_req_urls = [channel.get_partial_message(int(r['msg_id'])).jump_url for r in req['requests']]
        past_req_urls = [f"[**Jump #{i}**]({url})" for i, url in enumerate(past_req_urls, start=1)]

        embed = discord.Embed(description="\n".join(past_req_urls) or "No past requests", colour=self.bot.main_color)
        embed.set_author(name=f"{ign}'s past requests")
        embed.set_footer(text=f"Total {len(past_req_urls)} requests")
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.channel_id != self._req_channel_id or payload.user_id == self.bot.user.id:
            return
        if str(payload.emoji) not in {"\N{WHITE HEAVY CHECK MARK}", "\N{CROSS MARK}"}:
            return
        if payload.event_type != 'REACTION_ADD':
            return

        aggr = [
            {
                '$match': {
                    '_id': 'parkour-config'
                }
            }, {
                '$project': {
                    'requests': {
                        '$filter': {
                            'input': '$requests',
                            'as': 'request',
                            'cond': {
                                '$eq': [
                                    '$$request.msg_id', payload.message_id
                                ]
                            }
                        }
                    },
                    '_id': 0
                }
            }
        ]

        req = None
        async for doc in self.db.aggregate(aggr):
            req = doc
            break

        if not req:
            return
        req = req['requests'][0]

        channel = self.bot.get_channel(self._req_channel_id)
        if not channel:
            try:
                await self.bot.fetch_channel(self._req_channel_id)
            except discord.HTTPException:
                print("unsetting channel id")
                await self.db.find_one_and_update(
                    {'_id': 'parkour-config'},
                    {'$set': {'channel_id': None}},
                    upsert=True
                )
                self._req_channel_id = None
                return

        message = await channel.fetch_message(payload.message_id)
        for rxn in message.reactions:
            if str(rxn) == "\N{WHITE HEAVY CHECK MARK}":
                if discord.utils.get(await rxn.users().flatten(), id=self.bot.user.id):
                    break
        else:
            print("Already resolved")
            return

        if str(payload.emoji) == "\N{WHITE HEAVY CHECK MARK}":
            e = message.embeds[0]
            e.colour = discord.Colour.green()
            e.set_footer(text=f"Status: resolved (by {payload.member})")
            text = 'completed'
        else:
            e = message.embeds[0]
            e.colour = discord.Colour.red()
            e.set_footer(text=f"Status: denied (by {payload.member})")
            text = 'denied'

        await message.edit(embed=e)
        await message.clear_reactions()

        channel = self.bot.get_channel(req['req_channel_id'])
        if not channel:
            try:
                await self.bot.fetch_channel(req['req_channel_id'])
            except discord.HTTPException:
                channel = self.bot.get_user(req['user_id'])
                if not channel:
                    return
                await channel.create_dm()

        type = req.get('type')
        if not type:
            type = 'skip'

        target = req.get('target_level')
        if not target:
            target = req['level'] + 1

        await channel.send(
            f"<@!{req['user_id']}> Your parkour {type} request for `{req['ign']}` from level **{req['level']}** to **{target}** has been **{text}**!")


def setup(bot):
    bot.add_cog(Parkour(bot))
