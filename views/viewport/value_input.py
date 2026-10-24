# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The typed value buffer (VCB): key handling and value parsing."""
from __future__ import annotations

import math
import inspect
import re
from core.units import typed_value_text as _typed_value_text
from PySide6.QtCore import Qt
from core.i18n import tr
from views.viewport._support import _is_chord, _merge_mixed_numbers, _parse_length_field


class ValueInputMixin:
    """The typed value buffer (VCB): key handling and value parsing."""

    # ---- Numeric value buffer (VCB-style) ----------------------------------
    def _handle_value_key(self, ev) -> bool:
        """Buffer digit / dot / comma / semicolon / space / backspace.

        Enter applies the buffer via ``active_tool.on_value(...)``.

        Input forms:
        - ``"5"`` or ``"5,3"`` or ``"5.3"`` → single length (float).
        - ``"3;4;5"`` or ``"3 4 5"``       → 3D delta from the start point
                                              (passed as a ``(dx, dy, dz)`` tuple).
        - ``"-2"``                          → negative value (tools that take a
                                              direction flip it).
        - ``"30cm"`` / ``"1500mm"`` / ``"2m"`` → unit suffix per field; bare
                                              numbers are metres (project unit).
        Comma is the decimal separator; ``;`` and space are field
        separators (the usual convention adapted to our locale) -- except for
        a tool that only takes several values (``vcb_comma_lists``, the
        Rectangle): there ``200,100`` is two fields (#152).
        See :meth:`_parse_value_buffer`.
        """
        if self.active_tool is None:
            return False

        text = ev.text()
        key = ev.key()

        if key in (Qt.Key_Return, Qt.Key_Enter):
            if not self._value_buffer:
                return False
            # An angle, a factor or a count is not a length: the tool says
            # so and the document's unit stays out of it (#176).
            unitless = getattr(self.active_tool, "value_is_unitless", None)
            if callable(unitless) and unitless():
                from core.units import unitless_numbers
                with unitless_numbers():
                    value = self._parse_value_buffer(
                        self._value_buffer,
                        comma_lists=getattr(self.active_tool,
                                            "vcb_comma_lists", False))
            else:
                value = self._parse_value_buffer(
                    self._value_buffer,
                    comma_lists=getattr(self.active_tool, "vcb_comma_lists",
                                        False))
            if value is None:
                self._set_value_buffer("")
                return True
            if isinstance(value, tuple) and value and value[0] == "ratio":
                # A slope typed as rise:run ("3:12") — only angle
                # tools understand it; it reaches them as plain degrees.
                if getattr(self.active_tool, "accepts_angle_ratio", False):
                    self.active_tool.on_value(self, value[1])
                self._set_value_buffer("")
                return True
            if isinstance(value, tuple) and value and value[0] == "segments":
                handler = getattr(self.active_tool, "on_segments_value", None)
                if handler is not None:
                    handler(self, value[1])
                self._set_value_buffer("")
                return True
            if isinstance(value, tuple) and value and value[0] == "array":
                # Arrays: "3x" (external) / "/3" (internal) right
                # after a Move-copy. Only tools that declare it understand.
                handler = getattr(self.active_tool, "on_array_value", None)
                if handler is not None:
                    if len(value) <= 3:
                        handler(self, value[1], value[2])
                    elif "step" in inspect.signature(handler).parameters:
                        handler(self, value[1], value[2], step=value[3])
                    else:                       # "5x10m" means nothing here
                        self.flash_status(tr(
                            "Type the count alone here, e.g. 3x"))
                self._set_value_buffer("")
                return True
            if isinstance(value, tuple) and value and value[0] == "profile":
                # "0.3p": the profile of a bevel. Only tools that declare
                # it understand.
                handler = getattr(self.active_tool, "on_profile_value", None)
                if handler is not None:
                    handler(self, value[1])
                self._set_value_buffer("")
                return True
            if isinstance(value, tuple) and value and value[0] == "radius":
                # "2r": the 2-point arc takes a RADIUS instead
                # of the bulge. Only tools that declare it understand.
                handler = getattr(self.active_tool, "on_radius_value", None)
                if handler is not None:
                    handler(self, value[1])
                self._set_value_buffer("")
                return True
            if getattr(self.active_tool, "accepts_absolute_length", False):
                # Scale reads "2" as a factor but "2m" as the new
                # absolute size; the parser collapses both to metres, so the
                # unit's presence is re-detected here and tagged, the same
                # pattern as the arc's "2r" radius suffix.
                import re as _re
                if _re.search(r"[\d\"']\s*(mm|cm|m|in|ft)\b|\d\s*[\"']",
                              self._value_buffer.lower()):
                    value = ("abs_len", value)
            # Did this value actually commit geometry? Same signal as a
            # click that commits (see _dispatch_tool_click): a chaining tool
            # like Line stays busy the instant the segment exists, so "busy"
            # is not "the operation that used the arrow lock has ended". The
            # typed length must drop the lock exactly like the second click.
            history = getattr(self, "history", None)
            _before = len(history.undo_stack) if history is not None else 0
            _top = history.undo_stack[-1] if _before else None
            typed = self._value_buffer
            self.active_tool.on_value(self, value)
            _drew = history is not None and len(history.undo_stack) > _before
            # A hot retype (Push/Pull, Move, Rotate… typed right after a
            # commit) undoes the last command and commits it again: the
            # stack keeps its length but its top is a new command. That
            # also changed the model, and the box went on showing the
            # value from before the retype (tutorial video, #859).
            _redrew = (not _drew and _before > 0
                       and len(history.undo_stack) == _before
                       and history.undo_stack[-1] is not _top)
            self._set_value_buffer("")
            # The box falls back to the live reading, which only refreshes on
            # a mouse move: it went on showing the preview from BEFORE the
            # Enter, as if the typed size had been ignored (#607). What was
            # drawn is what was typed, read as the canvas showed it. Nothing
            # drawn: the preview the box shows is still the live one.
            if _drew or _redrew:
                unitless = getattr(self.active_tool, "value_is_unitless", None)
                self.measurementChanged.emit(
                    typed if callable(unitless) and unitless()
                    else _typed_value_text(typed))
            self._release_axis_lock_after_operation(committed=_drew)
            return True

        if key == Qt.Key_Backspace:
            if not self._value_buffer:
                return False
            self._set_value_buffer(self._value_buffer[:-1])
            return True

        if _is_chord(getattr(ev, "modifiers", lambda: Qt.NoModifier)()):
            # Alt+1, Ctrl+2…: a shortcut, not a digit for the value box. It
            # was taken as one while a value was being typed, so the view
            # shortcut never fired and each try added a «1» — a 35-digit
            # number, inf in the geometry's floats, then NaN (#185).
            return False
        from core.units import VULGAR_FRACTIONS, plain_marks
        if text in VULGAR_FRACTIONS:
            # ⅜, ½…: the fraction as digits, after a space when it follows
            # a whole number (1⅜ → 1 3/8). A keyboard that types them, or
            # smart quotes (”), made the value box drop keys (#189).
            if not self._value_buffer:
                self._set_value_buffer(plain_marks(text))
            else:
                self._set_value_buffer(plain_marks(self._value_buffer + text))
            return True
        text = plain_marks(text)
        arrays = getattr(self.active_tool, "accepts_array", False)
        if arrays and text == "*":
            # "*3" / "3*": the array multiplier ("x" works too).
            self._set_value_buffer(self._value_buffer + text)
            return True
        if arrays and text.lower() == "x" and (
                self._current_token_tail()
                or (not self._value_buffer and self._array_pending())):
            # "3x" — after a digit; bare X stays the Text tool shortcut,
            # except right after a copy, where "x5" is the array written
            # multiplier first (#542), as common a habit as "5x".
            self._set_value_buffer(self._value_buffer + text)
            return True
        if (text.lower() == "p" and self._current_token_tail()
                and hasattr(self.active_tool, "on_profile_value")):
            # "0.3p" — only after a digit, and only for a tool that takes a
            # profile: bare P stays the Push/Pull shortcut.
            self._set_value_buffer(self._value_buffer + text)
            return True
        if arrays and text == "/" and not self._value_buffer:
            # "/3": the internal-array divisor opens the buffer.
            self._set_value_buffer(text)
            return True
        if text and (text.isdigit()
                     or text in (".", ",", ";", " ", "-", ":", "\"", "'", "/")
                     or text.lower() in ("m", "c", "r", "i", "n", "f", "t", "s")):
            # A field separator (space / ;) with an empty buffer isn't VCB
            # input — let it fall through so Space can act as the Select
            # shortcut. It only separates fields mid-number.
            if text in (";", " ") and not self._value_buffer:
                return False
            # A unit letter with an empty buffer is a tool shortcut (M = Move,
            # C = Circle, R = Rectangle), not VCB input — only buffer it
            # after a digit. "r" is the radius suffix for arcs (2r), "s"
            # the segment count of an arc / sides of a circle (16s).
            if (text.lower() in ("m", "c", "r", "i", "n", "f", "t", "s")
                    and not self._current_token_tail()):
                return False
            # Imperial marks and the fraction bar belong after a digit too:
            # 2", 1'6", 3/4" (bare they are nothing a tool wants).
            if text in ("\"", "'", "/") and not self._current_token_tail():
                return True
            # Minus only opens a token (a sign, not an operator).
            if text == "-" and self._current_token_tail():
                return True
            # Colon (slope rise:run, "3:12"): mid-token only, once.
            if text == ":":
                tail = self._current_token_tail()
                if not tail or ":" in self._value_buffer:
                    return True
            # A second decimal separator in the current numeric token: a
            # "." is dropped, a "," starts the next value (#598) — dropping
            # it turned «0.9,2.1» into 0.921.
            if text in (".", ","):
                tail = self._current_token_tail()
                comma_fields = (
                    getattr(self.active_tool, "vcb_comma_lists", False)
                    and ";" not in self._value_buffer
                    and " " not in self._value_buffer)
                if comma_fields:
                    # Every comma separates a field here (#152).
                    tail = tail.rsplit(",", 1)[-1]
                if "." in tail or "," in tail:
                    if text == ".":
                        return True
                    if not comma_fields:
                        text = ";"
            self._set_value_buffer(self._value_buffer + text)
            return True

        return False

    @staticmethod
    def _parse_value_buffer(buffer: str, comma_lists: bool = False):
        """Return a float, a 2-tuple ``(w, h)`` (rectangle dimensions), a
        3-tuple ``(dx, dy, dz)`` (delta), or ``None`` on parse error. Each tool's
        ``on_value`` accepts the arity it understands and ignores the rest.
        Fields may carry a unit suffix — ``m``/``cm``/``mm``, and imperial
        ``in`` or ``"``, ``ft`` or ``'``, feet-and-inches ``1'6"``, fractions
        ``3/4"`` (the usual forms, so a 2×4 is typed ``2";4"`` while the
        span stays ``3.2``). Bare numbers are metres, and a leading minus is
        kept (direction tools flip on it).

        **The comma (#152).** ``;`` and whitespace always separate fields.
        A comma is a decimal separator (``2,5`` is 2.5, ``2,5;1,2`` is
        2.5 × 1.2 -- Spanish and Portuguese write decimals that way) --
        EXCEPT when ``comma_lists`` is set and the entry has no ``;`` and no
        space: then commas separate fields, so ``200,100`` is 200 × 100 as
        usual. ``comma_lists`` is the caller's word that the tool takes
        only several values (the Rectangle), where a lone decimal could never
        be meant; a user who wants decimals there separates with ``;``
        (``1,5;2,5``), which is the usual rule in comma-decimal locales."""
        from core.units import plain_marks
        buffer = plain_marks(buffer)
        # A comma followed by a space separates values: a decimal comma
        # never has one after it. «1 3/8", 1 3/16"» is two lengths (#189).
        buffer = re.sub(r",\s+", ";", buffer.strip())
        if (comma_lists and ";" not in buffer
                and not any(ch.isspace() for ch in buffer.strip())):
            buffer = buffer.replace(",", " ")
        normalized = buffer.replace(",", ".").replace(";", " ")
        stripped = normalized.strip()
        # Arrays after a copy: "3x" / "3*" / "*3" (external) and
        # "/3" / "3/" (internal). Only tools with ``accepts_array`` get them.
        m = re.fullmatch(r"(?:(\d+)\s*[x*]|[x*]\s*(\d+))", stripped.lower())
        if m is not None:
            return ("array", int(m.group(1) or m.group(2)), "x")
        # "5x10m": five copies ten metres apart in one entry (#111) — the
        # count and the spacing that would otherwise take two steps.
        m = re.fullmatch(r"(\d+)\s*[x*]\s*(.+)", stripped.lower())
        if m is not None:
            step = ValueInputMixin._parse_value_buffer(m.group(2))
            if isinstance(step, (int, float)) and not isinstance(step, bool) \
                    and step > 0:
                return ("array", int(m.group(1)), "x", float(step))
            return None
        m = re.fullmatch(r"(?:/\s*(\d+)|(\d+)\s*/)", stripped)
        if m is not None:
            return ("array", int(m.group(1) or m.group(2)), "/")
        if stripped.lower().endswith("r") and ":" not in stripped:
            import re as _re
            m = _re.fullmatch(r"(\d+\.?\d*|\.\d+)r", stripped.lower())
            if m is None:
                return None
            return ("radius", float(m.group(1)))
        if stripped.lower().endswith("p") and ":" not in stripped:
            # "0.3p": the profile of a bevel (0 to 1, no unit).
            m = re.fullmatch(r"(\d+\.?\d*|\.\d+)p", stripped.lower())
            if m is None:
                return None
            return ("profile", float(m.group(1)))
        if stripped.lower().endswith("s") and ":" not in stripped:
            # "12s": the segment count of an arc / the sides of
            # a circle. Only tools that declare it understand.
            import re as _re
            m = _re.fullmatch(r"(\d+)s", stripped.lower())
            if m is None:
                return None
            return ("segments", int(m.group(1)))
        if ":" in normalized:
            # Slope as rise:run ("3:12", "1:6") → ("ratio", degrees).
            m = re.fullmatch(
                r"\s*(-?(?:\d+\.?\d*|\.\d+)):(\d+\.?\d*|\.\d+)\s*", normalized)
            if m is None:
                return None
            rise, run = float(m.group(1)), float(m.group(2))
            if run <= 0 or not (math.isfinite(rise) and math.isfinite(run)):
                return None
            return ("ratio", math.degrees(math.atan2(rise, run)))
        nums = []
        # «;» is a hard separator: «5';3"» stays two values, while «5' 3"»
        # is one length, written the usual way.
        fields = [f for group in buffer.replace(",", ".").split(";")
                  for f in _merge_mixed_numbers(group.split())]
        for p in fields:
            v = _parse_length_field(p)
            if v is None:
                return None
            nums.append(v)
        if len(nums) == 1:
            return nums[0]
        if len(nums) in (2, 3):
            return tuple(nums)
        return None

    def _array_pending(self) -> bool:
        """Whether the active tool just made a copy that «x5» would turn
        into an array (#542)."""
        pending = getattr(self.active_tool, "array_pending", None)
        return bool(pending(self)) if callable(pending) else False

    def _current_token_tail(self) -> str:
        """The portion of the buffer after the last ``;`` or space."""
        normalized = self._value_buffer.replace(";", " ")
        idx = normalized.rfind(" ")
        if idx < 0:
            return self._value_buffer
        return self._value_buffer[idx + 1 :]

    def _set_value_buffer(self, text: str) -> None:
        if text == self._value_buffer:
            return
        self._value_buffer = text
        self.valueBufferChanged.emit(text)
        self.update()
