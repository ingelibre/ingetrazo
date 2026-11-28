# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded OnClick actions, using the existing formula interpreter for arguments.

Actions are prepared without mutating the model. Unsupported actions reject
the whole click. The document/controller decides when to commit the result.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import formula as F
from .apply import part_in_context
from .evaluate import Evaluator


class ActionError(ValueError):
    pass


@dataclass
class Change:
    group: object
    attribute: str
    start: object
    end: object
    duration: float = 0.0
    ease_in: float = 0.0
    ease_out: float = 100.0

    def value(self, elapsed):
        if self.duration <= 0 or elapsed >= self.duration:
            return self.end
        t = max(0.0, elapsed / self.duration)
        # Cubic Hermite interpolation with bounded endpoint speeds.
        a, b = 1 - self.ease_in / 100, 1 - self.ease_out / 100
        u = (-2*t**3 + 3*t*t) + (t**3 - 2*t*t + t)*a + (t**3 - t*t)*b
        return self.start + (self.end - self.start) * u


@dataclass
class ActionPlan:
    changes: list
    states: dict

    @property
    def duration(self):
        return max((c.duration for c in self.changes), default=0.0)

    def edits(self, elapsed=None):
        result = {key: dict(value) for key, value in self.states.items()}
        for c in self.changes:
            result.setdefault(id(c.group), {})[c.attribute] = (
                c.end if elapsed is None else c.value(elapsed))
        return result


def _statements(source):
    if not isinstance(source, str) or len(source) > F.MAX_SOURCE:
        raise ActionError("OnClick action is too long")
    out, start, quote, depth, i = [], 0, None, 0, 0
    while i < len(source):
        char = source[i]
        if quote:
            if char == quote:
                if i + 1 < len(source) and source[i + 1] == quote:
                    i += 1
                else:
                    quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif char == ';' and depth == 0:
            out.append(source[start:i].strip())
            start = i + 1
        if depth < 0 or depth > F.MAX_DEPTH:
            raise ActionError("Invalid OnClick action nesting")
        i += 1
    out.append(source[start:].strip())
    out = [s for s in out if s]
    if quote or depth or not out or len(out) > 32:
        raise ActionError("Invalid OnClick action list")
    return out


def prepare(root_group, clicked_group, scene=None):
    root, _frame = part_in_context(scene, root_group)
    part = next((p for p in root.walk() if p.handle is clicked_group), None)
    if part is None:
        raise ActionError("The clicked part is not in this component")
    source = part.attrs.get('onclick')
    ev = Evaluator(root)
    changes, states = [], {}

    def argument(node):
        return F.evaluate(F.Formula('', frozenset(), node), ev._lookup(part))

    for index, statement in enumerate(_statements(source), 1):
        try:
            tree = F.parse(statement)._tree
            if tree[0] != 'call':
                raise ActionError("OnClick expects an action call")
            _kind, name, args = tree
            allowed = {'SET', 'ANIMATE', 'ANIMATEFAST', 'ANIMATESLOW',
                       'ANIMATECUSTOM', 'REDRAW'}
            if name not in allowed:
                raise ActionError(f"Unsupported OnClick action: {name}")
            if name == 'REDRAW':
                if args:
                    raise ActionError("REDRAW expects no arguments")
                continue
            if len(args) < (5 if name == 'ANIMATECUSTOM' else 2):
                raise ActionError(f"{name} needs an attribute and a state")
            # SketchUp also accepts ANIMATE(Z,...) and ANIMATE(Part!Z,...):
            # its first argument names the attribute, rather than reading it.
            if args[0][0] == 'ref':
                owner, attr = args[0][1:]
                ref = attr if owner == 'self' else owner + '!' + attr
            else:
                ref = argument(args[0])
            if not isinstance(ref, str) or not ref.strip():
                raise ActionError("Action attribute must be a name")
            owner, sep, attr = ref.rpartition('!')
            target = ev.resolve(part, owner) if sep else part
            attr = (attr if sep else ref).strip().lower()
            if target is None or not attr or attr.startswith('_'):
                raise ActionError(f"Unknown action attribute: {ref}")
            duration = {'SET': 0., 'ANIMATEFAST': .25, 'ANIMATESLOW': 1.}.get(name, .5)
            ease_in, ease_out, offset = 0., 100., 1
            if name == 'ANIMATECUSTOM':
                duration, ease_in, ease_out = map(float, map(argument, args[1:4]))
                offset = 4
                if not (0 < duration <= 60 and 0 <= ease_in <= 100 and 0 <= ease_out <= 100):
                    raise ActionError("Invalid animation duration or easing")
            values = [ev.from_formula(target, attr, argument(n)) for n in args[offset:]]
            current = ev.value(target, attr)
            if duration:
                values = [float(v) for v in values]
                current = float(current)
                if not all(math.isfinite(v) for v in [current, *values]):
                    raise ActionError("Animation states must be finite numbers")
            matched = next((i for i, v in enumerate(values)
                            if (math.isclose(float(v), float(current), rel_tol=1e-7, abs_tol=1e-8)
                                if isinstance(v, (float, int)) and isinstance(current, (float, int))
                                else v == current)), -1)
            state = (matched + 1) % len(values)
            end = values[state]
            changes.append(Change(target.handle, attr, current, end, duration, ease_in, ease_out))
            states.setdefault(id(part.handle), {})[f'_onclick_state{index}'] = state
            # Later actions may read a value set by an earlier action.
            ev.overrides[(id(target), attr)] = end
            ev.memo.clear()
        except (F.FormulaError, TypeError, ValueError, OverflowError) as exc:
            if isinstance(exc, ActionError):
                raise
            raise ActionError(str(exc)) from exc
    return ActionPlan(changes, states)
