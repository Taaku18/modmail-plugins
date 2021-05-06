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

    @checks.has_permissions(PermissionLevel.ADMIN)
    @commands.command()
    async def parkoursetup(self, ctx, *, channel: discord.TextChannel = None):
        """
        Configure where parkour skip requests are sent to
        """
        if channel is None:
            channel = ctx.channel
        self._req_channel_id = channel.id
        await self.db.find_one_and_update(
            {'_id': 'parkour-config'},
            {'$set': {'channel_id': self._req_channel_id}},
            upsert=True
        )
        await ctx.send(f"Skip request channel set to {channel.mention}.")

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

        embed = discord.Embed(colour=discord.Colour.gold(),
                              description=f"IGN: **{ign}**\nCurrent level: **{level}**",
                              timestamp=ctx.message.created_at)
        embed.set_author(name=f"{ctx.author}'s parkour skip request")
        embed.set_footer(text="Status: pending")
        msg = await channel.send(embed=embed)
        await msg.add_reaction("\N{WHITE HEAVY CHECK MARK}")
        await msg.add_reaction("\N{CROSS MARK}")

        await self.db.find_one_and_update(
            {'_id': 'parkour-config'},
            {'$push': {'requests': {
                'msg_id': msg.id,
                'req_channel_id': ctx.channel.id,
                'user_id': ctx.author.id,
                'ign': ign,
                'level': level,
                'timestamp': ctx.message.created_at
            }}},
            upsert=True
        )

        await ctx.send(f"{ctx.author.mention} Your skip request was submitted successfully! Staff will process your request shortly.\n\nIGN: `{ign}`\nCurrent level: `{level}`")

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
            e.set_footer(text=f"Status: approved (by {payload.member})")
            text = 'approved'
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

        await channel.send(f"<@!{req['user_id']}> Your parkour skip request for `{req['ign']}` from level **{req['level']}** to **{req['level'] + 1}** has been {text}!")


def setup(bot):
    bot.add_cog(Parkour(bot))
