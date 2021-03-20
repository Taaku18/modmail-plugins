import asyncio
import datetime

import discord
from discord import utils
from discord.ext import commands


class ReactionLogger(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.webhook: discord.Webhook = None
        asyncio.create_task(self.cog_load())

    async def cog_load(self):
        await self.bot.wait_until_ready()
        channel = utils.get(self.bot.guild.text_channels, name='reaction-logs')
        if not channel:
            channel = next((c for c in self.bot.guild.text_channels if 'reaction-logs' in (c.topic or '')), None)

        if not channel:
            if not self.bot.guild.me.guild_permissions.manage_channels:
                print("I don't have permissions to manage channels")
                self.bot.remove_cog("ReactionLogger")
                return
            channel = await self.bot.guild.create_text_channel(
                "reaction-logs",
                topic="reaction-logs (don't change this)",
                overwrites={
                    self.bot.guild.me: discord.PermissionOverwrite(read_messages=True),
                    self.bot.guild.default_role: discord.PermissionOverwrite(read_messages=False)
                },
                reason="Reaction Logger!")

        if channel.guild.id != self.bot.guild.id:
            print("Channel ID not in guild ID")
            self.bot.remove_cog("ReactionLogger")
            return
        if not isinstance(channel, discord.TextChannel):
            print("Channel ID is not a text channel")
            self.bot.remove_cog("ReactionLogger")
            return

        if not channel.permissions_for(channel.guild.me).manage_webhooks:
            print("I don't have permissions to manage webhooks in the channel")
            self.bot.remove_cog("ReactionLogger")
            return

        try:
            self.webhook = utils.get(await channel.webhooks(), name='Reaction Logger')
            if not self.webhook:
                self.webhook = await channel.create_webhook(name='Reaction Logger',
                                                            avatar=await self.bot.user.avatar_url.read(),
                                                            reason='Reaction Logger!')
                print("made webhook")
        except Exception as e:
            print("Something went wrong...", e)
            self.bot.remove_cog("ReactionLogger")
            return

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if not self.webhook:
            return
        if payload.guild_id != self.bot.guild.id:
            return
        user: discord.Member = payload.member
        if user.bot:
            return
        channel: discord.TextChannel = self.bot.get_channel(payload.channel_id)
        message: discord.PartialMessage = channel.get_partial_message(payload.message_id)
        emoji: discord.PartialEmoji = payload.emoji
        if emoji.is_custom_emoji():
            emoji_text = f"`:{emoji.name}:`"
        else:
            emoji_text = str(emoji)

        embed = discord.Embed(
            description=f"**Message:** [Jump!](https://discord.com/channels/{channel.guild.id}/{channel.id}/{message.id}) ({channel.mention})\n",
            colour=0xffd1df,
        )
        embed.timestamp = datetime.datetime.utcnow()

        try:
            if emoji.is_custom_emoji():
                embed.set_author(name=f"Reaction added by {user}")
                embed.description += f"**Emoji name:** {emoji_text}\n"
                embed.set_thumbnail(url=str(emoji.url))
            else:
                embed.set_author(name=f"Reaction added by {user}")
                embed.description += f"**Emoji:** {emoji_text}\n"
        except Exception:
            embed.set_author(name=f"Reaction added by {user}")
            embed.description += f"**Emoji name:** {emoji_text} (emoji can't be found)\n"

        embed.set_footer(text=f"User ID: {user.id}\n"
                              f"Channel ID: {channel.id}\n"
                              f"Message ID: {message.id}")
        await self.webhook.send(embed=embed)


def setup(bot):
    bot.add_cog(ReactionLogger(bot))
