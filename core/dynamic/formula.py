# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 d1rty-pixel, moominot and IngeTrazo contributors.
# From d1rty-pixel's «Dynamic Components for IngeTrazo» (GPL-3.0,
# https://github.com/d1rty-pixel/ingetrazo-dynamic-components), through
# moominot's «dc_tools» (https://github.com/moominot/ingetrazo-skp-dc-import),
# extended here: part names with spaces before «!», and the rule of .skp files that
# only a positive number is true.
"""Spreadsheet-style formula language: tokenizer, parser and tree-walking interpreter.

Formulas come from documents we did not write, so this module never uses
eval/exec/compile/ast: the only operations available are the ones implemented here.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Context, Decimal

from .messages import MessageError, Msg, N_

MAX_SOURCE = 4096
MAX_DEPTH = 64
MAX_ARGS = 64
MAX_STRING = 64 * 1024
DEFAULT_BUDGET = 10_000


class FormulaError(MessageError):
    """User-facing error (``.msg`` is a translatable Msg); `steps` is the work
    done before it was raised."""

    steps = 0


@dataclass(frozen=True)
class Formula:
    source: str
    refs: frozenset
    _tree: tuple = field(default=(), repr=False, compare=False)


# ---------------------------------------------------------------- tokenizer

_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)
  | (?P<str>"(?:[^"]|"")*"|'(?:[^']|'')*')
  | (?P<owner>[^\W\d][\w\x20]*?(?=\x20*!))
  | (?P<id>[^\W\d]\w*)
  | (?P<op><>|<=|>=|[-+*/^&=<>(),!])
""", re.VERBOSE)

_NUMERIC_TEXT = re.compile(r"^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")


def _tokenize(text: str) -> list[tuple[str, str, int]]:
    tokens = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if m is None:
            raise FormulaError(Msg("Unexpected character {char} at position {pos}",
                                   char=repr(text[pos]), pos=pos + 1))
        if m.lastgroup == "owner":
            # .skp files name parts freely: «FINESTRA SIMPLE!B_TIPUS»,
            # «Vertical 1!LenX». The name before «!» may hold spaces and
            # digits; it is one identifier, its spaces collapsed.
            tokens.append(("id", " ".join(m.group().split()), pos))
        elif m.lastgroup != "ws":
            tokens.append((m.lastgroup, m.group(), pos))
        pos = m.end()
    return tokens


# ------------------------------------------------------------------- parser

# Left-associative levels, lowest precedence first.
_LEVELS = (
    ("cmp", frozenset({"=", "<>", "<", ">", "<=", ">="})),
    ("cat", frozenset({"&"})),
    ("add", frozenset({"+", "-"})),
    ("mul", frozenset({"*", "/"})),
)


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0
        self.depth = 0
        self.refs: set[tuple[str, str]] = set()

    def _peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else ("end", "", -1)

    def _next(self):
        tok = self._peek()
        self.i += 1
        return tok

    def _is_op(self, *ops) -> bool:
        kind, text, _ = self._peek()
        return kind == "op" and text in ops

    def _expect_op(self, op: str) -> None:
        if not self._is_op(op):
            raise self._unexpected(Msg("expected {op}", op=repr(op)))
        self.i += 1

    def _unexpected(self, hint=None) -> FormulaError:
        kind, text, pos = self._peek()
        if kind == "end":
            msg = Msg("Unexpected end of formula")
        else:
            msg = Msg("Unexpected {token} at position {pos}", token=repr(text), pos=pos + 1)
        if hint:
            msg = Msg("{error} ({hint})", error=msg, hint=hint)
        return FormulaError(msg)

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise FormulaError(Msg("Formula is nested too deeply (limit {limit})", limit=MAX_DEPTH))

    def parse(self):
        tree = self._expression()
        if self._peek()[0] != "end":
            raise self._unexpected()
        return tree

    def _expression(self):
        self._enter()
        try:
            return self._level(0)
        finally:
            self.depth -= 1

    def _level(self, lvl: int):
        if lvl == len(_LEVELS):
            return self._power()
        kind, ops = _LEVELS[lvl]
        first = self._level(lvl + 1)
        rest = []
        while self._is_op(*ops):
            op = self._next()[1]
            rest.append((op, self._level(lvl + 1)))
        return (kind, first, rest) if rest else first

    def _power(self):
        base = self._unary()
        if self._is_op("^"):
            self.i += 1
            self._enter()
            try:
                return ("pow", base, self._power())
            finally:
                self.depth -= 1
        return base

    def _unary(self):
        if self._is_op("-", "+"):
            op = self._next()[1]
            self._enter()
            try:
                return ("neg" if op == "-" else "pos", self._unary())
            finally:
                self.depth -= 1
        return self._primary()

    def _primary(self):
        kind, text, _ = self._peek()
        if kind == "num":
            self.i += 1
            value = float(text)
            if not math.isfinite(value):
                raise FormulaError(Msg("Number {number} is out of range", number=repr(text[:20])))
            return ("lit", value)
        if kind == "str":
            self.i += 1
            quote = text[0]
            return ("lit", text[1:-1].replace(quote * 2, quote))
        if kind == "id":
            self.i += 1
            return self._name(text)
        if self._is_op("("):
            self.i += 1
            inner = self._expression()
            self._expect_op(")")
            return inner
        raise self._unexpected()

    def _name(self, text: str):
        if self._is_op("("):
            return self._call(text.upper())
        if self._is_op("!"):
            self.i += 1
            kind, attr, _ = self._peek()
            if kind != "id":
                raise self._unexpected(Msg("expected an attribute name after '!'"))
            self.i += 1
            return self._ref(text.lower(), attr.lower())
        if text.upper() in ("TRUE", "FALSE"):
            return ("lit", text.upper() == "TRUE")
        return self._ref("self", text.lower())

    def _ref(self, node: str, attr: str):
        self.refs.add((node, attr))
        return ("ref", node, attr)

    def _call(self, name: str):
        self.i += 1  # the '('
        args = []
        if not self._is_op(")"):
            while True:
                args.append(self._expression())
                if len(args) > MAX_ARGS:
                    raise FormulaError(Msg("Too many arguments in {name}() (limit {limit})",
                                           name=name, limit=MAX_ARGS))
                if not self._is_op(","):
                    break
                self.i += 1
        self._expect_op(")")
        return ("call", name, args)


def parse(source: str) -> Formula:
    """Parse `source` (leading `=` optional); raises FormulaError on syntax or limits."""
    if not isinstance(source, str):
        raise FormulaError(Msg("Formula must be text"))
    if len(source) > MAX_SOURCE:
        raise FormulaError(Msg("Formula is too long (limit {limit} characters)", limit=MAX_SOURCE))
    text = source.strip()
    if text.startswith("="):
        text = text[1:]
    if not text.strip():
        raise FormulaError(Msg("Formula is empty"))
    parser = _Parser(_tokenize(text))
    try:
        tree = parser.parse()
    except RecursionError:
        raise FormulaError(Msg("Formula is nested too deeply")) from None
    return Formula(source, frozenset(parser.refs), tree)


# -------------------------------------------------------------- conversions

def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise FormulaError(Msg("Result is out of range"))
    return value


def _sanitize(value):
    """Accept only float/str/bool (ints become floats); reject anything else."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        try:
            return _finite(float(value))
        except OverflowError:
            raise FormulaError(Msg("Number is out of range")) from None
    if isinstance(value, str):
        if len(value) > MAX_STRING:
            raise FormulaError(Msg("Text is too long"))
        return value
    raise FormulaError(Msg("Unsupported value of type {type}", type=type(value).__name__))


def _num(value) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        text = value.strip()
        if _NUMERIC_TEXT.match(text):
            try:
                return _finite(float(text))
            except FormulaError:
                pass
        raise FormulaError(Msg("Cannot convert {value} to a number", value=repr(value[:30])))
    raise FormulaError(Msg("Expected a number"))


def _int(value) -> int:
    return math.trunc(_num(value))


def _text(value) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return format(value, ".15g")
    return value


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        # .skp dynamic components take only a POSITIVE number as true:
        # IF(estructura-1, a, b) with estructura = 0 gives b (checked against
        # real components saved in .skp files).
        return value > 0.0
    if value.strip().upper() in ("TRUE", "FALSE"):
        return value.strip().upper() == "TRUE"
    if _NUMERIC_TEXT.match(value.strip()):
        return float(value.strip()) > 0.0
    raise FormulaError(Msg("Cannot convert {value} to TRUE/FALSE", value=repr(value[:30])))


def _sort_key(value):
    if isinstance(value, str):
        return (1, value.lower())
    return (0, float(value))


def _compare(op: str, a, b) -> bool:
    ka, kb = _sort_key(a), _sort_key(b)
    if op == "=":
        return ka == kb
    if op == "<>":
        return ka != kb
    if op == "<":
        return ka < kb
    if op == ">":
        return ka > kb
    return ka <= kb if op == "<=" else ka >= kb


def _concat(*parts) -> str:
    result = "".join(_text(p) for p in parts)
    if len(result) > MAX_STRING:
        raise FormulaError(Msg("Text is too long"))
    return result


# --------------------------------------------------------------- functions

_CTX = Context(prec=800)


def _round(x, n=0.0):
    digits = max(-330, min(330, _int(n)))
    exact = Decimal(repr(_num(x))).quantize(
        Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP, context=_CTX)
    return float(exact)


def _snap(q: float) -> float:
    r = round(q)
    return float(r) if abs(q - r) < 1e-9 * max(1.0, abs(q)) else q


def _floor(x, sig=1.0):
    s = abs(_num(sig))
    if s == 0:
        raise FormulaError(Msg("{name}: significance must not be 0", name="FLOOR"))
    return math.floor(_snap(_num(x) / s)) * s


def _ceiling(x, sig=1.0):
    s = abs(_num(sig))
    if s == 0:
        raise FormulaError(Msg("{name}: significance must not be 0", name="CEILING"))
    return math.ceil(_snap(_num(x) / s)) * s


def _mod(n, d):
    """Excel's MOD: n - d*INT(n/d); the result has the sign of the divisor."""
    divisor = _num(d)
    if divisor == 0:
        raise FormulaError(Msg("Division by zero"))
    value = _num(n)
    result = value - divisor * math.floor(_snap(value / divisor))
    return 0.0 if abs(result) < 1e-12 * max(1.0, abs(divisor)) else result


def _sqrt(x):
    v = _num(x)
    if v < 0:
        raise FormulaError(Msg("SQRT of a negative number"))
    return math.sqrt(v)


def _clean(v: float) -> float:
    return 0.0 if abs(v) < 1e-12 else v


def _tan(x):
    angle = math.radians(_num(x))
    if abs(math.cos(angle)) < 1e-12:
        raise FormulaError(Msg("TAN is undefined for this angle"))
    return _clean(math.tan(angle))


def _asin(x):
    v = _num(x)
    if not -1.0 <= v <= 1.0:
        raise FormulaError(Msg("{name} argument must be between -1 and 1", name="ASIN"))
    return math.degrees(math.asin(v))


def _acos(x):
    v = _num(x)
    if not -1.0 <= v <= 1.0:
        raise FormulaError(Msg("{name} argument must be between -1 and 1", name="ACOS"))
    return math.degrees(math.acos(v))


def _count(value, what: str) -> int:
    n = _int(value)
    if n < 0:
        raise FormulaError(Msg("{what} must not be negative", what=what))
    return n


def _left(s, n=1.0):
    return _text(s)[:_count(n, N_("LEFT length"))]


def _right(s, n=1.0):
    count = _count(n, N_("RIGHT length"))
    return _text(s)[-count:] if count else ""


def _mid(s, start, n):
    first = _int(start)
    if first < 1:
        raise FormulaError(Msg("MID start must be at least 1"))
    return _text(s)[first - 1:first - 1 + _count(n, N_("MID length"))]


def _trim(s):
    return re.sub(" +", " ", _text(s).strip(" "))


def _minmax(fn):
    return lambda *a: fn(_num(v) for v in a)


# name -> (min args, max args, implementation on evaluated args)
_FUNCS = {
    "AND": (1, MAX_ARGS, lambda *a: all([_bool(v) for v in a])),
    "OR": (1, MAX_ARGS, lambda *a: any([_bool(v) for v in a])),
    "NOT": (1, 1, lambda v: not _bool(v)),
    "MIN": (1, MAX_ARGS, _minmax(min)),
    "MAX": (1, MAX_ARGS, _minmax(max)),
    "ABS": (1, 1, lambda v: abs(_num(v))),
    "ROUND": (1, 2, _round),
    "FLOOR": (1, 2, _floor),
    "CEILING": (1, 2, _ceiling),
    "INT": (1, 1, lambda v: float(math.floor(_num(v)))),
    "MOD": (2, 2, _mod),
    "SQRT": (1, 1, _sqrt),
    "SIN": (1, 1, lambda v: _clean(math.sin(math.radians(_num(v))))),
    "COS": (1, 1, lambda v: _clean(math.cos(math.radians(_num(v))))),
    "TAN": (1, 1, _tan),
    "ASIN": (1, 1, _asin),
    "ACOS": (1, 1, _acos),
    "ATAN": (1, 1, lambda v: math.degrees(math.atan(_num(v)))),
    "RADIANS": (1, 1, lambda v: math.radians(_num(v))),
    "DEGREES": (1, 1, lambda v: math.degrees(_num(v))),
    "PI": (0, 0, lambda: math.pi),
    "LEN": (1, 1, lambda v: float(len(_text(v)))),
    "LEFT": (1, 2, _left),
    "RIGHT": (1, 2, _right),
    "MID": (3, 3, _mid),
    "CONCATENATE": (1, MAX_ARGS, _concat),
    "VALUE": (1, 1, _num),
    "LOWER": (1, 1, lambda v: _text(v).lower()),
    "UPPER": (1, 1, lambda v: _text(v).upper()),
    "TRIM": (1, 1, _trim),
}
_LAZY = {"IF": (2, 3), "CHOOSE": (2, MAX_ARGS)}

#: Every function a formula may call, sorted (for pickers and completion).
FUNCTIONS: tuple[str, ...] = tuple(sorted({*_FUNCS, *_LAZY}))


# -------------------------------------------------------------- interpreter

class _Interpreter:
    def __init__(self, lookup, budget: int):
        self.lookup = lookup
        self.budget = budget
        self.used = 0

    def step(self) -> None:
        self.used += 1
        if self.used > self.budget:
            raise FormulaError(Msg("Formula is too expensive to evaluate (step budget exceeded)"))

    def ev(self, node):
        self.step()
        value = self._ev(node)
        if isinstance(value, str) and len(value) > 256:
            # Text ops cost O(length): charge it, or 64 KiB strings turn the step budget into a hang.
            self.used += len(value) >> 8
            if self.used > self.budget:
                raise FormulaError(Msg("Formula is too expensive to evaluate (step budget exceeded)"))
        return value

    def _ev(self, node):
        kind = node[0]
        if kind == "lit":
            return node[1]
        if kind == "ref":
            return self._ref(node[1], node[2])
        if kind == "neg":
            return -_num(self.ev(node[1]))
        if kind == "pos":
            return _num(self.ev(node[1]))
        if kind == "pow":
            return self._pow(_num(self.ev(node[1])), _num(self.ev(node[2])))
        if kind == "call":
            return self._call(node[1], node[2])
        return self._chain(kind, node[1], node[2])

    def _ref(self, node: str, attr: str):
        return _sanitize(self.lookup(node, attr))

    def _chain(self, kind: str, first, rest):
        acc = self.ev(first)
        for op, operand in rest:
            self.step()
            acc = self._binary(kind, op, acc, self.ev(operand))
        return acc

    def _binary(self, kind: str, op: str, a, b):
        if kind == "cmp":
            return _compare(op, a, b)
        if kind == "cat":
            return _concat(a, b)
        x, y = _num(a), _num(b)
        if op == "+":
            return _finite(x + y)
        if op == "-":
            return _finite(x - y)
        if op == "*":
            return _finite(x * y)
        if y == 0:
            raise FormulaError(Msg("Division by zero"))
        return _finite(x / y)

    @staticmethod
    def _pow(base: float, exponent: float) -> float:
        try:
            return _finite(math.pow(base, exponent))
        except OverflowError:
            raise FormulaError(Msg("Result of ^ is out of range")) from None
        except ValueError:
            if base == 0:
                raise FormulaError(Msg("Division by zero")) from None
            raise FormulaError(Msg("Cannot raise a negative number to a fractional power")) from None

    def _call(self, name: str, args):
        if name in _LAZY:
            self._check_arity(name, len(args), *_LAZY[name])
            return self._lazy(name, args)
        if name not in _FUNCS:
            raise FormulaError(Msg("Unknown function {name}", name=name))
        lo, hi, impl = _FUNCS[name]
        self._check_arity(name, len(args), lo, hi)
        values = [self.ev(a) for a in args]
        try:
            return _sanitize(impl(*values))
        except FormulaError:
            raise
        except (ArithmeticError, ValueError) as exc:
            raise FormulaError(Msg("{name}: invalid argument ({kind})", name=name,
                                   kind=type(exc).__name__)) from None

    @staticmethod
    def _check_arity(name: str, n: int, lo: int, hi: int) -> None:
        if not lo <= n <= hi:
            if lo == hi:
                raise FormulaError(Msg("{name} expects {count} argument(s), got {got}",
                                       name=name, count=lo, got=n))
            raise FormulaError(Msg("{name} expects {low} to {high} argument(s), got {got}",
                                   name=name, low=lo, high=hi, got=n))

    def _lazy(self, name: str, args):
        if name == "IF":
            if _bool(self.ev(args[0])):
                return self.ev(args[1])
            return self.ev(args[2]) if len(args) > 2 else False
        index = _int(self.ev(args[0]))
        if not 1 <= index < len(args):
            raise FormulaError(Msg("CHOOSE index {index} is out of range 1..{last}",
                                   index=index, last=len(args) - 1))
        return self.ev(args[index])


def run(f: Formula, lookup, *, budget: int = DEFAULT_BUDGET):
    """Like `evaluate`, but returns (value, steps used); errors carry `.steps`."""
    interp = _Interpreter(lookup, budget)
    try:
        return _sanitize(interp.ev(f._tree)), interp.used
    except FormulaError as exc:
        exc.steps = interp.used
        raise
    except RecursionError:
        error = FormulaError(Msg("Formula is nested too deeply"))
    except Exception as exc:  # noqa: BLE001 - trust boundary, nothing else may escape
        error = FormulaError(Msg("Evaluation failed ({kind})", kind=type(exc).__name__))
    error.steps = interp.used
    raise error


def evaluate(f: Formula, lookup, *, budget: int = DEFAULT_BUDGET):
    """Evaluate `f`; `lookup(node, attr)` supplies references. Raises only FormulaError."""
    return run(f, lookup, budget=budget)[0]
