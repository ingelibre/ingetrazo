# SPDX-License-Identifier: GPL-3.0-or-later
"""Function names/signatures from the user's DC reference; no vendor code.

This is an insertion catalogue, not an assertion that every function is
implemented. Availability is derived from the actual evaluator/action set.
"""
from .formula import FUNCTIONS

SIGNATURES = """
ABS(number)
CEILING(number, significance)
DEGREES(number)
EVEN(number)
EXP(number)
FLOOR(number, significance)
INT(number)
ISEVEN(number)
ISODD(number)
LN(number)
LOG10(number)
ODD(number)
POWER(base, power)
PI()
RADIANS(number)
RAND()
RANDBETWEEN(bottom, top)
ROUND(number, decimals)
SIGN(number)
SQRT(number)
CHOOSE(index, value1, value2, ...)
CURRENT(attribute)
EDGES()
FACEAREA(material)
FACES()
LARGEST(value1, value2, ...)
LAT()
LNG()
NEAREST(value, value1, value2, ...)
OPTIONINDEX(attribute)
OPTIONLABEL(attribute)
SMALLEST(value1, value2, ...)
SUNANGLE()
SUNELEVATION()
CHAR(number)
CODE(text)
CONCATENATE(text1, text2, ...)
DOLLAR(value, decimals)
EXACT(text1, text2)
FIND(search, text, position)
LEFT(text, number)
LEN(text)
LOWER(text)
MID(text, start, number)
PROPER(text)
REPLACE(text, position, length, new)
REPT(text, number)
RIGHT(text, number)
SUBSTITUTE(text, search, new, occurrence)
TRIM(text)
UPPER(text)
VALUE(text)
ACOS(number)
ACOSH(number)
ASIN(number)
ASINH(number)
ATAN(number)
ATANH(number)
COS(number)
COSH(number)
SIN(number)
SINH(number)
TAN(number)
TANH(number)
AND(value1, value2, ...)
FALSE()
IF(test, true_value, false_value)
NOT(value)
OR(value1, value2, ...)
TRUE()
ALERT(message)
ANIMATE(attribute, state1, state2, ...)
ANIMATEFAST(attribute, state1, state2, ...)
ANIMATECUSTOM(attribute, time, speedStart, speedEnd, state1, state2, ...)
ANIMATESLOW(attribute, state1, state2, ...)
GOTOSCENE(scene, time, speedStart, speedEnd)
REDRAW()
SET(attribute, state1, state2, ...)
MIN(value1, value2, ...)
MAX(value1, value2, ...)
MOD(number, divisor)
""".strip().splitlines()

ACTIONS = frozenset({'ALERT', 'ANIMATE', 'ANIMATEFAST', 'ANIMATECUSTOM',
                     'ANIMATESLOW', 'GOTOSCENE', 'REDRAW', 'SET'})
SUPPORTED_ACTIONS = ACTIONS - {'ALERT', 'GOTOSCENE'}

TRIG = frozenset('ACOS ACOSH ASIN ASINH ATAN ATANH COS COSH SIN SINH TAN TANH'.split())
TEXT = frozenset('CHAR CODE CONCATENATE DOLLAR EXACT FIND LEFT LEN LOWER MID PROPER REPLACE REPT RIGHT SUBSTITUTE TRIM UPPER VALUE'.split())
LOGIC = frozenset('AND FALSE IF NOT OR TRUE'.split())
CONTEXT = frozenset('CHOOSE CURRENT EDGES FACES LARGEST LAT LNG NEAREST OPTIONINDEX OPTIONLABEL SMALLEST SUNANGLE SUNELEVATION'.split())


def category(name):
    if name in TRIG:
        return 'trig'
    if name in TEXT:
        return 'text'
    if name in LOGIC:
        return 'logic'
    if name in ACTIONS:
        return 'onclick'
    if name == 'FACEAREA':  # material-specific surface query
        return 'texture'
    if name in CONTEXT:
        return 'context'
    return 'math'


def entries():
    for signature in sorted(SIGNATURES):
        name = signature.split('(', 1)[0]
        kind = 'action' if name in ACTIONS else 'function'
        supported = name in FUNCTIONS or name in SUPPORTED_ACTIONS or name in ('TRUE', 'FALSE')
        yield name, signature, kind, supported
