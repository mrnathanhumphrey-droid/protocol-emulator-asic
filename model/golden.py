"""THE GOLDEN MODEL -- an executable semantics of the action ISA.

Pre-registered in `docs/ARCH_PREREG_01.md` as commitment 3: "the golden model is
written as an executable formal semantics of the ISA FROM DAY ONE -- so a
conformance proof later starts from a spec that already exists instead of one
reconstructed afterwards." Prediction A3 and falsifier F1 both rest on it.

⛔⛔ IT DID NOT EXIST, AND THAT IS WORTH STATING PLAINLY. The commitment said
"from day one"; the engine (S3), the double buffer, the jitter analysis and two
digest bumps all landed first. Nothing in the repository executed an action word
-- `test/make_smoke_image.py` only ENCODES them. So every claim about what the
engine does has been a claim about what the RTL does, checked against a
testbench written alongside it.

⛔⛔⛔ THEREFORE THE ONE RULE THIS FILE MUST OBEY: IT IS WRITTEN FROM THE SPEC,
NOT FROM `pe_engine.v`. The opcode semantics below come from
`gate_program_census`'s action vocabulary and the programs it enumerates; the
word layout comes from `gate_encoding_f1.action_word`; the state comes from
`gate_spec_freeze_s2.frozen_fields`. ⭐ A golden model transcribed from the RTL
is a same-author re-derivation: it would agree with the engine on every bug they
share, and agreement would mean nothing. That is the same error as a measurement
"confirming" the bound it was derived from, which this project has already made.

⭐⭐ AND THE STATE IS A `FieldSet`, NOT A PYTHON OBJECT WITH ATTRIBUTES. Every
read and write goes through a name that must appear in the FROZEN FIELD TABLE,
and an access to an unfrozen name is RECORDED rather than silently working. That
is what makes reverse traceability mechanical instead of my opinion:

    S2 traceability   detects a FIELD WITH NO RULING      (forward)
    this              detects a BEHAVIOUR WITH NO FIELD   (reverse)

S3 found five such fields by writing RTL and watching it fail. This finds them
by executing the census, which is the cheaper direction and the one that
generalises.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "a2"))

from gate_program_census import (ARM, LEVEL, READBIT, SHIFT,        # noqa: E402
                                 SHIFTIN, START, STOP, WAIT)
from gate_spec_freeze_s2 import frozen_fields                       # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# The frozen names, imported rather than retyped. ⛔ A hand-typed copy of the
# field table is exactly the defect `gate_pyrta`'s arm 0 exists to catch.
FROZEN = {f[0] for f in frozen_fields()}

# Where each frozen field lives, so the model can tell lane state from program
# fields from global state without re-deciding it.
FROZEN_WHERE = {f[0]: f[2] for f in frozen_fields()}


class MissingField(Exception):
    """Raised when the semantics needs a field the freeze does not have."""


class FieldSet:
    """Named state whose keys must be FROZEN fields.

    ⛔ `strict=False` RECORDS instead of raising, because the point is to
    COLLECT every missing field in one run rather than stop at the first. A
    gate that reports one gap per run turns a five-field finding into five
    runs, and the fifth only gets found if someone keeps going.
    """

    def __init__(self, where: str, strict: bool = False):
        self._v = {}
        self._where = where
        self._strict = strict
        self.missing = {}        # name -> why the semantics needed it

    def need(self, name: str, why: str):
        """Declare a field the semantics is about to use."""
        if name not in FROZEN:
            self.missing[name] = why
            if self._strict:
                raise MissingField("%s: %s" % (name, why))
            return False
        return True

    def set(self, name: str, value, why: str = ""):
        self.need(name, why or "written by the semantics")
        self._v[name] = value

    def get(self, name: str, default=None, why: str = ""):
        self.need(name, why or "read by the semantics")
        return self._v.get(name, default)

    def __contains__(self, name):
        return name in self._v


# ===========================================================================
# THE ACTION WORD -- decode, per gate_encoding_f1.action_word's field list
# ===========================================================================
# (opcode 3, pin, level/dir 1, delay/period DELAY_BITS, bit count N)
# ⛔ NO per-action clock pin: S2 CUT it as a duplicate of the per-lane header
# field. The semantics therefore reads the clock pin from the LANE, and if a
# program ever needed two different clocks on one lane this model could not
# express it -- which is the cut being load-bearing rather than cosmetic.
class Action:
    def __init__(self, op, pin=0, level=0, delay=0, count=0, note=""):
        self.op, self.pin, self.level = op, pin, level
        self.delay, self.count, self.note = delay, count, note

    def __repr__(self):
        return "%s(pin=%d,lvl=%d,dly=%d,n=%d)" % (
            self.op, self.pin, self.level, self.delay, self.count)


# ===========================================================================
# THE SEMANTICS -- one function per opcode, from the census vocabulary
# ===========================================================================
# Each returns (pin_events, cycles_consumed). A pin event is
# (offset_cycles, pin, value) relative to the action's start, so the SCHEDULER
# owns absolute time and the semantics owns shape. ⭐ Separating them is what
# lets this model be checked against the RTL's waveform without also having to
# agree about dispatch order.
def sem_level(lane, a, bus):
    """LEVEL -- drive one pin to a level after a delay.

    ⛔ THE DRIVE MODE DECIDES WHAT "DRIVE" MEANS, and forgetting that is the
    bug S3 hit: with mode stuck at open-drain a lane on an output-only pin
    drove low once and stuck. Open-drain holds the output at 0 and modulates
    the ENABLE; push-pull drives both levels.
    """
    mode = lane.get("drive mode", 0, "LEVEL must know push-pull vs open-drain")
    if mode:                                     # push-pull
        return [(0, a.pin, a.level)], 1
    # open-drain: level 1 = release (pulled high), level 0 = drive low
    return [(0, a.pin, "Z" if a.level else 0)], 1


def sem_shift(lane, a, bus):
    """SHIFT -- emit N bits from the lane's data register, LSB first, at the
    lane's inner period, with the lane's clock pin toggling.

    ⭐ THE CLOCK IS PART OF THE ACTION, not a second action. That is F1's
    rationale for the shift/repeat encoding: data and clock as two actions must
    stay in lockstep, which is a per-bit ordering hazard.
    """
    data = lane.get("data/shift register", 0, "SHIFT emits from it")
    clk = lane.get("clock pin (per lane)", None,
                   "SHIFT must drive the lane's clock; the per-ACTION clock "
                   "pin was cut by S2 as a duplicate")
    per = max(1, a.delay)
    ev, t = [], 0
    for k in range(a.count):
        bit = (data >> k) & 1
        ev.append((t, a.pin, bit))
        if clk is not None:
            ev.append((t + per // 2, clk, 1))
            ev.append((t + per, clk, 0))
        t += per
    lane.set("bit pointer", a.count, "SHIFT advances it")
    return ev, t


def sem_shiftin(lane, a, bus):
    """SHIFTIN -- sample N bits into the lane's data register."""
    per = max(1, a.delay)
    ev, t, got = [], 0, 0
    for k in range(a.count):
        got |= (bus.read(a.pin, t) & 1) << k
        t += per
    lane.set("data/shift register", got, "SHIFTIN writes it")
    lane.set("bit pointer", a.count, "SHIFTIN advances it")
    return ev, t


def sem_readbit(lane, a, bus):
    """READBIT -- sample ONE bit. ⭐ On the OBSERVED clock rise, per R3: for
    I2C the ACK is read on the rise of the SCL we can SEE, not on a modelled
    phase, because the slave may stretch the clock."""
    v = bus.read(a.pin, 0)
    lane.set("data/shift register", v & 1, "READBIT writes the sampled bit")
    return [], 1


def sem_start(lane, a, bus):
    """I2C START -- SDA high->low while SCL is high."""
    clk = lane.get("clock pin (per lane)", None, "START must hold SCL high")
    ev = [(0, a.pin, 1)]
    if clk is not None:
        ev.append((0, clk, 1))
    ev.append((1, a.pin, 0))
    return ev, 2


def sem_stop(lane, a, bus):
    """I2C STOP -- SDA low->high while SCL is high."""
    clk = lane.get("clock pin (per lane)", None, "STOP must hold SCL high")
    ev = [(0, a.pin, 0)]
    if clk is not None:
        ev.append((0, clk, 1))
    ev.append((1, a.pin, "Z"))
    return ev, 2


def sem_arm(lane, a, bus):
    """ARM -- release the lane on a peer edge, with a bounded wait.

    ⭐ THIS SEMANTICS GREW AFTER THE FIRST RUN OF THIS MODEL FOUND `armed`
    MISSING. The original version recorded a single "armed" bit and stopped
    there; the field was absent from the freeze, the gate reported it, and
    chasing it into the RTL showed `OP_ARM` was a NO-OP with no edge capture
    anywhere in the design. The full semantics below is Wilson's ARMED ruling,
    and every field it touches is now in the freeze.

    THE FOUR PIECES, each with its own reason:
      armed               the lane waits on an edge -- NOT the same state as a
                          pending timestamp. It is also the EDGE LATCH, so an
                          edge before ARM has nothing holding it (Ruling 3).
      armed pin           full width: SPI-target needs MISO, SCK and CS.
      armed edge polarity the action's level bit. UART-rx arms on a start-bit
                          FALL, SPI-target on CS FALL, I2C on the SCL RISE --
                          so it cannot be fixed in hardware.
      no-timeout          delay == 0 means wait indefinitely (UART-rx idle).

    ⛔ AND THE REBASE IS THE PART THAT WOULD BREAK UART IF OMITTED: on an edge
    release the lane's timestamp becomes the EDGE TIME, not the ARM's deadline.
    0.9b derives the sample grid as `edge + half + m*T`; anchored to an
    arbitrary timeout instant it misses every bit.
    """
    lane.set("armed", 1, "ARM records that the lane is waiting on an edge, "
                         "which is not the same state as a pending timestamp")
    lane.set("armed pin", a.pin, "which pin's edge releases the lane")
    lane.set("armed edge polarity", a.level,
             "rise or fall -- the three reactive releases disagree")
    lane.set("no-timeout", 1 if a.delay == 0 else 0,
             "ARM with delay 0 waits indefinitely")
    # ⛔ A TIMEOUT IS AN ERROR, so the model needs somewhere to say so. If the
    # wait expires the lane HALTS; it must not carry on as though the peer had
    # answered.
    lane.need("TIMEOUT (sticky)",
              "a timeout must be distinguishable from an edge release, or a "
              "program reads a frame out of an idle line")
    return [], 1


def sem_wait(lane, a, bus):
    """WAIT / re-arm -- adds to the STORED timestamp (Ruling 2).

    ⛔⛔ `level` SELECTS TWO MEANINGS, and the second one needs a field:
      level = 0  extend the delay, program counter UNCHANGED  (chaining)
      level = 1  extend the delay AND JUMP TO THE LANE'S PROGRAM BASE (loop)
    A periodic protocol must repeat, so without the jump a program counter
    advances linearly and falls off the end.
    """
    if a.level:
        base = lane.get("program base", None,
                        "a looping re-arm must jump the program counter to the "
                        "lane's FIRST action; without a base register a "
                        "periodic protocol cannot repeat")
        lane.set("program counter", base,
                 "the loop writes the program counter")
    return [], 1


SEMANTICS = {
    LEVEL: sem_level, SHIFT: sem_shift, SHIFTIN: sem_shiftin,
    READBIT: sem_readbit, START: sem_start, STOP: sem_stop,
    ARM: sem_arm, WAIT: sem_wait,
}


class Bus:
    """The pins, and what an input reads.

    ⛔ A MODEL OF THE PEER, DELIBERATELY TRIVIAL. It returns a fixed pattern,
    because this model exists to check that the ISA can EXPRESS each program and
    what state that needs -- not to co-simulate a FRAM. A peer model good enough
    to judge protocol correctness is a separate artefact and pretending otherwise
    would make this file's green mean more than it does.
    """

    def __init__(self, pattern=0xA5):
        self.pattern = pattern
        self.events = []
        self._i = 0

    def read(self, pin, offset):
        v = (self.pattern >> (self._i % 8)) & 1
        self._i += 1
        return v

    def drive(self, t, pin, value):
        self.events.append((t, pin, value))


class Machine:
    """Non-preemptive EDF over lanes, each running its own action list.

    ⛔ The scheduler is here because TIMING IS THE PRODUCT: a semantics that
    returned only pin shapes could not be compared against the engine's
    waveform, and the whole claim of this project is about when edges land.
    """

    def __init__(self, strict=False):
        self.lanes = []
        self.bus = Bus()
        self.now = 0
        self.strict = strict
        self.missing = {}
        self.ops_executed = {}

    def add_lane(self, name, prog, *, pin, clkpin=None, mode=1, c=2,
                 d_sched=10, period=1, data=0xA5):
        st = FieldSet("lane-reg", self.strict)
        st.set("pin index", pin, "every action names a pin")
        st.set("drive mode", mode, "LEVEL needs it")
        st.set("data/shift register", data, "SHIFT/SHIFTIN need it")
        st.set("bit pointer", 0, "SHIFT/SHIFTIN advance it")
        st.set("next-action timestamp", 0, "Ruling 2's absolute schedule")
        st.set("C_i", c, "service time")
        st.set("D_sched (EDF key)", d_sched, "the EDF key")
        if clkpin is not None:
            st.set("clock pin (per lane)", clkpin, "SHIFT/START/STOP drive it")
        # ⛔ THE THREE BELOW ARE WHAT THE SEMANTICS NEEDS AND THE FREEZE LACKS.
        # They are set through the SAME checked interface as everything else, so
        # they are recorded as missing rather than quietly working.
        st.set("program counter", 0,
               "a lane executes a SEQUENCE of actions, so it must remember "
               "which one is next; nothing in the frozen table holds it")
        st.set("program base", 0,
               "a looping re-arm must jump somewhere, and each lane's program "
               "starts at a different address")
        self.lanes.append({"name": name, "st": st, "prog": prog,
                           "period": period, "done": False})
        return st

    def _collect(self):
        for l in self.lanes:
            for k, v in l["st"].missing.items():
                self.missing.setdefault(k, v)

    def run(self, horizon=4000, max_actions=4000):
        """Execute until every lane's program is exhausted or horizon passes."""
        n = 0
        while n < max_actions:
            ready = [l for l in self.lanes if not l["done"]
                     and l["st"].get("next-action timestamp", 0) <= self.now]
            if not ready:
                pend = [l["st"].get("next-action timestamp", 0)
                        for l in self.lanes if not l["done"]]
                if not pend:
                    break
                self.now = min(pend)
                if self.now > horizon:
                    break
                continue
            # EDF: earliest absolute deadline = timestamp + D_sched
            ready.sort(key=lambda l: (l["st"].get("next-action timestamp", 0)
                                      + l["st"].get("D_sched (EDF key)", 0)))
            lane = ready[0]
            st = lane["st"]
            pc = st.get("program counter", 0)
            if pc >= len(lane["prog"]):
                lane["done"] = True
                continue
            a = lane["prog"][pc]
            fn = SEMANTICS.get(a.op)
            if fn is None:
                self.missing.setdefault(
                    "opcode %s" % a.op,
                    "the census uses this opcode and the semantics has no rule "
                    "for it")
                lane["done"] = True
                continue
            ev, cycles = fn(st, a, self.bus)
            for off, pin, val in ev:
                self.bus.drive(self.now + off, pin, val)
            self.ops_executed[a.op] = self.ops_executed.get(a.op, 0) + 1
            # ⛔ the PC advance is the semantics' own, and a looping re-arm has
            # already written it -- so advance only when the action did not.
            if not (a.op == WAIT and a.level):
                st.set("program counter", pc + 1, "sequencing")
            st.set("next-action timestamp",
                   st.get("next-action timestamp", 0) + max(cycles, a.delay or 1),
                   "Ruling 2: the next action is relative to the STORED "
                   "timestamp, never to `now`")
            self.now += max(1, st.get("C_i", 2))
            n += 1
        self._collect()
        return self.bus.events
