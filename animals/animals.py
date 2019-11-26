import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


class Animals(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=["cat"])
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

    @commands.command(aliases=["dog"])
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

    @commands.command(aliases=["fox"])
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def floof(self, ctx):
        """
        Random fox pic.

        API from randomfox.ca!
        """
        async with self.bot.session.get("https://randomfox.ca/floof/") as r:
            fox = (await r.json())["image"]
        embed = discord.Embed(title=":fox: Here come's floofy")
        embed.set_image(url=fox)
        return await ctx.channel.send(embed=embed)

    @commands.command(aliases=["shiba"])
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def shibe(self, ctx):
        """
        Random Shiba Inu pic.

        API from shibe.online!
        """
        async with self.bot.session.get("http://shibe.online/api/shibes") as r:
            shiba = (await r.json())[0]
        embed = discord.Embed(title=":dog2: Peekaboo Shiba's here!")
        embed.set_image(url=shiba)
        return await ctx.channel.send(embed=embed)


def setup(bot):
    bot.add_cog(Animals(bot))
