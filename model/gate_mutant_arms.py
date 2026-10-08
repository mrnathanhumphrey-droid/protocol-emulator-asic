"""MUTANT ARM DRIFT GUARD -- the ifdef must wrap the minimal delta, nothing else.

THE ONE CLAIM: for every mutant define, preprocessing the sources with and
without it differs by EXACTLY the intended mutation. Any other difference means
the two arms have drifted apart.

⛔⛔⛔ WHY THIS EXISTS, AND IT IS NOT HYPOTHETICAL. 1.6s's refusal-to-dispatch
went in as `ST_IDLE: if (hdr_done && !config_err && winner_v)` -- and landed in
the `M_NO_PRIME` MUTANT ARM. The guard line was DUPLICATED either side of an
`ifdef`, a text edit hit one copy, and the default path (which gates on
`primed`, not `hdr_done`) never got it. The violating program ran, every other
gate stayed green, and only the new must-fire caught it.
⇒ A FIX THAT LANDS IN A MUTANT ARM IS NOT IN THE DESIGN. The failure mode is
  duplicated ACTIVE LOGIC inside an `ifdef`, so the structural answer is to
  forbid the duplication and check it mechanically.

## The rules, each checked

  1. SIZE IS THE SIGNAL FOR DUPLICATION, NOT COUNT EQUALITY. An early version
     required the diff to remove as many lines as it adds, on the theory that a
     mutation is a substitution. ⛔ That is wrong: an `ifndef` mutant legitimately
     DELETES one line (M_NO_REBASE drops the rebase), and a duplicated block
     shows up as a LARGE diff with EQUAL counts -- the opposite of what the rule
     would have caught. So the budget below is the duplication check.
  2. NO COMMENTS IN THE DIFF. A comment that appears in only one arm proves the
     `ifdef` wraps more than the delta -- the comment is not the mutation. This
     found a real instance on the first run.
  3. NON-EMPTY. A mutant whose diff is empty changes nothing and is dead
     weight that reads as coverage.
  4. SIZE BUDGET, with declared exceptions. Anything above `MINIMAL` lines must
     carry a stated reason, so a block swap is a decision on the record rather
     than a habit.
  5. NO DRIFT. The diff must equal the recorded expectation line for line.

⚠ RULE 5 IS RECORDED FROM INSPECTION, NOT AUTO-ACCEPTED. A table generated from
whatever the source happens to say would certify the current state as intended,
which is the fitted-to-observation failure. The counts and reasons below were
read one at a time; rules 1-4 hold independently of them, so even a wrong
expectation cannot make a duplicated block pass.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), "test"))
from toolchain import banner, tool          # noqa: E402  ruling V

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
SOURCES = ["pe_engine.v", "project.v", "pe_store.v"]

MINIMAL = 4          # lines of preprocessed diff that need no excuse

# mutant -> (expected total diff lines, reason if above MINIMAL)
EXPECT = {
    "M_NOOP_DRIVES":     (2, None),
    # ⭐ TWO DELETED LINES SINCE RULING TF1: the rebase write in the lane block
    # and the same rebase term in `ts_n`, the next-state timestamp the
    # registered readiness reads. Both must go or the arms disagree.
    "M_NO_REBASE":       (2, None),
    # TF2-R3's must-fire: the release term reads the CURRENT `l_live`, so a
    # lane halted this cycle stays eligible one more -- one token, one line
    "M_TF2_LIVE_LATE":   (2, None),
    "M_PFETCH_NOWAIT":   (2, None),
    "M_BUF_NOINVAL":     (2, None),
    "M_BUF_SWAP":        (2, None),
    "M_COMB_OUT":        (4, None),
    "M_NO_PRIME":        (4, None),
    "M_BUF_CHAINFLIP":   (3, None),
    # ⭐ TWO LINES, WHICH IS ONE SUBSTITUTION: `assign host_q = a_q;` becomes
    # `assign host_q = 2'd0;`, so the diff is one line removed and one added --
    # the same shape as M_BUF_SWAP and M_PFETCH_NOWAIT. The queue tag is a
    # single expression, so nothing else moves with it, which is what makes
    # this a clean price on the field rather than on a block.
    "M_TX_IGNORE_TAG":   (2, None),
    "M_RX_NO_LANE":      (2, None),
    "M_IGNORE_ORDER":    (2, None),
    "M_SHARED_BITP":     (14,
        "a BLOCK substitution across FOUR sites, declared: the mutation "
        "re-merges the TX and RX bit pointers, and the pointer is named in the "
        "reset, in OP_SHIFT's advance, in OP_SHIFTIN's advance-and-complete, "
        "and at the TX host load. There is no single expression whose value "
        "expresses 'share the pointer' -- the arm also has to DECLARE the "
        "shared register, which is why it is the largest arm in this table. "
        "⚠ Its size is the point: the defect it reproduces was distributed "
        "across every site that touched the pointer, which is how it survived "
        "unnoticed."),
    "M_UNGUARDED_ARMPIN": (2,
        "AN IFDEF/ELSE PAIR, like its sibling: one line of guard against one "
        "line of mutant, so the diff is two. ⭐ Same shape because the FIX is "
        "the same shape -- the edge select now reads a single `arm_real` wire "
        "instead of indexing `pin_rise`/`pin_fall` raw, so BOTH arms of the "
        "`?:` are covered by one guard. Guarding only one would have left the "
        "asymmetry that made D2 a defect, in the one place where both arms "
        "index the same program field."),
    "M_UNGUARDED_SAMPLE": (2,
        "ONE LINE, and that is the whole point of the fix. The three sample "
        "sites now read a single guarded wire -- `rx_bit = pin_real ? "
        "pin_in[a_pin] : 1'b0` -- so the mutation is one substitution rather "
        "than three, and a fourth sample site cannot pick up the unguarded "
        "form by copying its neighbour. ⚠ Before the wire existed, "
        "`pin_in[a_pin]` appeared verbatim at 745, 1502 and 1524, and removing "
        "the guard would have meant three separate edits -- an arm whose size "
        "tracks the number of copies rather than the size of the idea."),
    "M_BUS_NO_PULLDOWN": (2,
        "ONE LINE IN EACH ARM, in `test/od_bus.vh` -- THE BENCHES' one bus "
        "model. It drops the DUT's pull-down, so a line the part is actively "
        "pulling low still reads HIGH. ⛔ WHAT IT PROVES is that there is now "
        "ONE model: the resolution used to exist three times (tb_trace, "
        "tb_edge, and a Python coroutine in test.py), and the Python copy was "
        "a CONSTANT 0xFF -- pull-ups without pull-downs -- for most of its "
        "life. ⚠ IT IS PRICED AGAINST THE DESIGN'S OWN FAULT DETECTOR, not a "
        "bench heuristic, and that choice was forced by measurement: a global "
        "stall detector CANNOT see it (under the mutant tb_trace still "
        "produced 1603 writebacks, because the other four lanes keep the "
        "engine busy, while only 1 action retired against 110), and a per-lane "
        "one cannot either (a lane parked on an OP_ARM edge legitimately never "
        "retires). MEASURED with the prescaler shortened: clean = no fault, "
        "7387 actions retired, 2462 clocked actions conformant; mutant = "
        "`clk_stretch_err` SET, 1 action retired, 0 clocked actions checked."),
    "M_CK_NO_PARK": (2,
        "ONE LINE IN EACH ARM: `ck_park_en` is a wire, so the mutant is `1'b0` "
        "for `1'b1`. ⛔ WHAT IT BREAKS IS COMPLIANCE, not an assertion: without "
        "the post-HIGH park the capture races the lane's own next dispatch, so "
        "a peer holding SCL longer than that gap LOSES A BIT. ⭐ MEASURED BOTH "
        "WAYS, which is what makes this evidence -- with the mutant a 500-cycle "
        "SCL hold sets `clk_stretch_err` while a 50-cycle hold does not; "
        "without it, 5000 cycles lose nothing. ⚠ Layer B of the bench watchdog "
        "reports OK in every one of those runs, because the DISPATCH COUNT is "
        "unchanged by a stretch -- which is the point of capturing on the rise, "
        "and also why bit loss needs its own check and not a conformance one."),
    "M_CK_HOLD_RETIRES": (2,
        "TWO LINES IN ONE ARM, added to an EMPTY clean arm: a held clocked "
        "action retires like a normal one -- invalidate AND advance the PC. "
        "⛔ IT IS THE MUTATION THAT REACHES F1's HAZARD: the slot goes free, "
        "the prefetch refills it from the NEW pc, and the parked lane releases "
        "on a delay belonging to the next action. ⚠ IT TAKES BOTH LINES AND "
        "THAT COST TWO ATTEMPTS TO ESTABLISH. Invalidating alone leaves the PC "
        "put, so the refill restores an identical word; advancing the PC alone "
        "leaves the slot valid, so no refill happens and nothing is re-read. "
        "Neither single-line mutant fires A1. ⭐ A must-fire has to be built "
        "against the MECHANISM, not against the name of the invariant -- and a "
        "mutant that does not fire is a statement about the design worth "
        "recording, not a failed attempt to be deleted."),
    "M_CK_HOLD_INVAL": (1,
        "ONE LINE IN ONE ARM: the clean arm is EMPTY, because a held clocked "
        "action is defined by retiring nothing, so the mutant adds the "
        "invalidation rather than replacing anything. ⛔ WHAT IT BREAKS IS "
        "F1's ZERO-FLOP REBASE, which reads the parked lane's delay out of "
        "`l_act[hix[gi]]` and is sound ONLY because a held action leaves its "
        "slot valid. Under the mutant the prefetch refills the head slot with "
        "the NEXT action's word while the park is still waiting, so the lane "
        "releases on a delay belonging to a different action. ⚠ IT IS INVISIBLE "
        "TO EVERY COUNT-BASED CHECK -- the dispatch count is unchanged and the "
        "clock still looks like a clock -- which is why "
        "`clocked_conform.vh`'s A1 arm snapshots the word and compares it on "
        "every re-dispatch. ⭐ The whole saving rested on an arm that does "
        "nothing, and an emptiness cannot be read as deliberate; now it is "
        "checked. ⚠⚠ MEASURED: THIS MUTANT DOES **NOT** FIRE A1, and that is "
        "recorded rather than hidden. The PC does not advance during a hold, so "
        "the prefetch re-reads the same address and restores an IDENTICAL "
        "word -- the delay the park reads stays correct. What it really breaks "
        "is Amendment A1's PORT premise: a refill per DISPATCH instead of per "
        "ACTION, and re-dispatch counts moved 1229 -> 1061 on `corpus_i2c`. "
        "`M_CK_HOLD_PCADV` is the arm that reaches the delay hazard. "
        "⭐⭐ AND IT IS NO LONGER A SURVIVOR (ruling R). It survived every gate "
        "in this repo for an entire arc -- A1 cannot see it, Layer B cannot "
        "see it, and the coverage sweep covers its lines either way -- so the "
        "suite read 20 of 20 while the premise `D*` is computed from went "
        "unchecked. `clocked_conform.vh`'s Layer R counts PREFETCH REFILLS per "
        "retired clocked action against a bound DERIVED from the buffer depth "
        "(`dut.u_eng.SPL`, one fill per slot), and `model/gate_port_demand.py` "
        "requires this mutant RED on all three clocked images: MEASURED 16, 16 "
        "and 17 refills against a bound of 2, with the clean design at 1, 1 "
        "and 2 over 632 retired actions."),
    "M_CK_OD_CLK_DRIVE": (4,
        "TWO LINES IN EACH ARM: the open-drain side of the self-clocked HIGH "
        "phase DRIVES a hard 1 on SCL instead of releasing it. ⛔⛔ IT IS D2's "
        "MUST-FIRE IN THE PATH THAT IS ACTUALLY LIVE. D2's defect was an "
        "open-drain clock driven high -- against a peer stretching by holding "
        "SCL low, that is a SHORT, not a slow bit. Its original mutant "
        "(`M_OD_CLK_PUSHPULL`) lives in the UNCLOCKED arm, which the "
        "self-clocked rework made unable to express it; this one sits where "
        "every clocked open-drain HIGH now goes. `test/gate_corpus_trace.py` "
        "requires (a) the cross-program open-drain invariant to REPORT hard-1 "
        "cycles under it on `corpus_i2c`, and (b) a bench-held SCL low to "
        "CONTEND (X on the line) against it while staying clean against the "
        "real design."),
    "M_SHIFTIN_UNHELD": (7,
        "SEVEN LINES IN THE CLEAN ARM AND NONE IN THE MUTANT'S, declared: the "
        "fix ADDS a branch -- the clock-low SHIFTIN release loads the hold "
        "pipeline (a three-line condition, three pipeline writes, `end else`; "
        "W6 added the condition's `pin_oe[a_pin]` line) -- and the "
        "mutant removes it, leaving the original unconditional release. There "
        "is no single expression to swap: holding is three register writes. "
        "RULING K3's must-fire: `model/gate_sda_hold.py` requires the "
        "corpus_i2c SHIFTIN class to read hold 0 under it (it measured 0 on "
        "every release before the fix)."),
    "M_HOLD_CLOCKED_ONLY": (2,
        "ONE LINE IN EACH ARM: the refusal's scope `(ck_act | uc_hold)` back "
        "to `ck_act`. RULING U's must-fire: `model/gate_sda_hold.py` requires "
        "the unclocked frame at d = SDA_HOLD to RUN under it (the clean build "
        "refuses it). ⚠ Its setup moves are gone since W1 holds the release "
        "back in silicon, so the RUN is the observable."),
    "M_TF1_LATE": (6,
        "TWO SITES BY DESIGN, ONE SUBSTITUTION EACH: TF1 registers two things "
        "computed from next-state values -- the EDF key `key_q` (TF1 block, "
        "one line each arm) and, since TF2-R3, the release term `rel_q` (lane "
        "block: one line in the mutant arm against the clean arm's four-line "
        "expression with M_TF2_LIVE_LATE nested inside it). The mutant is the "
        "naive retiming of BOTH, which is what TF1's must-fire is about. "
        "Killed by `test/run_lockstep.py` (12 of 12 streams move)."),
    "M_NO_HOLD_GATE": (2,
        "ONE LINE IN EACH ARM: `ready` drops the W1 term `l_hcnt == 0`, so a "
        "lane may dispatch its SCL release while its own hold + setup is still "
        "running. The hold itself still lands on time. RULING W5's must-fire: "
        "`model/gate_sda_hold.py` requires Layer H red with data moves while "
        "SCL is released -- MEASURED 11 of 562 on ckhold_over and 10 / 3 on "
        "i2cframe at d = 16 / 17, the recorded findings."),
    "M_SHIFTIN_UC_UNHELD": (6,
        "SIX LINES IN THE CLEAN ARM AND NONE IN THE MUTANT'S, the same shape "
        "as M_SHIFTIN_UNHELD: W2 ADDS a branch (a two-line condition, three "
        "pipeline writes, `end else`) routing the UNCLOCKED SHIFTIN/READBIT "
        "release through the hold pipeline, and the mutant removes it. RULING "
        "W5's must-fire: `model/gate_sda_hold.py` requires the SHIFTIN release "
        "hold on i2cframe d = 16 to fall under SDA_HOLD (MEASURED 14) and Layer "
        "H red."),
    "M_NO_STORE_FULL": (2,
        "ONE LINE IN EACH ARM, in `project.v`: the engine's run input is `run` "
        "instead of `run & store_full`, so the chip executes whatever the "
        "unreset store holds after a partial load. ⛔ RULING M5's MUST-FIRE: "
        "`test/store_run.sh` loads `corpus_i2c` as its 51 program bytes on "
        "this build and requires it to RUN (1317 writebacks measured), while "
        "the clean build refuses the same load with 0 writebacks and "
        "CONFIG_ERR; `model/gate_store_full.py` holds both."),
    "M_PFETCH_BOTH_INVAL": (1,
        "ONE LINE IN ONE ARM: the clean arm is EMPTY, because a retiring "
        "dispatch invalidates its HEAD and nothing else -- the mutant adds the "
        "SPARE's invalidation rather than replacing anything. ⛔⛔ IT IS "
        "RULING R4's MUST-FIRE, AND IT IS AIMED AT A SENTENCE RATHER THAN AT A "
        "BEHAVIOUR. Theorem 3's P10 reads \"a dispatch consumes a valid head "
        "and leaves AT MOST ONE slot per lane to be refilled\", and "
        "`D* = k * L_REFILL` counts exactly one refill per lane per period from "
        "it. Under this mutant one dispatch leaves TWO slots to refill, so the "
        "port demand is double what the published bound is computed from. "
        "⚠ IT IS A DIFFERENT DEFECT FROM `M_CK_HOLD_INVAL`, which Layer R "
        "catches: that one raises the RATE (a refill per dispatch instead of "
        "per action) while keeping one refill owed per dispatch, so it passes "
        "R4a and fails R. This one keeps the rate and breaks the per-dispatch "
        "premise, so it fails R4a and passes R. ⇒ Two layers, two mutants, "
        "neither redundant -- which is the whole reason R4 was ordered "
        "separately from R after R checked a rate rather than the premise."),
    "M_CK_REBASE_2D": (2,
        "ONE LINE IN EACH ARM, against the SAME `ck_rebase` wire its sibling "
        "mutates -- `rise + 2d` instead of `rise + d`. ⛔ IT IS THE 'TOO LATE' "
        "DIRECTION, AND NOTHING ELSE CATCHES IT: `t_HIGH >= d` still holds, so "
        "G1's lower bound stays green and the UM10204 hold floor stays green, "
        "while the clock period is simply wrong. ⭐ That is the argument for "
        "bounding the gap on BOTH sides -- a one-sided bound is half a check, "
        "and this arm is what makes the other half non-vacuous."),
    "M_CK_RISE_ELIGIBLE": (2,
        "ONE LINE IN EACH ARM: `ck_rebase` is a wire, so the mutant drops the "
        "`+ d` and rebases a parked clocked lane to `now`. ⛔ WHAT IT BREAKS IS "
        "COMPLIANCE, and it is the pre-fix design rather than an invented "
        "defect: releasing the next dispatch AT the observed rise makes the SCL "
        "HIGH phase the synchroniser latency, so t_HIGH is not programmable at "
        "all. ⭐ MEASURED, WITH A CONTROL ARM AND A SCALING FALSIFIER -- t_HIGH "
        "FLAT at 6 cycles while the programmed delay spanned 13x (d = 9, 25, "
        "60, 120) and t_LOW tracked d exactly (7, 26, 58, 119), against "
        "push-pull `ckfive` in the SAME bench reading t_HIGH = 25 = d. UM10204 "
        "wants 13 cycles (Fm+), 30 (Fm), 200 (Sm) at 50 MHz, so the clocked "
        "scheme met no I2C mode. ⚠ Layer B reported OK throughout, because a "
        "park changes TIMING and not the DISPATCH COUNT -- the same blindness "
        "`M_CK_NO_PARK` records, and the reason gap conformance is now checked "
        "too."),
    "M_CK_NO_ALTERNATE": (2,
        "ONE LINE IN EACH ARM. The next phase is a wire (`ck_norm`), so the "
        "mutant substitutes `ck_next = CK_LOW`. ⛔ WHAT IT BREAKS: the phase "
        "never leaves LOW, so the clock is taken down and never released and "
        "the action never reaches its retire condition -- LAYER A of the bench "
        "watchdog trips in every bench running a clocked program, and the "
        "foreign decoder would find no byte at all."),
    "M_CK_NEVER_RETIRE": (2,
        "ONE LINE IN EACH ARM: `ck_hold_eff = ck_act` instead of `ck_hold`, so "
        "a clocked action holds for ever. ⭐ THIS IS LAYER A'S MUST-FIRE, the "
        "one the ruling asked for by name: a never-retiring lane must trip the "
        "COARSE liveness check, which is model-independent on purpose. "
        "MEASURED: layer A fires, layer B stays silent -- because layer B only "
        "compares actions that DID retire, which is exactly why one layer "
        "cannot do both jobs."),
    "M_CK_NO_PHASE_RESET": (3,
        "ONE LINE AGAINST TWO -- the clean arm needs both the reset and the "
        "advance it falls back to -- and ⚠ A CHARACTERISED SURVIVOR rather than a "
        "kill -- which is the useful result. It removes the action-start phase "
        "reset the ruling ordered. Neither watchdog layer fires, and the "
        "reason is structural: with the phase machine as the golden model "
        "specifies it, every clocked action already LEAVES the phase at LOW (a "
        "SHIFT retires from HIGH -> LOW, a SHIFTIN from COLL -> LOW) and "
        "power-on resets it. The reset is DEFENSIVE -- it covers a lane halted "
        "mid-action and restarted -- not load-bearing for any program the "
        "suite builds. ⛔⛔ AND IT IS WHAT LOCATED THE REAL ROOT CAUSE: the "
        "retire chain read `a_op != OP_REARM && !ck_hold`, so a held clocked "
        "action (level = 1 by definition of the trigger) fell into the "
        "`else if (a_lvl)` looping-REARM arm and jumped its PC to the lane "
        "base. Correct by derivation, unevidenced by test, recorded rather "
        "than killed with a contrived program -- as `M_BUF_CHAINFLIP` is."),
    "M_ACK_DRIVES_SDA": (2,
        "ONE LINE IN EACH ARM: `{oe, out}` is a wire, so the mutant is `2'b11` "
        "for `2'b00`. ⭐ IT CANNOT PERTURB THE CLEAN BUILD -- with `ack_drv[1]` "
        "low the `pin_out` write it feeds is never taken, so every unclocked "
        "SHIFTIN path is bit-for-bit what it was. ⛔ WHAT IT BREAKS, which is "
        "ruled condition (a): the ACK slot DRIVES the data pin high while the "
        "peer pulls it low to acknowledge -- on an open-drain net a push-pull "
        "high against a low, which is a SHORT and which the per-net-type "
        "overlap rule must refuse. ⚠ Deliberately NOT a wrong-bit mutant: "
        "forcing the pin LOW would read as a permanent ACK, which is the NACK "
        "test's job. Two defects, two arms."),
    "M_SHIFT_CLK_ALIAS": (6,
        "a BLOCK substitution, declared: the refusal has to suppress BOTH the "
        "data write and the clock write, so removing it removes an if/else "
        "whose begin and end bracket two separate assignment groups -- the "
        "`else begin` and its closing `end` are in different `ifndef` arms. "
        "⚠ The first version of the guard put only the data write inside the "
        "else, and the clock write then drove the aliased pin anyway: a "
        "refusal that still drives the pin it refuses is the defect with a "
        "flag set beside it."),
    "M_TIMEOUT_PROCEED": (6,
        "a BLOCK substitution, declared: the mutation removes the halt -- "
        "clearing l_live, l_armed and the sticky flag -- and there is no single "
        "expression whose value expresses 'do not halt'. The arms share no "
        "duplicated logic; the whole block is the delta."),
    "M_OD_CLK_PUSHPULL": (9,
        "a BLOCK substitution, declared: restoring D2 means removing BOTH the "
        "l_mode branch on the clock pin AND the 1.5 pin_pp mask, because with "
        "1.5 built the mask alone would suppress the hard 1 and the mutant "
        "would no longer reproduce the defect it prices. Two coupled changes, "
        "so no single expression carries it. ⛔⛔ AND IT IS NOW AN EQUIVALENT "
        "MUTANT, recorded rather than deleted. It sits in the UNCLOCKED SHIFT "
        "arm, and the self-clocked rework sends every `clk_real & level = 1` "
        "SHIFT to the clocked arm -- so here `a_lvl` is always 0 whenever "
        "`clk_real` holds, and `pin_out <= a_lvl; pin_oe <= 1` writes exactly "
        "the pull-low the clean design writes. No image can kill it. Found by "
        "ruling Q2: `gate_corpus_trace` had been unbuildable since `7a672b0`, "
        "and the first run after the repair showed this must-fire at 0 hard-1 "
        "and 0 contended cycles. D2's must-fire is now `M_CK_OD_CLK_DRIVE`, in "
        "the arm the defect can still reach."),
}


def discover():
    """⛔ MATCH `ifdef`/`ifndef`, NOT A BARE `M_` PATTERN. A loose scan for
    `M_[A-Z_]+` reports `M_TYPE`, which does not exist -- it is the tail of
    `MEM_TYPE`. That is the same false-positive class as `F7` in the ruling
    audit, and a phantom mutant with an empty diff would trip rule 3 forever."""
    found = set()
    for fn in SOURCES:
        with open(os.path.join(SRC, fn), encoding="utf-8") as fh:
            for m in re.finditer(r"`(?:ifdef|ifndef)\s+(M_[A-Z0-9_]+)", fh.read()):
                found.add(m.group(1))
    return sorted(found)


def preprocess(fn, define=None):
    out = os.path.join(tempfile.gettempdir(), "pe_pp_%s.v" % (define or "off"))
    cmd = [tool("iverilog"), "-E", "-o", out]
    if define:
        cmd.append("-D" + define)
    cmd.append(os.path.join(SRC, fn))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0 or not os.path.isfile(out):
        return None
    with open(out, encoding="utf-8", errors="replace") as fh:
        # ⛔ BLANK LINES ARE DROPPED. The preprocessor emits an empty line
        # where each `ifdef`/`else`/`endif` stood, so when the two arms differ in
        # length those blanks SHIFT and a line differ reports them as changes --
        # it made every delta read 3x its real size. Whitespace is not a mutation
        # class, so removing it is safe and makes the count mean what it says.
        return [ln.rstrip() for ln in fh if ln.strip()]


def diff_lines(a, b):
    """The changed lines, as (sign, text). A plain set difference is enough:
    we only need WHAT changed, not where."""
    import difflib
    out = []
    for ln in difflib.unified_diff(a, b, lineterm="", n=0):
        if ln.startswith("+++") or ln.startswith("---") or ln.startswith("@@"):
            continue
        if ln.startswith("+"):
            out.append(("+", ln[1:].strip()))
        elif ln.startswith("-"):
            out.append(("-", ln[1:].strip()))
    return out


def is_comment(t):
    return t.startswith("//") or t.startswith("/*") or t.startswith("*")


def audit(src_dir=None):
    """Returns (rc, rows). `src_dir` lets the must-fire point at a mutated copy."""
    global SRC
    saved, rc, rows = SRC, 0, []
    if src_dir:
        SRC = src_dir
    try:
        for mut in discover():
            changed = []
            for fn in SOURCES:
                off = preprocess(fn)
                on = preprocess(fn, mut)
                if off is None or on is None:
                    rows.append((mut, 0, 0, 0, "*** preprocess FAILED"))
                    rc = 1
                    break
                changed += diff_lines(off, on)
            else:
                nadd = sum(1 for s, _ in changed if s == "+")
                ndel = sum(1 for s, _ in changed if s == "-")
                ncmt = sum(1 for _, t in changed if is_comment(t))
                flags = []
                exp, reason = EXPECT.get(mut, (None, None))
                if ncmt:
                    flags.append("%d COMMENT line(s) inside an arm: the ifdef "
                                 "wraps more than the delta" % ncmt)
                if nadd + ndel == 0:
                    flags.append("EMPTY: this mutant changes nothing")
                if nadd + ndel > MINIMAL and not reason:
                    flags.append("%d lines with no declared reason (budget %d)"
                                 % (nadd + ndel, MINIMAL))
                if exp is None:
                    flags.append("NOT IN THE EXPECT TABLE -- unreviewed")
                elif nadd + ndel != exp:
                    flags.append("DRIFT: %d diff lines, expected %d"
                                 % (nadd + ndel, exp))
                if flags:
                    rc = 1
                rows.append((mut, nadd, ndel, ncmt, "; ".join(flags)))
    finally:
        SRC = saved
    return rc, rows


def main() -> int:
    banner("iverilog")   # ruling V2: the log names the binary that ran
    print()
    print("=" * 78)
    print("MUTANT ARM DRIFT GUARD -- the ifdef wraps the minimal delta")
    print("=" * 78)
    muts = discover()
    print("  mutants discovered (from `ifdef`/`ifndef`): %d" % len(muts))
    print()
    rc, rows = audit()
    print("  %-22s %5s %5s %5s  %s" % ("mutant", "+", "-", "cmt", "verdict"))
    print("  " + "-" * 74)
    for mut, nadd, ndel, ncmt, flags in rows:
        print("  %-22s %5d %5d %5d  %s"
              % (mut, nadd, ndel, ncmt, flags or "minimal, as recorded"))

    print()
    print("  --- declared block substitutions ---")
    for mut, (n, reason) in sorted(EXPECT.items()):
        if reason:
            print("    %s (%d lines)" % (mut, n))
            for line in _wrap(reason, 66):
                print("        %s" % line)

    # ---- MUST-FIRE: a drifted arm has to FAIL -------------------------
    # ⛔ The guard exists because a real edit landed in the wrong arm, so it is
    # priced by doing that on purpose: an extra line inside one branch of an
    # `ifdef` must make this red.
    print()
    print("  --- must-fire: a deliberately drifted arm ---")
    mf = "did not run"
    with tempfile.TemporaryDirectory() as td:
        for fn in SOURCES:
            with open(os.path.join(SRC, fn), encoding="utf-8") as fh:
                txt = fh.read()
            if fn == "pe_engine.v":
                # inject a line into ONE arm of M_NO_PRIME, as happened for real
                txt = txt.replace("`ifdef M_NO_PRIME\n",
                                  "`ifdef M_NO_PRIME\n// drifted arm\n", 1)
            with open(os.path.join(td, fn), "w", encoding="utf-8") as fh:
                fh.write(txt)
        drc, drows = audit(td)
        bad = [r for r in drows if r[0] == "M_NO_PRIME" and r[4]]
        if drc != 0 and bad:
            mf = "FIRED: %s" % bad[0][4][:120]
        else:
            mf = "*** DID NOT FIRE -- the guard would miss a drifted arm"
            rc = 1
    print("    %s" % mf)

    print()
    print("=" * 78)
    print("  GATE mutant-arms: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * %d mutants, each checked for comment-free arms, a non-empty"
          % len(muts))
    print("      delta, a size budget with declared reasons (the duplication")
    print("      check), and no drift from the recorded diff.")
    print("    * the must-fire injects a line into ONE arm of M_NO_PRIME --")
    print("      the real failure -- and requires this gate to go red.")
    return rc


def _wrap(t, w):
    out, cur = [], ""
    for x in str(t).split():
        if cur and len(cur) + 1 + len(x) > w:
            out.append(cur)
            cur = x
        else:
            cur = (cur + " " + x) if cur else x
    if cur:
        out.append(cur)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
