import re

from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication, \
    implicit_application, function_exponentiation, convert_xor

from discord.ext import commands

from core import checks
from core.models import PermissionLevel
from core.utils import cleanup_code


class Calculator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.transformations = standard_transformations + (implicit_multiplication, implicit_application,
                                                           function_exponentiation, convert_xor)

    @commands.command()
    @checks.has_permissions(PermissionLevel.OWNER)
    async def calc(self, ctx, *, exp):
        exp = cleanup_code(exp).splitlines()
        variables = {}
        output = ''
        for line in exp:
            line = line.strip()
            var = re.match(r'^let ([a-zA-Z]+)\s*=\s*(.+)$', line)
            if var is not None:
                v, e = var.groups()
                variables[v] = parse_expr(e, transformations=self.transformations).subs(variables).doit()
            else:
                output += str(parse_expr(line, transformations=self.transformations).subs(variables).doit()) + '\n'
        await ctx.send(f'```\n{output}\n```')


def setup(bot):
    bot.add_cog(Calculator(bot))

