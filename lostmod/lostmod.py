import asyncio

import discord
from discord import Embed
from discord.ext import commands
from discord.utils import get

from core import checks
from core.models import PermissionLevel


class Lost(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.in_progress = set()
        self.db = bot.plugin_db.get_partition(self)
        self.event_channel = None
        self.trade_channel = None
        bot.loop.create_task(self.get_configs())

    async def get_configs(self):
        config = await self.db.find_one({'_id': 'lost-config'}) or {}
        self.event_channel = config.get('event_channel')
        self.trade_channel = config.get('trade_channel')

    @commands.command(name='seteventchannel')
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def set_event_channel(self, ctx, *, channel: discord.TextChannel = None):
        """
        Set the event channel.
        """
        self.event_channel = channel.id if channel is not None else None
        await self.db.find_one_and_update(
            {'_id': 'lost-config'},
            {'$set': {'event_channel': self.event_channel}},
            upsert=True
        )
        if self.event_channel is None:
            embed = Embed(title='Success',
                          description='You have unset the event channel.',
                          color=self.bot.main_color)
        else:
            embed = Embed(title='Success',
                          description=f'The event channel is now set to {channel.mention}.',
                          color=self.bot.main_color)
        return await ctx.send(embed=embed)

    @commands.command(name='settradechannel')
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def set_trade_channel(self, ctx, *, channel: discord.TextChannel = None):
        """
        Set the trade channel.
        """
        self.trade_channel = channel.id if channel is not None else None
        await self.db.find_one_and_update(
            {'_id': 'lost-config'},
            {'$set': {'trade_channel': self.trade_channel}},
            upsert=True
        )
        if self.trade_channel is None:
            embed = Embed(title='Success',
                          description='You have unset the trade channel.',
                          color=self.bot.main_color)
        else:
            embed = Embed(title='Success',
                          description=f'The trade channel is now set to {channel.mention}.',
                          color=self.bot.main_color)
        return await ctx.send(embed=embed)

    async def request(self, ctx, msg, options=None, lower=True):
        def check_message(m):
            if m.content.strip().lower() == 'cancel':
                raise asyncio.TimeoutError
            return m.author == ctx.author

        embed = Embed(description=msg, color=self.bot.main_color)
        embed.set_footer(text='Type "cancel" anytime to cancel, timeout: 2 minutes.')
        await ctx.send(embed=embed)

        for i in range(3):
            try:
                m = await self.bot.wait_for('message', check=check_message, timeout=120)
                content = m.content.strip()
                if lower:
                    content = content.lower()
            except asyncio.TimeoutError:
                embed = Embed(description=f'Timed out or cancelled.',
                              color=self.bot.error_color)
                await ctx.send(embed=embed)
                return None

            if options is not None:
                if content not in options:
                    if i < 2:
                        embed = Embed(title='Error',
                                      description=f'Invalid option, try again.',
                                      color=self.bot.error_color)
                        await ctx.send(embed=embed)
                    continue
                await m.add_reaction('✅')
                return content
            await m.add_reaction('✅')
            return content

        embed = Embed(description=f'Too many retries, aborting.',
                      color=self.bot.error_color)
        await ctx.send(embed=embed)
        return None

    @commands.group()
    async def trade(self, ctx):
        """
        Start a trade offer. Will ping @Trader role.
        """
        if ctx.author.id in self.in_progress:
            return

        if self.trade_channel is None:
            embed = Embed(title='Error',
                          description=f'No trade channels has been set, '
                                      f'set one with `{self.bot.prefix}settradechannel`.',
                          color=self.bot.error_color)
            return await ctx.send(embed=embed)

        role = get(ctx.guild.roles, name='Trader')

        channel = self.bot.get_channel(self.trade_channel)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(self.trade_channel)
            except discord.NotFound:
                self.trade_channel = None
                await self.db.find_one_and_update(
                    {'_id': 'lost-config'},
                    {'$set': {'trade_channel': self.trade_channel}},
                    upsert=True
                )
                embed = Embed(title='Error',
                              description=f'The current trade channel is invalid, '
                                          f'set a new one with `{self.bot.prefix}settradechannel`.',
                              color=self.bot.error_color)
                return await ctx.send(embed=embed)

        self.in_progress.add(ctx.author.id)

        r = await self.request(ctx, 'Are you buying or selling (b/s)?',
                               {'1', '2', 'buying', 'selling', 'b', 's', 'buy', 'sell'})
        if r is None:
            self.in_progress.remove(ctx.author.id)
            return

        if r == '1' or r.startswith('b'):
            mode = 'buying'
        else:
            mode = 'selling'

        r = await self.request(ctx, f'What are you {mode}?')
        if r is None:
            self.in_progress.remove(ctx.author.id)
            return

        item = r

        r = await self.request(ctx, f'How much are you willing to offer?')
        if r is None:
            self.in_progress.remove(ctx.author.id)
            return

        price = r

        r = await self.request(ctx, f'Additional info:')
        if r is None:
            self.in_progress.remove(ctx.author.id)
            return

        info = r

        r = await self.request(ctx, f'What is your IGN?', lower=False)
        if r is None:
            self.in_progress.remove(ctx.author.id)
            return

        name = r

        ping = False
        if role is not None:
            r = await self.request(ctx, f'Do you want to ping the {role.mention} role (y/n)?', {'y', 'n', 'yes', 'no'})
            if r is None:
                self.in_progress.remove(ctx.author.id)
                return
            ping = r.startswith('y')

        embed = Embed(title=f'{name}\'s {mode.capitalize()} Deal',
                      color=self.bot.main_color)

        embed.add_field(name=mode.capitalize(), value=item)
        embed.add_field(name='Price Offer', value=price)
        embed.add_field(name='Additional Info', value=info)

        embed.set_footer(text=f'Trade started by {ctx.author.name}#{ctx.author.discriminator}.')

        if ping:
            await channel.send(role.mention, embed=embed)
        else:
            await channel.send(embed=embed)
        self.in_progress.remove(ctx.author.id)

        embed = Embed(title='Successfully sent trade offer!', color=self.bot.main_color)
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Lost(bot))
