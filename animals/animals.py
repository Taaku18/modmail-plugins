import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


class Animals(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def meow(self, ctx):
        """
        Random cat pic.

        API from random.cat, more coming soon!
        """
        async with self.bot.session.get("http://aws.random.cat/meow") as r:
            cat = (await r.json())["file"]
        embed = discord.Embed(title=":cat: ~meow~")
        embed.set_image(url=cat)
        return await ctx.channel.send(embed=embed)

    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def woof(self, ctx):
        """
        Random dog pic.

        API from random.dog, more coming soon!
        """
        async with self.bot.session.get("https://random.dog/woof.json?filter=mp3") as r:
            dog = (await r.json())["url"]
        embed = discord.Embed(title=":dog: ~woof~")
        embed.set_image(url=dog)
        return await ctx.channel.send(embed=embed)


def setup(bot):
    bot.add_cog(Animals(bot))
