import typing

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


class Giveaway(commands.Cog):
    """
    A giveaway plugin.
    """

    def __init__(self, bot):
        self.bot = bot

    @commands.command(usage='<duration> [channel] [reaction] "<prize>"')
    @checks.has_permissions(PermissionLevel.SUPPORTER)
    async def giveaway(self, ctx, duration: typing.Union[int, str], channel: typing.Optional[discord.TextChannel],
                       reaction: typing.Optional[str], prize: str):
        """
        Giveaway!!!

        Usage
        -----
        duration: the duration of the giveaway in seconds or in ISO-8601 Duration Format https://en.wikipedia.org/wiki/ISO_8601#Durations.
        channel: optional, a channel mention or ID of a channel, leave blank for the current channel.
        reaction: optional, the reaction of the giveaway, leave blank for all reactions.
        prize: a phrase to send when the giveaway concludes, you may use `{name}`, `{mention}`, `{nick}`, `{id}` as substitute variables for their corrisponding attibutes of the user.
        """



def setup(bot):
    bot.add_cog(Giveaway(bot))
