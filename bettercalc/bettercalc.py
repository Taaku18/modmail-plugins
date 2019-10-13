#
# Modified from https://raw.githubusercontent.com/lark-parser/lark/master/examples/calc.py.
#

import operator as op
import re
import sympy as sy
from lark import Lark, Transformer, v_args
from mpmath import mp

from core import checks
from core.models import PermissionLevel
from core.paginator import MessagePaginatorSession

from discord.ext import commands


REMOVE_ZERO = re.compile(r'(?:(\.\d+?)0+|(\d\.0)0+)\b')
REMOVE_CODE = re.compile(r'^\s*`{3,}(\w+\n)?|(\n\s*)(?=\n)|`{3,}\s*$')

calc_grammar = """
    ?start: sum
          | NAME "=" sum                   -> assign_var
          | ("print"i | "repr"i ) sum
          | "latex" sum                    -> latex_print

    ?sum: product
        | sum "+" product            -> add
        | sum "-" product            -> sub

    ?product: atom
        | product "*" atom           -> mul
        | product "/" atom           -> div
        | product "//" atom          -> floor_div
        | product ("^" | "**") atom  -> exp
        | product "(" atom ")"       -> mul

    ?trig: sum
        | sum ("degrees"i | "degree"i | "deg"i | "°")    -> to_radian

    ?trig2: atom
        | final ("degrees"i | "degree"i | "deg"i | "°")  -> to_radian

    ?atom: func
         | "-" atom              -> neg
         | "+" atom

    ?func: final
         | ("sin"i "(" trig ")" | "sin"i trig2)    -> sin
         | ("tan"i "(" trig ")" | "tan"i trig2)    -> tan
         | ("cos"i "(" trig ")" | "cos"i trig2)    -> cos
         | ("asin"i "(" trig ")"| "asin"i trig2)   -> asin
         | ("atan"i "(" trig ")"| "atan"i trig2)   -> atan
         | ("acos"i "(" trig ")"| "acos"i trig2)   -> acos

         | "sqrt"i "(" sum ")"                     -> sqrt
         | ("log"i | "ln"i) "(" sum ")"            -> log
         | ("log_"i _ | "log"i) final "(" sum ")"    -> log_base
         | ("abs"i "(" sum ")" | "|" sum "|")      -> abs

         | (final "!" | "(" sum ")" "!" | "factorial"i "(" sum ")") -> factorial

         | "(" sum ")"

    ?final: NAME                 -> var
         |  NUMBER               -> number
         | ("pi"i | "π")         -> pi
         | "e"i                  -> e
         | ("inf"i | "oo"i)      -> inf
         | ("phi"i | "φ")        -> phi

    %import common.WORD          -> NAME
    %import common.NUMBER
    %import common.WS_INLINE

    %ignore WS_INLINE
"""


@v_args(inline=True)
class CalculateTree(Transformer):
    number = sy.Float

    def __init__(self):
        self.vars = {}
        self.reserved = {'oo', 'ln', 'print', 'repr'} | set(CalculateTree.__dict__)

    precision = mp.dps = 20

    @classmethod
    def set_precision(cls, n):
        mp.dps = n
        cls.precision = n

    add = op.add
    sub = op.sub
    mul = op.mul
    div = op.truediv
    floor_div = op.floordiv
    neg = op.neg

    exp = sy.Pow
    abs = sy.Abs
    factorial = sy.factorial
    sin = sy.sin
    tan = sy.tan
    cos = sy.cos
    asin = sy.asin
    atan = sy.atan
    acos = sy.acos

    # def imp_mul(self, a, b):
    #     if isinstance(b, str):
    #         b = self.var(b)
    #     return a * b

    def latex_print(self, value):
        return sy.latex(value)

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

    def sqrt(self, n):
        return sy.sqrt(n)

    def log(self, n):
        return sy.log(n)

    def log_base(self, b, n):
        return sy.log(n, b)


class Calculatorv2(commands.Cog):
    """
    It's working!! FINALLY - Taki.
    """

    def __init__(self, bot):
        self.bot = bot
        self.bot._ct = CalculateTree
        self.calc_parser = Lark(calc_grammar, parser='lalr', transformer=CalculateTree())
        self.calc = self.calc_parser.parse

    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def calcv2(self, ctx, *, exp):
        """
        Basically a simple calculator-v2. This command is safe.
        """
        exp = REMOVE_CODE.sub('', exp).strip().splitlines()
        outputs = []
        for i, line in enumerate(exp, start=1):
            try:
                e = self.calc(line.strip())
                if hasattr(e, 'evalf'):
                    e = e.evalf(n=CalculateTree.precision, chop=True)
                e = REMOVE_ZERO.sub(r'\1\2', str(e))

                outputs += [f"Line {i}: " + e + '\n']
            except Exception as e:
                outputs += [f"Error on line {i}: {e}.\n"]

        messages = ['```\n']
        for output in outputs:
            if len(messages[-1]) + len(output) + len('```') > 2048:
                messages[-1] += '```'
                messages.append('```\n')
            messages[-1] += output
        if not messages[-1].endswith('```'):
            messages[-1] += '```'

        session = MessagePaginatorSession(ctx, *messages)
        return await session.run()

    @commands.command()
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def calcprec(self, ctx, *, precision: int):
        """
        Change the precision of calculator. Resets to 20 digits when the bot restarts.
        """
        if precision > 100:
            return await ctx.send("Maximum precision is 100.")
        CalculateTree.set_precision(precision)
        return await ctx.send(f"Successfully set precision to {precision}.")


def setup(bot):
    bot.add_cog(Calculatorv2(bot))
