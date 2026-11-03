"""hold_bound -- `SDA_HOLD`, READ from the RTL rather than restated beside it.

⛔⛔ WHY A MODULE FOR ONE NUMBER. Ruling D needs the SDA data-hold length in
four places outside the RTL: the silicon refusal's must-fire images (D4), the
corpus delays (D5), the refusal audit (D6) and -- once S lands -- the
assembler's per-program floor (D2). Every one of them is a question of the form
"is this delay above the hold?", so every one of them needs the boundary. A
copy of `15` in each would be four chances to drift from `src/pe_engine.v`, and
this project has already published a column off a constant that existed twice.

⇒ THE BOUNDARY IS STATED ONCE, IN THE RTL, and read from there.

⚠ IT IS A READER WITH A TRIPWIRE, NOT A SECOND IMPLEMENTATION, and the
difference is the whole point. The `ceil` arithmetic is NOT re-derived here on
faith: `bound()` requires the RTL's own expression to match the form it knows
how to evaluate, TEXTUALLY, and raises if it does not. So the failure mode of a
changed formula is a named refusal at the next gate run rather than a stale
number that still looks plausible. ⛔ The thing that must never happen is this
file computing `ceil(300/20) = 15` while the RTL has been edited to round down
and actually holds 14 -- a Python helper quietly disagreeing with silicon is
the shape that cost this project its `d/2` claim.

⭐ AND IT IS CROSS-CHECKABLE BY A SECOND AUTHORITY: `test/param_dump.sh`
elaborates the design and prints the resolved localparams, `SDA_HOLD` among
them. `check_against_dump()` compares when such a dump is on disk. That is an
independent read -- the elaborator's -- rather than a better regex.
"""

from __future__ import annotations

import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE = os.path.join(ROOT, "src", "pe_engine.v")

#: the expression this reader knows how to evaluate, whitespace-insensitive:
#: ceil(NS x 1000 x BAND_NUM / (BAND_DEN x CLK_PERIOD_PS)), the banded
#: picosecond form (Wilson 11-03). ⛔ ANCHORED ON THE TEXT ON PURPOSE -- see the
#: module docstring.
def _form(ns_name):
    return (r"\(\s*%s\s*\*\s*1000\s*\*\s*BAND_NUM\s*\+\s*BAND_DEN\s*\*\s*"
            r"CLK_PERIOD_PS\s*-\s*1\s*\)\s*/\s*\(\s*BAND_DEN\s*\*\s*"
            r"CLK_PERIOD_PS\s*\)" % ns_name)


_CEIL_FORM = _form("SDA_HOLD_NS")


class HoldBoundError(RuntimeError):
    """The RTL could not be read, or it no longer matches the known form."""


def _params(text):
    out = {}
    for name in ("SDA_HOLD_NS", "CLK_PERIOD_PS", "BAND_NUM", "BAND_DEN"):
        m = re.search(r"(?:local)?param(?:eter)?\s+integer\s+%s\s*=\s*(\d+)"
                      % name, text)
        if m is None:
            raise HoldBoundError(
                "src/pe_engine.v has no `parameter integer %s = <n>`. The hold "
                "boundary is supposed to be stated THERE and read from there; "
                "with the parameter gone this reader has nothing to read and "
                "every caller would be guessing." % name)
        out[name] = int(m.group(1))
    return out


def _eval(ns, p, period_ps):
    per = p["CLK_PERIOD_PS"] if period_ps is None else int(period_ps)
    if per <= 0:
        raise HoldBoundError("CLK_PERIOD_PS is %d; the hold is undefined" % per)
    num, den = p["BAND_NUM"], p["BAND_DEN"]
    return (ns * 1000 * num + den * per - 1) // (den * per)


def bound(engine_path=None, hold_ns=None, period_ps=None, text=None):
    """`SDA_HOLD` in CYCLES, as the RTL computes it.

    `hold_ns` overrides the parameter's default, for the `-GSDA_HOLD_NS=<n>`
    builds (`test/phases_run.sh`'s `hold0` and `holdbig` arms). The FORMULA is
    still the RTL's -- only the input moves, which is exactly what `-G` does.
    `period_ps` is the same for a build at another target's clock (the FPGA
    passes its own `CLK_PERIOD_PS`). `text` is the engine source itself, for a
    caller judging a mutated copy (`gate_clock_consistency`'s must-fire).
    """
    path = engine_path or ENGINE
    if text is None:
        try:
            with io.open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            raise HoldBoundError("cannot read %s: %s" % (path, exc))
    p = _params(text)
    m = re.search(r"localparam\s+integer\s+SDA_HOLD\s*=\s*(.+?);", text,
                  re.S)
    if m is None:
        raise HoldBoundError(
            "src/pe_engine.v has no `localparam integer SDA_HOLD = ...;`. "
            "The derived cycle count is the boundary every caller compares "
            "against; it cannot be inferred from the two ns parameters alone "
            "because the ROUNDING is the part that matters.")
    expr = " ".join(m.group(1).split())
    if re.fullmatch(_CEIL_FORM, expr) is None:
        raise HoldBoundError(
            "src/pe_engine.v computes SDA_HOLD as `%s`, which is NOT the "
            "ceiling form this reader knows how to evaluate "
            "(`(SDA_HOLD_NS * 1000 * BAND_NUM + BAND_DEN * CLK_PERIOD_PS - 1) "
            "/ (BAND_DEN * CLK_PERIOD_PS)`). ⛔ REFUSING "
            "rather than guessing: a rounding change here moves the legal "
            "delay floor in silicon, and a helper that kept returning 15 while "
            "the hardware held 14 would make every D4/D5/D6 verdict wrong in "
            "the SAFE-LOOKING direction. Update this reader deliberately."
            % expr)
    ns = p["SDA_HOLD_NS"] if hold_ns is None else int(hold_ns)
    return _eval(ns, p, period_ps)


_SETUP_FORM = _form("SDA_SETUP_NS")


def setup(engine_path=None, period_ps=None, text=None):
    """`SDA_SETUP` in CYCLES (ruling W1), read the same way as `bound()`.

    W1 gates a lane's next dispatch until SDA_HOLD + SDA_SETUP cycles after the
    dispatch that loaded its hold, so A2 needs this number as well. Same
    tripwire: the RTL's expression must be the ceiling form, textually.
    """
    path = engine_path or ENGINE
    if text is None:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    p = _params(text)
    m = re.search(r"parameter\s+integer\s+SDA_SETUP_NS\s*=\s*(\d+)", text)
    e = re.search(r"localparam\s+integer\s+SDA_SETUP\s*=\s*(.+?);", text, re.S)
    if m is None or e is None:
        raise HoldBoundError("src/pe_engine.v has no SDA_SETUP_NS parameter "
                             "or SDA_SETUP localparam; W1's setup cannot be "
                             "read.")
    if re.fullmatch(_SETUP_FORM, " ".join(e.group(1).split())) is None:
        raise HoldBoundError("src/pe_engine.v computes SDA_SETUP in a form "
                             "this reader does not know; update it "
                             "deliberately.")
    return _eval(int(m.group(1)), p, period_ps)


def params(engine_path=None):
    """The hold, period and band inputs, for callers that report them."""
    path = engine_path or ENGINE
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        return _params(fh.read())


def check_against_dump(dump_path):
    """Compare with `test/param_dump.sh`'s elaborated value, if present.

    Returns `(ours, theirs)` or `None` when no dump is on disk. ⚠ A MISSING
    DUMP IS NOT A PASS: callers that want the second authority must say so --
    this returns None and lets them decide, rather than reporting agreement
    with something it never read.
    """
    if not os.path.isfile(dump_path):
        return None
    with io.open(dump_path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    m = re.search(r"PARAM\s+SDA_HOLD\s*=\s*(\d+)", text)
    if m is None:
        return None
    return bound(), int(m.group(1))


def main() -> int:
    p = params()
    print("  SDA_HOLD_NS   = %d" % p["SDA_HOLD_NS"])
    print("  CLK_PERIOD_PS = %d" % p["CLK_PERIOD_PS"])
    print("  band          = %d/%d" % (p["BAND_NUM"], p["BAND_DEN"]))
    print("  SDA_HOLD      = %d cycles  (read from src/pe_engine.v)" % bound())
    print("  legal clocked open-drain delay: d > %d" % bound())
    print("  SDA_SETUP     = %d cycles  (W1: dispatch gated SDA_HOLD + "
          "SDA_SETUP after a hold load)" % setup())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
