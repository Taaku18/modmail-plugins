from itertools import zip_longest
from urllib.parse import quote

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel
from core.paginator import EmbedPaginatorSession, MessagePaginatorSession
from core import utils


class Animals(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.plugin_db.get_partition(self)
        self.meowkey = None
        bot.loop.create_task(self.fetch_meowkey())

    async def fetch_meowkey(self):
        config = await self.db.find_one({'_id': 'animals-config'})
        self.meowkey = (config or {}).get("apikey")

    async def randomcat(self, ctx):
        async with self.bot.session.get("http://aws.random.cat/meow") as r:
            cat = (await r.json())["file"]
        embed = discord.Embed(title=":cat: ~meow~")
        embed.set_image(url=cat)
        return await ctx.channel.send(embed=embed)

    async def catapi(self, ctx, breed=None):
        if breed is not None:
            url = f"https://api.thecatapi.com/v1/images/search?breed_id={quote(breed)}"
        else:
            url = "https://api.thecatapi.com/v1/images/search"
        async with self.bot.session.get(url, headers={'x-api-key': self.meowkey}) as r:
            data = await r.json()
            if not data:
                if breed is not None:
                    return await ctx.channel.send("Invalid breed, only breed code is supported.\n"
                                                  f"To find the breed code, type `{self.bot.prefix}meow breeds`.")
                return await ctx.channel.send("No cat found...")
            cat = data[0]
            embed = discord.Embed(title=":cat: ~meow~")
            embed.set_image(url=cat["url"])
            if cat.get("breeds"):
                embed.set_footer(text=", ".join(b["name"] for b in cat["breeds"]))

        return await ctx.channel.send(embed=embed)

    @commands.group(aliases=["cat"], invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def meow(self, ctx, *, breed=None):
        """
        Random cat pic.

        API from random.cat or TheCatAPI.com.

        Breed can only be the codes found from `{prefix}meow breeds` command.

        To request from TheCatAPI.com, an API key must be set with `{prefix}meow apikey yourkeyhere`.
        Sign up for an API key for FREE here: https://thecatapi.com/signup.
        """
        if self.meowkey is not None:
            return await self.catapi(ctx, breed)
        if breed is not None:
            return await ctx.channel.send("Breed cannot be specified without using TheCatAPI.")
        return await self.randomcat(ctx)

    @meow.command(name="apikey")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def meow_apikey(self, ctx, *, key):
        """
        Set API key for TheCatAPI.com!

        To request from TheCatAPI.com, an API key must be set with `{prefix}meow apikey yourkeyhere`.
        Sign up for an API key for FREE here: https://thecatapi.com/signup.

        You may remove the API key with `{prefix}meow apikey clear`.
        """
        if key.lower() == "clear":
            key = None
        await self.db.find_one_and_update(
            {'_id': 'animals-config'},
            {'$set': {'apikey': key}},
            upsert=True
        )
        self.meowkey = key
        if key is None:
            return await ctx.channel.send("Successfully removed API key for TheCatAPI.com!")
        return await ctx.channel.send("Successfully set API key for TheCatAPI.com!")

    @meow.command(name="breeds")
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def meow_breeds(self, ctx):
        """
        Fetch cat breeds!
        """
        if self.meowkey is None:
            return await ctx.channel.send("No API key found!")
        async with self.bot.session.get("https://api.thecatapi.com/v1/breeds",
                                        headers={'x-api-key': self.meowkey}) as r:
            data = await r.json()
            breeds = []
            for breed in data:
                # Bug with API for Javanese breed
                if breed.get("alt_names", " ").strip():
                    for alt_name in breed["alt_names"].split(','):
                        breeds.append(f"{alt_name.strip().title()} (`{breed['id']}`)")
                breeds.append(f"{breed['name'].strip().title()} (`{breed['id']}`)")

        embeds = []
        for i, names in enumerate(zip_longest(*(iter(sorted(breeds)),) * 12)):
            description = utils.format_description(i, names)
            embed = discord.Embed(title=":cat: ~meow~", description=description)
            embeds.append(embed)

        async with self.bot.session.get(f"https://api.thecatapi.com/v1/images/search?limit={len(embeds)}",
                                        headers={'x-api-key': self.meowkey}) as r:
            data = await r.json()
            for cat, embed in zip(data, embeds):
                embed.set_image(url=cat["url"])
                if cat.get("breeds"):
                    embed.set_footer(text=", ".join(b["name"] for b in cat["breeds"]))

        session = EmbedPaginatorSession(ctx, *embeds)
        await session.run()

    @commands.group(aliases=["dog"], invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def woof(self, ctx, *, breed: str.lower = None):
        """
        Random dog pic.

        You may specify a dog breed, see `{prefix}woof breeds` to find all supported breeds.

        API from dog.ceo!
        """
        if breed is not None:
            if "".join(breed.lower().split()).strip() == "sharpbit" or any(u.name.lower() == "sharpbit" for u in ctx.message.mentions):
                embed = discord.Embed(title=":dog: ~woof~")
                embed.set_image(url="https://i.imgur.com/i2uODxh.jpg")
                embed.set_footer(text="SharpBit")
                return await ctx.channel.send(embed=embed)

            *sub_breed, breed = breed.split()
            if sub_breed:
                url = f"https://dog.ceo/api/breed/{quote(breed, safe='')}/{quote(sub_breed[0], safe='')}/images/random"
            else:
                url = f"https://dog.ceo/api/breed/{quote(breed, safe='')}/images/random"
        else:
            url = "https://dog.ceo/api/breeds/image/random"

        async with self.bot.session.get(url) as r:
            data = await r.json()
            if data["status"] == "error":
                return await ctx.channel.send(data["message"])
            dog = data["message"]
            breed, *sub_breed = dog.split('/')[-2].split('-')
            if sub_breed:
                breed = sub_breed[0] + " " + breed

        embed = discord.Embed(title=":dog: ~woof~")
        embed.set_image(url=dog)
        embed.set_footer(text=breed.title())
        return await ctx.channel.send(embed=embed)

    @woof.command(name="breeds")
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def woof_breeds(self, ctx):
        """
        Fetch a list of dog breeds.
        """
        async with self.bot.session.get("https://dog.ceo/api/breeds/list/all") as r:
            data = await r.json()
            if data["status"] == "error":
                return await ctx.channel.send(data["message"])
            dogs = data["message"]
            breeds = []
            for breed, sub_breeds in dogs.items():
                breeds.append(breed.title())
                for sub_breed in sub_breeds:
                    breeds.append((sub_breed + " " + breed).title())

        embeds = []
        for i, names in enumerate(zip_longest(*(iter(sorted(breeds)),) * 12)):
            description = utils.format_description(i, names)
            embed = discord.Embed(title=":dog: ~woof~", description=description)
            embeds.append(embed)

        async with self.bot.session.get(f"https://dog.ceo/api/breeds/image/random/{len(embeds)}") as r:
            data = await r.json()
            if data["status"] != "error":
                for dog, embed in zip(data["message"], embeds):
                    embed.set_image(url=dog)
                    breed, *sub_breed = dog.split('/')[-2].split('-')
                    if sub_breed:
                        breed = sub_breed[0] + " " + breed
                    embed.set_footer(text=breed.title())

        session = EmbedPaginatorSession(ctx, *embeds)
        await session.run()

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
