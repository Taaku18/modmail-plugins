import difflib
import re

from pkg_resources import parse_version

from discord import Embed
from discord.ext import commands
from discord.utils import escape_mentions

from core import checks
from core._color_data import ALL_COLORS
from core.models import PermissionLevel


class Colors(commands.Cog):
    """
    Conversions between hex, RGB, and color names.
    """
    def __init__(self, bot):
        self.bot = bot

    @commands.group(invoke_without_command=True, aliases=['colour'])
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def color(self, ctx, *, name: str.lower):
        """
        Convert a known color name to RGB and hex representations.
        """

        hex_code = ALL_COLORS.get(name)
        if hex_code is None:
            return await ctx.send(f'Color "{escape_mentions(name)}" is not a known color name.')

        if self.bot.version < parse_version('3.3.0-dev0'):
            hex_code = hex_code[1:]

        r, g, b = tuple(int(hex_code[i:i + 2], 16) for i in (0, 2, 4))

        embed = Embed(title=name.title(), description=f'Hex: `#{hex_code}`, RGB: `{r}, {g}, {b}`.')
        embed.set_thumbnail(url=f'https://placehold.it/100/{hex_code}?text=+')
        return await ctx.send(embed=embed)

    @color.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def hex(self, ctx, *, hex_code: str.lower):
        """
        Find the closest color name corresponding to the hex code, if any.
        """
        hex_code_match = re.match(r'^#?([a-f0-9]{6}|[a-f0-9]{3})$', hex_code)
        if hex_code_match is None:
            return await ctx.send(f'"{escape_mentions(hex_code)}" is not a valid hex code.')
        hex_code = hex_code_match.group(1)
        if len(hex_code) == 3:
            hex_code = ''.join(s for s in hex_code for _ in range(2))

        if self.bot.version >= parse_version('3.3.0-dev0'):
            possibilities = {v: k for k, v in ALL_COLORS.items() if v[::2] == hex_code[::2]}
        else:
            possibilities = {v: k for k, v in ALL_COLORS.items() if v[1::2] == hex_code[::2]}
        closest_hex = difflib.get_close_matches(hex_code, possibilities, n=1)
        if not closest_hex:
            return await ctx.send(f'Hex code `#{hex_code}` does not have an known color name.')
        closest_hex = closest_hex[0]

        clean_name = re.match(r'^(?:[^:]+:)?([^:]+)$', possibilities[closest_hex]).group(1)
        embed = Embed(title=f'#{hex_code}', description=f'Closest color name: "{clean_name.title()}".')
        if self.bot.version >= parse_version('3.3.0-dev0'):
            embed.set_thumbnail(url=f'https://placehold.it/100/{closest_hex}?text=+')
        else:
            embed.set_thumbnail(url=f'https://placehold.it/100/{closest_hex[1:]}?text=+')
        return await ctx.send(embed=embed)

    @color.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def rgb(self, ctx, *, rgb_value):
        """
        Find the closest color name corresponding to the RGB value, if any.
        """
        rgb_value_match = re.match(r'^(\d{,3})\D+(\d{,3})\D+(\d{,3})$', rgb_value)
        if not rgb_value_match:
            return await ctx.send(f'"{escape_mentions(rgb_value)}" is not a valid RGB value.')

        r, g, b = map(int, rgb_value_match.groups())
        if not 0 <= r <= 255 or not 0 <= g <= 255 or not 0 <= b <= 255:
            return await ctx.send(f'`{rgb_value}` is not a valid RGB value.')

        hex_code = '{0:02x}{1:02x}{2:02x}'.format(r, g, b)

        if self.bot.version >= parse_version('3.3.0-dev0'):
            possibilities = {v: k for k, v in ALL_COLORS.items() if v[::2] == hex_code[::2]}
        else:
            possibilities = {v: k for k, v in ALL_COLORS.items() if v[1::2] == hex_code[::2]}

        closest_hex = difflib.get_close_matches(hex_code, possibilities, n=1)
        if not closest_hex:
            return await ctx.send(f'RGB values `{r}, {g}, {b}` does not have an known color name.')
        closest_hex = closest_hex[0]

        clean_name = re.match(r'^(?:[^:]+:)?([^:]+)$', possibilities[closest_hex]).group(1)
        embed = Embed(title=f'RGB {r}, {g}, {b}', description=f'Closest color name: "{clean_name.title()}".')
        if self.bot.version >= parse_version('3.3.0-dev0'):
            embed.set_thumbnail(url=f'https://placehold.it/100/{closest_hex}?text=+')
        else:
            embed.set_thumbnail(url=f'https://placehold.it/100/{closest_hex[1:]}?text=+')
        return await ctx.send(embed=embed)

    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def rgbtohex(self, ctx, *, rgb_value):
        """
        Converts an RGB value to hex code.
        """
        rgb_value_match = re.match(r'^(\d{,3})\D+(\d{,3})\D+(\d{,3})$', rgb_value)
        if not rgb_value_match:
            return await ctx.send(f'"{escape_mentions(rgb_value)}" is not a valid RGB value.')

        r, g, b = map(int, rgb_value_match.groups())
        if not 0 <= r <= 255 or not 0 <= g <= 255 or not 0 <= b <= 255:
            return await ctx.send(f'`{rgb_value}` is not a valid RGB value.')

        hex_code = '{0:02x}{1:02x}{2:02x}'.format(r, g, b)

        embed = Embed(title=f'RGB {r}, {g}, {b}', description=f'Corresponding hex code is `#{hex_code}`.')
        embed.set_thumbnail(url=f'https://placehold.it/100/{hex_code}?text=+')
        return await ctx.send(embed=embed)

    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def hextorgb(self, ctx, *, hex_code: str.lower):
        """
        Converts a hex code to RGB value.
        """
        hex_code_match = re.match(r'^#?([a-f0-9]{6}|[a-f0-9]{3})$', hex_code)
        if hex_code_match is None:
            return await ctx.send(f'"{escape_mentions(hex_code)}" is not a valid hex code.')
        hex_code = hex_code_match.group(1)
        if len(hex_code) == 3:
            hex_code = ''.join(s for s in hex_code for _ in range(2))

        r, g, b = tuple(int(hex_code[i:i + 2], 16) for i in (0, 2, 4))

        embed = Embed(title=f'#{hex_code}', description=f'Corresponding RGB value is `{r}, {g}, {b}`.')
        embed.set_thumbnail(url=f'https://placehold.it/100/{hex_code}?text=+')
        return await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Colors(bot))
