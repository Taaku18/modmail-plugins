#
# Modified from https://raw.githubusercontent.com/lark-parser/lark/master/examples/calc.py.
#

import operator as op
import sympy as sy
from lark import Lark, Transformer, v_args
from mpmath import mp

from core import checks
from core.models import PermissionLevel
from core.utils import cleanup_code

from discord.ext import commands

mp.dps = 50

calc_grammar = """
    ?start: sum
          | NAME "=" sum    -> assign_var

    ?sum: product
        | sum "+" product   -> add
        | sum "-" product   -> sub

    ?product: atom
        | product "*" atom         -> mul
        | product "/" atom         -> div
        | product "//" atom        -> floor_div
        | product "^" atom         -> exp
        | product "(" atom ")"     -> mul
        | product NAME             -> imp_mul

    ?trig: sum
        | sum ("deg"i | "degree"i | "degrees"i)  -> to_radian

    ?trig2: atom
        | final ("deg"i | "degree"i | "degrees"i) -> to_radian

    ?atom: final
         | "-" atom              -> neg
         | "+" atom
         | "pi"i | "π"           -> pi
         | "e"i                  -> e
         | "inf"i | "oo"i        -> inf
         | "phi"i | "φ"          -> phi
         | "c"i                  -> c

         | ("sin"i "(" trig ")" | "sin"i trig2)    -> sin
         | ("tan"i "(" trig ")" | "tan"i trig2)    -> tan
         | ("cos"i "(" trig ")" | "cos"i trig2)    -> cos
         | ("asin"i "(" trig ")"| "asin"i trig2)   -> asin
         | ("atan"i "(" trig ")"| "atan"i trig2)   -> atan
         | ("acos"i "(" trig ")"| "acos"i trig2)   -> acos

         | "sqrt"i "(" sum ")"                     -> sqrt
         | ("log"i | "ln"i) "(" sum ")"            -> log
         | ("log"i | "log_"i) final "(" sum ")"    -> log_base
         | ("abs"i "(" sum ")" | "|" sum "|")      -> abs

         | (final "!" | "(" sum ")" "!" | "factorial"i "(" sum ")") -> factorial

         | "(" sum ")"

    ?final: NUMBER        -> number
        | NAME            -> var

    %import common.WORD -> NAME
    %import common.NUMBER
    %import common.WS_INLINE

    %ignore WS_INLINE
"""


@v_args(inline=True)
class CalculateTree(Transformer):
    number = float

    def __init__(self):
        self.vars = {}
        self.reserved = {'oo', 'ln'} | set(CalculateTree.__dict__)

    add = op.add
    sub = op.sub
    mul = op.mul
    div = op.truediv
    floor_div = op.floordiv
    exp = op.pow
    abs = abs
    factorial = sy.factorial
    sin = sy.sin
    tan = sy.tan
    cos = sy.cos
    asin = sy.asin
    atan = sy.atan
    acos = sy.acos
    neg = op.neg

    def imp_mul(self, a, b):
        b = self.var(b)
        return a * b

    def assign_var(self, name, value):
        self.vars[sy.Symbol(name)] = value
        return f"{sy.Symbol(name)} = {value}"

    def to_radian(self, n):
        return n * sy.pi / 180

    def var(self, name):
        if name.lower() in self.reserved:
            raise ValueError(f"{name} is reserved.")
        return self.vars.get(sy.Symbol(name), sy.Symbol(name))

    def pi(self):
        return sy.pi

    def e(self):
        return sy.E

    def inf(self):
        return sy.oo

    def phi(self):
        return mp.phi

    def c(self):
        return mp.catalan

    def sqrt(self, n):
        return sy.sqrt(n)

    def log(self, n):
        return sy.log(n)

    def log_base(self, n, b):
        return sy.log(n, b)



class Calculatorv2(commands.Cog):
    """
    It's working!! FINALLY - Taki.
    """

    def __init__(self, bot):
        self.bot = bot
        self.calc_parser = Lark(calc_grammar, parser='lalr', transformer=CalculateTree())
        self.calc = self.calc_parser.parse

    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def calcv2(self, ctx, *, exp):
        """
        Basically a simple calculator-v2. This command is safe.
        """
        exp = cleanup_code(exp).splitlines()
        output = '\n'.join(sy.pretty(self.calc(line.strip()), use_unicode=True) for line in exp)
        return await ctx.send(f'```\n{output}\n```')


def setup(bot):
    bot.add_cog(Calculatorv2(bot))
