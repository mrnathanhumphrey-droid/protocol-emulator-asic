#!/usr/bin/env python3
"""Mutation testing for the double-buffered action fetch.

THE ONE CLAIM: every piece of state the double buffer added is load-bearing --
break it and the smoke bench goes RED, for a stated reason.

⛔⛔ WHY THIS FILE EXISTS. `M-PREFETCH-STALE` has been NAMED in `pe_engine.v`
since S3 and was never mechanically runnable. A mutant that has never been seen
kill anything is an unmeasured artefact, exactly like a guard that has never
fired -- and this project has already shipped one of those (1.6s passed
unconditionally for a release because `bad` was unreachable). The double buffer
adds FOUR coupled pieces of state (two slots, a select bit, a fetch pointer that
runs ahead of the PC), and "the edge counts still look right" does not check any
of them: a lane dispatching a stale action still toggles its pin.

⭐ EACH MUTANT MUST DIE FOR ITS OWN STATED REASON, not merely die. The standing
rule in this project is that a red mutant has to be certified by its failure
MESSAGE -- a mutant that fails because the build broke, or because an unrelated
assertion tripped, is not evidence about the thing it mutates. So each entry
below names the assertion that must be the one to fire.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRATCH = os.environ.get("TEMP", "/tmp")

# ⛔⛔ WHAT ACTUALLY RAN, COUNTED -- NOT A HAND-SUMMED LIST. The verdict
# reported `len(MUTANTS) + len(TX_MUTANTS) + len(HALF_MUTANTS)` = 8 while
# THIRTEEN mutants were defined: the whole EDGE family was missing from the
# sum, and a new family would have been missing too. A summary value is not
# evidence until it is checked against its run, and this one had been
# reported as "8 of 8" for a long time.
# ⚠ Two EDGE entries are STRUCTURAL (F2) and are deliberately not built or
# run, so they are listed separately rather than silently inflating this.
RAN = []
SKIPPED_STRUCTURAL = []

SRC = ["test/tb_smoke.v", "src/pe_engine.v", "src/pe_store.v", "src/project.v"]
# ⭐ The reactive-release mutants run against a DIFFERENT bench: tb_edge drives
# protocol inputs during run, which tb_smoke never does. One runner, two
# benches, because a mutant has to be judged by the bench that can see it.
SRC_EDGE = ["test/tb_edge.v", "src/pe_engine.v", "src/pe_store.v",
            "src/project.v"]
# ⭐ T5.1 -- A THIRD BENCH, because the TX queue tag is invisible to the other
# two. `tb_smoke` and `tb_edge` never drive the host channel, so every
# OP_SHIFT they execute finds an empty queue and takes the underrun branch: a
# mutant on the queue-selection path has nothing to break there. `tb_tx` is
# what gives M_TX_IGNORE_TAG something to kill it with.
SRC_TX = ["test/tb_tx.v", "src/pe_engine.v", "src/pe_store.v", "src/project.v"]
SRC_PINRANGE = ["test/tb_pinrange.v", "src/pe_engine.v", "src/pe_store.v",
                "src/project.v"]
# ⭐ A FOURTH BENCH -- the HALF-DUPLEX one, where TX and RX live on ONE lane.
# `tb_tx` has SHIFT-only lanes and `tb_trace` runs real protocols without
# asserting byte identity, so neither can see a direction corrupting the other.
SRC_HALF = ["test/tb_half.v", "src/pe_engine.v", "src/pe_store.v",
            "src/project.v"]
# ⭐ THE BIT-ORDER MUTANT IS JUDGED BY A FOREIGN DECODER, so it lives with
# `run_i2c.py` rather than here: no bench of ours can tell a correctly ordered
# I2C byte from a reversed one -- that is the whole reason the defect survived.
# Named here so the mutant inventory is complete in one place.
ORDER_MUTANT = ("M_IGNORE_ORDER",
                "tie l_order to 0: the per-lane bit order is ignored",
                "judged by test/run_i2c.py (sigrok), not by a bench here")
# ⛔⛔ RULING MU -- THE CLOCKED FAMILY, on tb_trace with the shared
# `clocked_conform.vh` / `progress.vh` layers. Every one of these was killed
# ONCE, by a hand-run probe, and recorded in a spec; no runner re-ran any of
# them, so each "kill" was as old as the day it was last typed. Each entry
# names the LAYER that must fire -- a mutant that dies of another assertion
# has not been shown to be killed by the thing that claims it.
# ⚠ `OD_HARD1` is not a message but a TRACE predicate: an open-drain pin
# driven as a hard 1 (oe=1, out=1), read with `gate_corpus_trace.od_violations`
# -- the per-net-type contention rule `fram_i2c.v` states, applied to the
# resolved trace rather than restated here.
SRC_TRACE = ["test/tb_trace.v", "test/fram_i2c.v", "test/fram_spi.v",
             "src/pe_engine.v", "src/pe_store.v", "src/project.v"]
CLOCKED_MUTANTS = [
    ("M_CK_NEVER_RETIRE", "corpus_i2c", "i2c", "*** FAIL progress.vh[A]",
     "a clocked action holds for ever; Layer A (coarse liveness) is the one "
     "that must see a lane stop retiring."),
    ("M_CK_NO_ALTERNATE", "corpus_i2c", "i2c", "*** FAIL progress.vh[A]",
     "the clock phase never alternates, so the action never completes its "
     "bits; Layer A sees the lane stop retiring."),
    ("M_CK_NO_PARK", "corpus_i2c", "i2c", "*** FAIL clocked_conform[G1]",
     "the post-HIGH park is removed, so a release can follow the rise sooner "
     "than d; G1 (post-HIGH gap >= d) is the lower bound it breaks."),
    ("M_CK_HOLD_RETIRES", "corpus_i2c", "i2c", "*** FAIL clocked_conform[A1]",
     "a held clocked dispatch invalidates the slot AND advances the PC, so "
     "the refill brings the next action's word; A1 (head-slot word stable "
     "across a hold) is the one that must fire."),
    ("M_CK_REBASE_2D", "corpus_i2c", "i2c", "*** FAIL clocked_conform[A2]",
     "the release re-bases at rise + 2d -- too LATE; A2 (release within d + "
     "the lane's own budget after the observed rise) is the upper bound."),
    ("M_CK_HOLD_INVAL", "ckod_image", "none", "*** FAIL clocked_conform[R]",
     "a held dispatch invalidates its slot: a refill per DISPATCH, not per "
     "action -- Layer R's rate. (Also gate_port_demand, under Verilator.)"),
    ("M_PFETCH_BOTH_INVAL", "ckod_image", "none",
     "*** FAIL clocked_conform[R4a]",
     "one dispatch frees BOTH slots; R4a is Theorem 3's P10 checked "
     "verbatim. (Also gate_port_demand, under Verilator.)"),
    # ⛔⛔ THE EXPECTED REASON MOVED WITH RULING TF2, AND THIS IS WHY. Under the
    # mutant the FIRST refill files a never-written register: X in iverilog.
    # The dispatched action is all-X, so that lane's timestamp goes X. The OLD
    # serial select read `if (ready[k] && ...)`, and an X condition is FALSE
    # in an `if` -- the X lane was silently DROPPED, the engine ran on, and
    # Layer M later caught a filler fetch. The TREE select uses `?:`, which
    # PROPAGATES the X into `winner`, so the engine wedges after one dispatch
    # and progress.vh's liveness check is the first to fire.
    # ⭐ Silicon has no X, and the clean design never makes one (TF4 lockstep:
    # byte-identical streams). The defect is still caught where it is a
    # 2-state fact: verilator_trace.sh with -DM_PFETCH_NOWAIT, MEASURED after
    # TF on corpus_i2c -- SEEDS DISAGREE on both pairs.
    ("M_PFETCH_NOWAIT", "corpus_i2c", "i2c", "*** FAIL progress.vh",
     "P_CAP samples the store before the read is registered, so it files the "
     "PREVIOUS read's word -- on the first refill a never-written register, "
     "X in iverilog, which the tree select propagates until nothing retires. "
     "(Under Verilator --x-initial unique the same defect shows as seeds "
     "disagreeing, which is verilator_trace.sh's arm.)"),
    # ⛔⛔ SILICON FIX #2 (ruling TX1/TX2): the pre-fix host load, on the HIGH
    # phase after the 7th bit. Every timing layer passes it -- the dispatch
    # stream is byte-identical -- so the kill must be a VALUE: Layer V1 sees
    # the load off the model's load point and the 8th bit wrong.
    ("M_TX_LOAD_ANYPHASE", "corpus_i2c", "i2c", "*** FAIL clocked_conform[V1]",
     "the clocked SHIFT's host load fires on the HIGH phase after the 7th "
     "LOW, so the 8th bit is the next byte's first and the stream drifts a "
     "bit per byte (5B fed -> 00, B5, 6A, D5 on the wire); counts, gaps and "
     "widths are all exact, so only a value check can see it."),
    # ⛔⛔ SILICON FIX #3 (rulings PN1 / CI1), both parts, killed on VALUE by
    # Layer V-RX on the real SPI FRAM read (`corpus_spim`, its own feed):
    ("M_CKRX_HEADER_PIN", "corpus_spim", "spi",
     "*** FAIL clocked_conform[V-RX]",
     "a clocked SHIFTIN samples the lane HEADER's pin (MOSI) instead of the "
     "action's (MISO): the chip receives its own output, 00, while MISO "
     "carries 5B C4 -- every frame disagrees with the pins."),
    ("M_CKRX_PP_OBSERVED", "corpus_spim", "spi",
     "*** FAIL rx_e2e",
     "a push-pull clocked SHIFTIN waits for an OBSERVED rise; the SPI master's "
     "SCLK is a uo_out pin with no input path, so it never captures. Before "
     "RX1 every bit was consumed uncaptured (read as 0); since RX1's capture "
     "gate the receive lane DEADLOCKS, which only rx_e2e's completion rule "
     "names (V-RX and the coarse liveness check both stayed quiet)."),
    ("M_ACK_DRIVES_SDA", "corpus_i2c", "i2c", "OD_HARD1",
     "the clocked ACK drives SDA as a PUSH-PULL HIGH on an open-drain net "
     "while the peer pulls low to acknowledge -- a SHORT. The trace shows "
     "SDA with oe=1, out=1; the clean design shows none."),
    # ⭐ RULING CS1 -- silicon fix #6 undone: the CS async clear is released
    # with D = 1. inv_cdc.vh (in every DUT bench) checks the D net on the
    # two edges after each CS fall; the fix passes 344 falls on this image.
    ("M_CS_RAW_D", "corpus_sptgt", "tgt", "*** FAIL inv_cdc",
     "the MISO enable's D input is not qualified by the synchronised CS, so "
     "the async clear on CS releases with D = 1 -- a recovery hazard on the "
     "MISO pad enable that simulation and STA cannot see; inv_cdc names it "
     "on the first CS fall."),
    ("M_BUS_NO_PULLDOWN", "ckod_image", "none",
     "no action was observed to retire",
     "the DUT's pull-down is dropped from the ONE bus model, so a released "
     "open-drain clock never resolves as the engine expects and the clocked "
     "lanes never retire; progress.vh reports it."),
]
CLOCKED_SURVIVORS = {
    "M_CK_NO_PHASE_RESET": "CHARACTERISED SURVIVOR (pe_engine.v records why): "
                           "every clocked action already leaves the phase at "
                           "LOW and power-on resets it, so the reset is "
                           "defensive (a lane halted mid-action) and no "
                           "program the suite builds can see its removal.",
    "M_OD_CLK_PUSHPULL": "EQUIVALENT in the clocked path: the self-clocked "
                         "rework routes every open-drain clocked HIGH through "
                         "the release arm, so the unclocked branch this "
                         "mutates cannot express the defect. D2's live "
                         "must-fire is M_CK_OD_CLK_DRIVE (gate_corpus_trace).",
}

HALF_IMG = "test/half_image.hex"
HALF_MUTANTS = [
    ("M_SHARED_BITP",
     "re-merge the TX and RX bit pointers into one",
     # ⛔ THE BYTE-CONTENT CHECK, not "*** FAIL" (10-22 must-fire audit: any
     # failure at all -- a timeout, a liveness line -- satisfied it). MEASURED:
     # it dies of `lane 0 byte 1: got 90 want 69 *** FAIL`.
     re.compile(r"lane \d byte \d+: got [0-9a-f]{2} want [0-9a-f]{2} \*\*\* FAIL"),
     "⛔ WHAT SHIPPED FOR THE LIFE OF THE HOST CHANNEL. OP_SHIFT and OP_SHIFTIN "
     "shared the bit pointer, so the RX byte-complete reset at `a_cnt - 1` "
     "always fired BEFORE the TX host load at `a_cnt`: on corpus_i2c, 124 "
     "OP_SHIFT dispatches produced 0 loads and 0 underruns -- no byte was ever "
     "even REQUESTED, and every I2C and SPI-master result exercised the shift "
     "mechanics without sending a real byte. ⭐ WITH THE POINTER RE-MERGED THE "
     "KILL IS WORSE THAN THE ORIGINAL SYMPTOM, which is the informative part: "
     "the load now fires sometimes and delivers CORRUPTED bytes (lane 0 emits "
     "60 09 48 2b where 96 69 c5 3a was pushed), because `l_tx` and `l_rx` are "
     "split while the pointer is not. Plausible wrong data beats no data for "
     "danger, and it is why the register had to split WITH the pointer rather "
     "than after it."),
    ("M_RX_NO_LANE",
     "pin the RX frame's lane field to 0: every byte looks like lane 0's",
     "no frame was attributed to lane 1",
     "⛔ WHAT SHIPPED IN EFFECT. `rx_push`/`rx_data` were engine-wide and the "
     "serial frame was {marker, 8 data} with NO lane field, so a host with two "
     "receiving lanes could not attribute a byte -- the mirror image of the TX "
     "queue-tag problem that per-lane queues solved, and found the same way: by "
     "feeding the channel and watching the arithmetic fail to add up (50 bytes "
     "delivered where 40 were assembled, the difference being exactly the other "
     "lane's). ⭐ THE MUTANT KEEPS THE FRAME WIDTH and only pins the field, so "
     "the bench still decodes and the kill is an ATTRIBUTION failure rather "
     "than a framing one -- the host sees L0=50, L1=0 where the truth is L0=10, "
     "L1=40. A mutant that broke the framing would die of the wrong "
     "assertion."),
]
TX_IMG = "test/tx_image.hex"
PINNONE_IMG = "test/pinnone_image.hex"
ARMNONE_IMG = "test/armnone_image.hex"

#: ⛔ EACH PINRANGE MUTANT HAS ITS OWN PROGRAM AND MODE, and each gets
#: its OWN baseline below. A family that shared one baseline would report
#: "the mutant killed it" for an arm whose unmutated run was never
#: checked -- which is unreadable, not evidence.
PINRANGE_ARMS = {
    "M_UNGUARDED_SAMPLE": (PINNONE_IMG, "1"),
    "M_UNGUARDED_ARMPIN": (ARMNONE_IMG, "2"),
}
TX_BADCLK_IMG = "test/tx_badclk_image.hex"
# (define, what it breaks, the text that certifies the kill, why, which image)
# ⭐ TWO IMAGES, because the two mutants break DIFFERENT claims: the tag mutant
# needs a legal two-lane program to misroute bytes in, and the clock-alias
# mutant needs the ILLEGAL program whose refusal it removes. A single image
# could not kill both.
TX_MUTANTS = [
    ("M_TX_IGNORE_TAG",
     "host_q becomes a constant: every lane pops queue 0",
     "the queue tag was ignored",
     "⛔ THE SILENT-CORRUPTION CLASS. The engine pops a queue, the lane shifts "
     "what it got, and the wire carries a WELL-FORMED FRAME WITH ANOTHER "
     "LANE'S PAYLOAD -- no assertion in the design fires, no flag is set. "
     "With two TX lanes active, consumption order is the EDF interleave, so "
     "the host cannot predict which lane takes the next byte; the action's "
     "queue field is the whole mechanism that makes that safe. ⚠ The kill is "
     "certified by the CROSS-LANE diagnosis, not by a value mismatch: the "
     "bench scans every byte a lane emitted against every byte of the other "
     "queue, because the narrow 'byte 0 vs byte 0' check did NOT fire (lane 1 "
     "gets queue 0's SECOND byte, since lane 0 took the first) and the mutant "
     "would have died of 'got 4e want 2d' -- a wrong reason.", "good"),
    ("M_SHIFT_CLK_ALIAS",
     "remove the 1.6x refusal of a SHIFT lane whose clk pin is its data pin",
     "1.6x: the aliased SHIFT was not refused",
     "⛔ OP_SHIFT writes the data pin and THEN the clock pin, so with "
     "`clkpin == pin` the clock write overwrites every data bit with the "
     "action's level field -- at level = 0 every 1 bit becomes a 0 and the "
     "wire carries a well-formed frame of the wrong data. ⚠ IT WAS LATENT FOR "
     "THE WHOLE LIFE OF THE HOST CHANNEL: nothing had ever fed a queue, so "
     "every OP_SHIFT ran on an all-zero shift register where losing the 1 bits "
     "changed nothing -- and `build_census` declared the alias on its shifting "
     "lane the entire time. ⭐ With the refusal removed the bad program RUNS "
     "and emits 36 bytes; with it, config_err is sticky, the lane halts, and "
     "nothing beyond the reset byte comes out.", "badclk"),
]

# ⛔⛔ THE OUT-OF-RANGE SAMPLE GUARD (Wilson's ruling 1). Its own family,
# because the claim lives in `tb_pinrange` and not in `tb_tx`.
PINRANGE_MUTANTS = [
    ("M_UNGUARDED_SAMPLE",
     "read pin_in[a_pin] with no range guard",
     "X on ser_d: the pin_in[a_pin] range guard is gone",
     "⛔ `a_pin` is a 4-bit PROGRAM-CONTROLLED field addressing 0..15 while "
     "only N_PINS = 12 pins exist, so `OP_SHIFTIN`/`OP_READBIT` on the "
     "reserved index reads OUT OF RANGE. The X went into `l_rx`, then "
     "`rx_data`, then the serial readback, and LEFT THE CHIP on `ser_d` "
     "while `ser_v` was high -- 112 cycles, one per SHIFT dispatch. "
     "⭐ IT IS THE MIRROR OF A DEFECT ALREADY FIXED: the WRITE side was "
     "guarded after the `pin_out[12]` incident and the READ side was not, "
     "which is fix-one-axis-miss-the-parallel-one for the second time. "
     "⚠ In silicon an out-of-range read is not X at all -- it is whatever "
     "synthesis made of it, deterministic but UNSPECIFIED, which is worse "
     "because nothing warns. The guard samples a defined 0 so the behaviour "
     "is a property of the RTL."),
    ("M_UNGUARDED_ARMPIN",
     "read pin_rise/pin_fall[l_armpin] with no range guard",
     "arm_hit went X: the l_armpin range guard is gone",
     "⛔ THE THIRD SITE IN THE SAME FAMILY, and the one the class sweep "
     "found. `l_armpin[cur] <= a_pin` is written straight from the action's "
     "4-bit pin field with nothing refusing it, and `pin_rise`/`pin_fall` "
     "are [N_PINS-1:0], so an OP_ARM naming 12..15 reads OUT OF RANGE. "
     "⭐ MEASURED: `arm_hit` X for ALL 198 armed cycles against 0 on a real "
     "pin, with the armed window counted so the result cannot be vacuous -- "
     "`arm_hit` is masked to 0 whenever no lane is armed, so a pin-level "
     "probe cannot see this at all. ⚠ `ready` did NOT go X: the terms it is "
     "ANDed with masked it, so this was never shown to reach the scheduler. "
     "Guarded anyway, because an X at a flop's input surviving on which "
     "terms happen to mask it is not a property to rely on."),
]
EDGE_MUTANTS = [
    ("M_NO_REBASE",
     "edge release leaves the timestamp at the ARM's DEADLINE",
     "MUST-FIRE 1 FAILED",
     "The sample grid then anchors to an arbitrary timeout instant instead of "
     "to the peer's edge, which for UART-rx misses every bit (0.9b derives the "
     "grid as edge + half + m*T). ⚠ Must-fire 4 does NOT catch this -- it still "
     "reports a constant offset, because its program uses timeout=0. Only the "
     "finite-deadline case distinguishes them."),
    ("M_TIMEOUT_PROCEED",
     "a timeout lets the lane carry on instead of halting",
     "MUST-FIRE 3 FAILED",
     "A program then cannot tell 'the peer answered' from 'the peer never "
     "answered' and would read a frame out of an idle line -- the forbidden "
     "direction one level up from an unsound bound."),
    ("M_NOOP_DRIVES",
     "remove the pin_real guard: a no-op drives its pin",
     "(characterised survivor -- structural only)",
     "⛔ NOT KILLABLE BY SIMULATION, and the reason is specific: with "
     "PIN_NONE = 15 on 12-wide vectors an out-of-range write is SILENTLY "
     "IGNORED by iverilog, so removing the guard changes nothing the bench can "
     "see. It DOES take effect -- the local netlist gains 3 cells, so the "
     "comparator is real logic, not documentation. ⭐ The guard's value is "
     "SYNTHESIS portability: out-of-range indexing is where tool behaviour "
     "diverges, which is the class that passed iverilog and died in Yosys "
     "once already. ⚠ The OBSERVABLE failure is a BAD PROGRAM, not this "
     "mutant: a no-op naming a real input pin, which tb_edge catches (135 "
     "drive cycles) and 1.6w rejects at load."),
    ("M_COMB_OUT",
     "restore the combinational prog_mode mux on the uio outputs",
     "(structural, checked by F2 on the local netlist)",
     "Not a simulation mutant: it is caught by model/f2_flop_driven_outputs.py "
     "on a yosys JSON netlist, where it shows up as $_ANDNOT_ driving the uio "
     "bits. Listed here so the full mutant inventory is in one place."),
]

DEFAULT_IMG = "test/smoke_image.hex"
# ⛔⛔ THE STRESS IMAGE IS NOT AN EXTRA, IT IS WHAT MAKES ONE MUTANT KILLABLE.
# The default program's delays are 20/31 against a ~4-cycle refill, so the
# prefetcher always wins and the steady-state stall is 0 with ONE buffer or
# TWO. Against it, M_BUF_SWAP SURVIVED -- and a bench that cannot tell the
# design from the mutant cannot evidence the design. Five active lanes at
# d = 12..16 is the regime where the buffering is observable at all.
# ⛔ IMPORTED, NOT RESTATED. These delays and `--all`'s were two recipes for
# one filename, which the clean-room check caught as the same file reproducing
# with different content. The generator owns them.
from make_smoke_image import FIVE_STRESS as STRESS_FIVE   # noqa: E402
from toolchain import banner, tool          # noqa: E402  ruling V
import sim_run                              # noqa: E402
#: the images tb_edge $readmemh's by hardcoded path (read from its source)
EDGE_IMGS = sim_run.hardcoded_images("tb_edge")
import scratch_heads                        # noqa: E402

# ⭐ SCRATCH MUTANTS (gate_mutant_kills SCRATCH): one-line patches applied at
# run time to the CURRENT src/ (test/scratch_heads.py), so the frozen RTL
# (CE5) carries no ifdef for them; a patch that no longer applies is RED.
SCRATCH_MUTANTS = {
    "S_HEAD_NEWER": "the engine reads a queue's NEWER slot (`~tx_rp`) "
                    "instead of its head -- bytes leave out of order",
    "S_QUEUE_SWAP": "queues 0<->1 have their heads swapped -- a lane pops "
                    "its own queue but sends the other queue's byte",
}
# (mutant, what it breaks, the text that certifies the kill)
# ⛔ S_HEAD_NEWER is certified by the ORDER check (MUST-FIRE 2's per-byte
# compare), not MUST-FIRE 1, whose label for a wrong first byte reads "not
# byte-aligned"; S_QUEUE_SWAP by the CROSS-QUEUE diagnosis, the attribution
# claim tb_tx exists to make (distinct per-queue data -- Wilson)
TX_SCRATCH = [
    ("S_HEAD_NEWER", "the head read from the newer slot",
     "lane 0 byte 1: got 7c want 4e"),
    ("S_QUEUE_SWAP", "queues 0<->1 heads swapped",
     "lane 0 emitted a QUEUE 1 byte -- the queue tag was ignored"),
]
STRESS_IMG = "test/five_image.hex"

# mode "assert": a named bench assertion must fire.
# mode "worse" : ⭐ DIFFERENTIAL. The mutant must be measurably WORSE than the
#   baseline on the SAME image. An absolute threshold cannot work here: the
#   bench's steady-J check is `> 2` and both the design (5) and the mutant (9)
#   exceed it, so an absolute check would "kill" the mutant while being equally
#   satisfied by the correct design -- a guard passing for the wrong reason,
#   which is this project's signature defect.
MUTANTS = [
    ("M_BUF_NOINVAL", "assert", DEFAULT_IMG,
     "swap without invalidating the consumed head slot",
     "buffer-swap invariant",
     "After two writebacks the lane dispatches the action it already ran: the "
     "old head is still valid and holds the consumed word, so the second swap "
     "selects it. This is the double-buffer form of M-PREFETCH-STALE."),
    ("M_BUF_SWAP", "worse", STRESS_IMG,
     "invalidate the head but never swap to the prefetched successor",
     "more steady-state stall events than the baseline",
     "The dispatched action stays CORRECT -- `fetch_addr` sees an invalid head "
     "and refills it from `l_pc` -- so no correctness assertion fires. What "
     "breaks is the jitter. This is the mutant that certifies the SWAP, rather "
     "than merely the second slot, is what buys the J reduction."),
    # ⛔⛔ A CHARACTERISED SURVIVOR, DECLARED AS ONE. It is NOT reclassified to
    # make this gate green: `effect` still asserts that the mutation CHANGES THE
    # DESIGN'S BEHAVIOUR, so it cannot become a no-op in silence. What is
    # declared is that its cost is below the bench's resolution -- verified, not
    # assumed: with it, lane 2's select bit flips 4 times instead of 3, and the
    # total refill count is IDENTICAL at 652. So the chaining asymmetry is
    # correct by derivation and unevidenced by test, which is the honest state.
    # ⭐ AND IT CORRECTED THE RTL: the comment there called the asymmetry a
    # correctness requirement, claiming a flip would dispatch the wrong action.
    # It would not -- the refill reloads `l_pc`, which a chaining re-arm has not
    # advanced, so the same action comes back. The mutant is what established
    # that, which is a mutant earning its place by surviving.
    # ⭐⭐ RULING 1(a)'s mutant. Releasing jobs before the buffers are primed is
    # the thing prime-before-release exists to prevent, and it must be visible.
    # ⛔ MEASURED cold = 76, not the 5 this project had been quoting. The old
    # engine counter AND the old bench both gated on `hdr_done`, so BOTH were
    # blind to the header-load window -- during which `now` ran, lanes were
    # released, and nothing could dispatch. Two independent reconstructions
    # sharing one blind spot read as agreement.
    ("M_NO_PRIME", "assert", DEFAULT_IMG,
     "release jobs before every lane's buffers are primed",
     "prime-before-release must-fire",
     "Without priming, `now` advances through the header load and the initial "
     "refills, so every lane's first job is released ALREADY LATE and the "
     "first-edge delay (76) differs from the steady-state one (0). That "
     "difference is differential jitter against D_tol on a source lane, which "
     "is why the cold start had to be removed rather than declared out of "
     "scope."),
    ("M_BUF_CHAINFLIP", "effect", DEFAULT_IMG,
     "swap on a chaining re-arm (PC does not advance)",
     "select-bit flip count must differ from the baseline",
     "Performance-only: one needless refill per park dispatch. No program the "
     "bench can build makes that visible in the worst-case stall, so this is "
     "declared a characterised survivor rather than killed by a contrived "
     "program -- but the mutation is still required to TAKE EFFECT."),
]


def make_stress():
    r = subprocess.run([sys.executable, "test/make_smoke_image.py", "--five"]
                       + [str(x) for x in STRESS_FIVE],
                       cwd=ROOT, capture_output=True, text=True)
    # ⛔ F6 (meta-test, 10-23): its exit code was ignored, so a failed
    # generation ran the stress arm on whatever five_image.hex was on disk
    if r.returncode != 0:
        raise SystemExit("*** make_stress: make_smoke_image --five exited %d: %s"
                         % (r.returncode, (r.stdout + r.stderr)[-300:]))


def steady(out):
    m = re.search(r"max prefetch stall, STEADY\s+:\s+(\d+)", out)
    return int(m.group(1)) if m else None


# ⛔⛔ THE "WORSE" MEASURE IS THE STALL-EVENT COUNT, NOT THE MAXIMUM, SINCE
# RULING TF3. The stress image is overloaded and below D*, which is exactly
# where TF3 changed the port's arbitration on purpose (a winner-first refill
# no longer moves the round-robin pointer). There the single worst stall is
# chaotic: MEASURED on `five_image`, baseline 7 -> 13 and M_BUF_SWAP 10 -> 11
# across the fix, and on five other sub-D* delay sets the mutant's MAXIMUM
# came out BELOW the baseline's. A maximum that a correct design can exceed
# is the wrong witness for "the swap buys the J reduction".
# ⭐ THE EVENT COUNT IS THE STEADY ONE: on `five_image` the mutant stalls 329
# times against 246 (TF RTL) and 417 against 287 (pre-TF) -- strictly worse
# on both, as a design that pays a full refill per dispatch must be.
def stall_events(out):
    m = re.search(r"stall EVENTS in steady state\s+:\s+(\d+)", out)
    return int(m.group(1)) if m else None


def flips(out):
    m = re.search(r"select-bit flips\s+:\s+(\d+)", out)
    return int(m.group(1)) if m else None


def build(defines, out, src=None):
    # ⛔ THE TOP IS DERIVED FROM THE BENCH FILE, NOT FROM LIST IDENTITY. This
    # read `src is SRC_EDGE`, so adding a third bench meant a third `is`
    # comparison and a silent fall-through to `tb_smoke` if one was forgotten
    # -- the mutant would then build the wrong top, pass, and be recorded as a
    # survivor for a reason that was not the mutation.
    files = src if src is not None else SRC
    top = os.path.splitext(os.path.basename(files[0]))[0]
    # `-I test -I .`: tb_trace and the shared layers include by repo path
    cmd = [tool("iverilog"), "-g2012", "-I", "test", "-I", ".",
           "-o", out, "-s", top]
    for d in defines:
        cmd += ["-D%s" % d]
    cmd += (src if src is not None else SRC)
    # ⛔⛔ UTF-8, EXPLICITLY. `text=True` uses the locale codec, which on this
    # box is cp1252 -- and every bench prints ⭐/⛔, so the reader thread raised
    # UnicodeDecodeError, DIED, and left the captured output TRUNCATED. The
    # verdicts below are parsed from that output, so a mutant could be judged
    # killed or survived from a partial stream. It presented as "the unmutated
    # tb_edge does not pass" while the same command passed by hand.
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run(vvp, img=DEFAULT_IMG, extra=None, hard=()):
    """`hard`: images the bench `$readmemh`s by hardcoded path (tb_edge), named
    so the helper's lookup sees every image the run loads."""
    cmd = sim_run.vvp([vvp] + ([] if img is None else ["+IMG=%s" % img])
                      + (extra or []),
                      images=([] if img is None else [img]) + list(hard))
    # ⛔⛔ UTF-8, EXPLICITLY. `text=True` uses the locale codec, which on this
    # box is cp1252 -- and every bench prints ⭐/⛔, so the reader thread raised
    # UnicodeDecodeError, DIED, and left the captured output TRUNCATED. The
    # verdicts below are parsed from that output, so a mutant could be judged
    # killed or survived from a partial stream. It presented as "the unmutated
    # tb_edge does not pass" while the same command passed by hand.
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                       encoding="utf-8", errors="replace")
    return (r.stdout or "") + (r.stderr or "")


def verdict(out):
    """(failures, which assertions fired). ⛔ Parsed, not eyeballed."""
    m = re.search(r"SMOKE:\s+(\d+)\s+FAILURE", out)
    n = int(m.group(1)) if m else (0 if "SMOKE: PASS" in out else None)
    fired = []
    if re.search(r"FAIL buffer-swap invariant", out) or \
       "THE HEAD SLOT DOES NOT HOLD THE ACTION" in out:
        fired.append("buffer-swap invariant")
    if "STEADY-STATE J EXCEEDS" in out:
        fired.append("STEADY-STATE J")
    if "C IS NOT 2" in out:
        fired.append("C")
    if "never moved its pin" in out:
        fired.append("edges")
    if "PRIME-BEFORE-RELEASE MUST-FIRE FAILED" in out:
        fired.append("prime-before-release must-fire")
    if "THE INVARIANT RAN" in out:
        fired.append("invariant vacuous")
    if "disagrees with the engine's" in out:
        fired.append("cold-max disagreement")
    return n, fired


def main() -> int:
    banner("iverilog", "vvp")   # ruling V2: the log names the binary that ran
    print()
    print("=" * 78)
    print("MUTATION TESTING -- the double-buffered action fetch")
    print("=" * 78)

    # ---- arm 0: the UNMUTATED build must PASS ------------------------
    # ⛔ Run this first. Every "the mutant died" below is meaningless if the
    # baseline is already red -- the mutants would be dying of the baseline's
    # illness and the run would read as perfect mutation coverage.
    base = os.path.join(SCRATCH, "mut_base.vvp")
    rc, log = build([], base)
    if rc != 0:
        print("  *** the UNMUTATED build does not compile:")
        print(log[:1500])
        return 1
    out = run(base)
    n, fired = verdict(out)
    print()
    print("  arm 0 -- baseline, no mutation: %s"
          % ("PASS" if n == 0 else "*** %s failures: %s ***" % (n, fired)))
    if n != 0:
        print("      Nothing below is interpretable: a mutant cannot be shown")
        print("      to kill an assertion that is already failing.")
        return 1
    # and the invariant must actually have run
    mchk = re.search(r"checks performed\s+:\s+(\d+)", out)
    print("      buffer-swap invariant checks in the baseline: %s"
          % (mchk.group(1) if mchk else "NOT REPORTED"))
    if not mchk or int(mchk.group(1)) < 100:
        print("      *** the invariant barely ran in the CLEAN build, so it")
        print("          cannot be credited with killing anything. ***")
        return 1

    # ---- the mutants -------------------------------------------------
    print()
    base_out_flips = out           # the baseline run on the DEFAULT image
    make_stress()
    _bs_out = run(base, STRESS_IMG)
    base_stress = stall_events(_bs_out)
    print("      baseline on the stress image: %s steady-state stall events "
          "(max stall %s)" % (base_stress, steady(_bs_out)))
    if base_stress is None:
        print("      *** the stress image produced no steady-state figure ***")
        return 1

    print()
    print("  %-18s %-7s %-28s %-9s %s"
          % ("mutant", "mode", "what it breaks", "verdict", "evidence"))
    survivors, wrong_reason = [], []
    for define, mode, img, breaks, want, why in MUTANTS:
        vvp = os.path.join(SCRATCH, "mut_%s.vvp" % define.lower())
        rc, log = build([define], vvp)
        if rc != 0:
            print("  %-18s %-7s %-28s BUILD FAIL -- not a kill"
                  % (define, mode, breaks[:28]))
            print("      ⛔ a mutant that does not COMPILE proves nothing about")
            print("         the bench. Fix the mutation, not the verdict.")
            print(log[:600])
            wrong_reason.append((define, "build"))
            continue
        out = run(vvp, img)
        n, fired = verdict(out)
        if mode == "assert":
            killed = (n is None) or (n > 0)
            right = want in fired
            evidence = ", ".join(fired) if fired else "(none)"
        elif mode == "worse":
            ms = stall_events(out)
            killed = ms is not None and base_stress is not None and ms > base_stress
            right = killed
            evidence = "stall events %s vs baseline %s (max stall %s)" % (
                ms, base_stress, steady(out))
        else:   # "effect" -- a characterised survivor that must still DO something
            fl = flips(out)
            bl = flips(base_out_flips)
            # ⛔ MORE flips, not different ones (10-22 must-fire audit): the
            # mutation adds a needless refill per park dispatch, so it can
            # only add swaps; a DROP would be a different defect. MEASURED
            # 343 vs 319 on the default image.
            killed = fl is not None and bl is not None and fl > bl
            right = killed
            evidence = "sel flips %s vs baseline %s" % (fl, bl)
        RAN.append(define)
        print("  %-18s %-7s %-28s %-9s %s"
              % (define, mode, breaks[:28],
                 "RED" if killed else "*** SURVIVED ***", evidence))
        print("      %s" % why)
        if not killed:
            survivors.append(define)
            if mode == "worse":
                print("      ⛔ the mutant is NOT worse than the design on this")
                print("         image, so the image does not exercise the")
                print("         mechanism. That is a statement about the BENCH.")
        elif not right:
            print("      *** it died, but NOT of `%s` -- it died of %s. A kill"
                  % (want, fired or "an unparsed failure"))
            print("          for the wrong reason is not evidence about this")
            print("          mutation. ***")
            wrong_reason.append((define, fired))

    # ---- the REACTIVE-RELEASE mutants, on tb_edge -------------------
    print()
    print("  --- edge-capture mutants (bench: tb_edge) ---")
    base_e = os.path.join(SCRATCH, "mut_edge_base.vvp")
    rc, log = build([], base_e, src=SRC_EDGE)
    if rc != 0:
        print("    *** tb_edge does not compile: %s" % log[:300])
        survivors.append("tb_edge build")
    else:
        out_e = run(base_e, img=None, hard=EDGE_IMGS)
        if "tb_edge: PASS" not in out_e:
            print("    *** the UNMUTATED tb_edge does not pass -- nothing below")
            print("        is interpretable.")
            survivors.append("tb_edge baseline")
        else:
            print("    baseline: PASS (4 of 4 must-fires)")
            for define, breaks, want, why in EDGE_MUTANTS:
                if define in ("M_COMB_OUT", "M_NOOP_DRIVES"):
                    SKIPPED_STRUCTURAL.append(define)
                    print("    %-19s %-40s %s"
                          % (define, breaks[:40], "structural -- see F2"))
                    print("        %s" % why)
                    continue
                v = os.path.join(SCRATCH, "mut_e_%s.vvp" % define.lower())
                rc, log = build([define], v, src=SRC_EDGE)
                if rc != 0:
                    print("    %-19s BUILD FAIL -- not a kill" % define)
                    wrong_reason.append((define, "build"))
                    continue
                o = run(v, img=None, hard=EDGE_IMGS)
                killed = "tb_edge: PASS" not in o
                right = want in o
                RAN.append(define)
                print("    %-19s %-40s %s"
                      % (define, breaks[:40],
                         "RED" if killed else "*** SURVIVED ***"))
                print("        %s" % why)
                if not killed:
                    survivors.append(define)
                elif not right:
                    print("        *** died, but not of `%s` ***" % want)
                    wrong_reason.append((define, "wrong reason"))

    # ---- the TX QUEUE mutants, on tb_tx -----------------------------
    print()
    print("  --- TX queue-ownership mutants (bench: tb_tx) ---")
    nb_tx = None
    tx_path = os.path.join(ROOT, TX_IMG)
    if not os.path.isfile(tx_path):
        print("    *** %s is missing. Build it:" % TX_IMG)
        print("        python test/make_smoke_image.py --tx 12 13")
        survivors.append("tb_tx image")
    else:
        # ⛔ NBYTES IS COUNTED FROM THE FILE, never passed as a literal. The
        # bench REFUSES to run without it, because an image that never loaded
        # emits nothing and "no bytes" would read as a queue fault.
        with open(tx_path, encoding="ascii") as fh:
            nb_tx = len([w for w in fh.read().split() if w])
    if nb_tx is not None:
        extra = ["+NBYTES=%d" % nb_tx, "+NCYC=6000"]
        base_t = os.path.join(SCRATCH, "mut_tx_base.vvp")
        rc, log = build([], base_t, src=SRC_TX)
        if rc != 0:
            print("    *** tb_tx does not compile: %s" % log[:300])
            survivors.append("tb_tx build")
        else:
            out_t = run(base_t, img=TX_IMG, extra=extra)
            if "tb_tx: PASS" not in out_t:
                print("    *** the UNMUTATED tb_tx does not pass -- nothing")
                print("        below is interpretable.")
                survivors.append("tb_tx baseline")
            else:
                print("    baseline: PASS (4 of 4 must-fires)")
                # ⛔ THE BAD-CLOCK IMAGE IS BUILT AND MEASURED HERE TOO,
                # and its BASELINE is the refusal: `tb_tx +BADCLK=1` passes
                # only if the engine refused the program. A mutant arm whose
                # unmutated run was never checked would make "the mutant
                # killed it" unreadable.
                bad_extra, bad_ok = None, False
                bp = os.path.join(ROOT, TX_BADCLK_IMG)
                if os.path.isfile(bp):
                    with open(bp, encoding="ascii") as fh:
                        nb = len([w for w in fh.read().split() if w])
                    bad_extra = ["+NBYTES=%d" % nb, "+NCYC=4000", "+BADCLK=1"]
                    ob = run(base_t, img=TX_BADCLK_IMG, extra=bad_extra)
                    bad_ok = "tb_tx: PASS" in ob
                    print("    baseline (1.6x image): %s"
                          % ("REFUSED, as it must" if bad_ok
                             else "*** the illegal program was NOT refused"))
                    if not bad_ok:
                        survivors.append("tb_tx 1.6x baseline")
                else:
                    print("    *** %s is missing. Build it:" % TX_BADCLK_IMG)
                    print("        python test/make_smoke_image.py --txbadclk")
                    survivors.append("tb_tx 1.6x image")
                for define, breaks, want, why, which in TX_MUTANTS:
                    if which == "badclk" and not bad_ok:
                        continue
                    use_img = TX_BADCLK_IMG if which == "badclk" else TX_IMG
                    use_extra = bad_extra if which == "badclk" else extra
                    v = os.path.join(SCRATCH, "mut_t_%s.vvp" % define.lower())
                    rc, log = build([define], v, src=SRC_TX)
                    if rc != 0:
                        print("    %-19s BUILD FAIL -- not a kill" % define)
                        wrong_reason.append((define, "build"))
                        continue
                    o = run(v, img=use_img, extra=use_extra)
                    killed = "tb_tx: PASS" not in o
                    right = want in o
                    RAN.append(define)
                    print("    %-19s %-40s %s"
                          % (define, breaks[:40],
                             "RED" if killed else "*** SURVIVED ***"))
                    print("        %s" % why)
                    if not killed:
                        survivors.append(define)
                    elif not right:
                        print("        *** died, but not of `%s` ***" % want)
                        wrong_reason.append((define, "wrong reason"))
                # ⭐ THE QUEUE-HEAD SCRATCH MUTANTS (Wilson): each a copy of
                # the CURRENT src/ plus one patch -- the frozen src/ untouched
                for name, breaks, want in TX_SCRATCH:
                    v = os.path.join(SCRATCH, "mut_t_%s.vvp" % name.lower())
                    d = scratch_heads.patched_srcdir(name, SCRATCH)
                    rc, log = build([], v, src=[SRC_TX[0]] + [
                        os.path.join(d, f) for f in
                        ("pe_engine.v", "pe_store.v", "project.v")])
                    if rc != 0:
                        print("    %-19s BUILD FAIL -- not a kill" % name)
                        wrong_reason.append((name, "build"))
                        continue
                    o = run(v, img=TX_IMG, extra=extra)
                    killed = "tb_tx: PASS" not in o
                    right = want in o
                    RAN.append(name)
                    print("    %-19s %-40s %s"
                          % (name, breaks[:40],
                             "RED" if killed else "*** SURVIVED ***"))
                    if not killed:
                        survivors.append(name)
                    elif not right:
                        print("        *** died, but not of `%s` ***" % want)
                        wrong_reason.append((name, "wrong reason"))

    # ---- the OUT-OF-RANGE SAMPLE mutant, on tb_pinrange -------------
    # ⛔ ITS BASELINE IS THE GUARD HOLDING, so a kill is readable: the
    # unmutated run must report ZERO serial X on the reserved-index program.
    print()
    print("  --- out-of-range sample mutants (bench: tb_pinrange) ---")
    if not os.path.isfile(os.path.join(ROOT, PINNONE_IMG)):
        print("    *** %s is missing. Build it:" % PINNONE_IMG)
        print("        python test/make_smoke_image.py --pinnone")
        survivors.append("tb_pinrange image")
    else:
        base_p = os.path.join(SCRATCH, "mut_pr_base.vvp")
        rc, log = build([], base_p, src=SRC_PINRANGE)
        if rc != 0:
            print("    *** tb_pinrange does not compile: %s" % log[:300])
            survivors.append("tb_pinrange build")
        else:
            for define, breaks, want, why in PINRANGE_MUTANTS:
                img_rel, mode = PINRANGE_ARMS[define]
                ip = os.path.join(ROOT, img_rel)
                if not os.path.isfile(ip):
                    print("    *** %s is missing for %s" % (img_rel, define))
                    survivors.append(define + " image")
                    continue
                with open(ip, encoding="ascii") as fh:
                    nbp = len([w for w in fh.read().split() if w])
                extra = ["+NBYTES=%d" % nbp, "+NCYC=8000", "+MODE=" + mode]
                out_p = run(base_p, img=img_rel, extra=extra)
                if "tb_pinrange: PASS" not in out_p:
                    print("    *** the UNMUTATED tb_pinrange does not pass on"
                          " %s -- %s is not interpretable."
                          % (os.path.basename(img_rel), define))
                    survivors.append(define + " baseline")
                    continue
                print("    baseline on %-22s PASS"
                      % os.path.basename(img_rel))
                v = os.path.join(SCRATCH, "mut_pr_%s.vvp" % define.lower())
                rc, log = build([define], v, src=SRC_PINRANGE)
                if rc != 0:
                    print("    %-19s BUILD FAIL -- not a kill" % define)
                    wrong_reason.append((define, "build"))
                    continue
                o = run(v, img=img_rel, extra=extra)
                killed = "tb_pinrange: PASS" not in o
                right = want in o
                RAN.append(define)
                print("    %-19s %-40s %s"
                      % (define, breaks[:40],
                         "RED" if killed else "*** SURVIVED ***"))
                print("        %s" % why)
                if not killed:
                    survivors.append(define)
                elif not right:
                    print("        *** died, but not of `%s` ***" % want)
                    wrong_reason.append((define, "wrong reason"))

    # ---- the HALF-DUPLEX mutants, on tb_half -------------------------
    print()
    print("  --- half-duplex mutants (bench: tb_half) ---")
    hp = os.path.join(ROOT, HALF_IMG)
    if not os.path.isfile(hp):
        print("    *** %s is missing. Build it:" % HALF_IMG)
        print("        python test/make_smoke_image.py --half 24")
        survivors.append("tb_half image")
    else:
        with open(hp, encoding="ascii") as fh:
            nbh = len([w for w in fh.read().split() if w])
        h_extra = ["+NBYTES=%d" % nbh, "+NCYC=40000"]
        base_h = os.path.join(SCRATCH, "mut_half_base.vvp")
        rc, log = build([], base_h, src=SRC_HALF)
        if rc != 0:
            print("    *** tb_half does not compile: %s" % log[:300])
            survivors.append("tb_half build")
        else:
            out_h = run(base_h, img=HALF_IMG, extra=h_extra)
            if "tb_half: PASS" not in out_h:
                print("    *** the UNMUTATED tb_half does not pass -- nothing")
                print("        below is interpretable.")
                survivors.append("tb_half baseline")
            else:
                print("    baseline: PASS (4 of 4 must-fires)")
                for define, breaks, want, why in HALF_MUTANTS:
                    v = os.path.join(SCRATCH, "mut_h_%s.vvp" % define.lower())
                    rc, log = build([define], v, src=SRC_HALF)
                    if rc != 0:
                        print("    %-19s BUILD FAIL -- not a kill" % define)
                        wrong_reason.append((define, "build"))
                        continue
                    o = run(v, img=HALF_IMG, extra=h_extra)
                    killed = "tb_half: PASS" not in o
                    right = (bool(want.search(o)) if hasattr(want, "search")
                             else want in o)
                    RAN.append(define)
                    print("    %-19s %-40s %s"
                          % (define, breaks[:40],
                             "RED" if killed else "*** SURVIVED ***"))
                    print("        %s" % why)
                    if not killed:
                        survivors.append(define)
                    elif not right:
                        print("        *** died, but not of `%s` ***" % want)
                        wrong_reason.append((define, "wrong reason"))
                # ⛔ THE PLANTED EDGE RACE (Wilson): MISO written blocking on
                # every rising edge. Not an RTL mutant -- a bench plusarg -- so
                # it is not in RAN; it must still turn the verdict red, and for
                # a receive reason (rx_e2e or a received byte), under THIS
                # simulator; the Verilator sweep holds the same arm as XFAIL.
                o = run(base_h, img=HALF_IMG, extra=h_extra + ["+PLANT_EDGE_RACE"])
                killed = "tb_half: PASS" not in o
                # ⛔ A FAILED receive check, not the name of one (10-22
                # must-fire audit): tb_half prints "RX2: rx_e2e checked ..."
                # on EVERY run, so `"rx_e2e" in o` was constant True.
                right = bool(re.search(r"\*\*\* FAIL rx_e2e|RX byte \d+: got "
                                       r"[0-9a-f]{2}, presented [0-9a-f]{2} "
                                       r"\*\*\* FAIL", o))
                print("    %-19s %-40s %s" % ("+PLANT_EDGE_RACE",
                      "MISO changed ON the sampling edge",
                      "RED" if killed and right else "*** SURVIVED ***"))
                if not killed:
                    survivors.append("+PLANT_EDGE_RACE")
                elif not right:
                    print("        *** died, but not of a receive check ***")
                    wrong_reason.append(("+PLANT_EDGE_RACE", "wrong reason"))

    # ---- RULING MU: the clocked family, on tb_trace --------------------
    # ⛔ BASELINE FIRST, per image: the unmutated design must produce ZERO
    # `*** FAIL` lines and ZERO open-drain hard-1 cycles, or no kill below is
    # readable. (Layer R failed the CLEAN design under iverilog until its
    # cross-block race was fixed -- found exactly here.)
    print()
    print("  --- clocked mutants (bench: tb_trace + clocked_conform/progress) ---")
    import benchset
    import gate_corpus_trace as gct

    def trace_run(vvp, img, peer):
        a2 = benchset.a2_slack_arg("test/%s.hex" % img)
        tr = os.path.join(SCRATCH, "mut_ck_trace.txt")
        extra = (["+NBYTES=256", "+PEER=%s" % peer, "+NCYC=40000",
                  "+OUT=%s" % tr, "+SEED=1", "+ASYNC=0", "+STAYLOAD=0",
                  "+SCLHOLD=0"] + ([a2] if a2 else [])
                 + gct.feed_args("test/%s.hex" % img))
        o = run(vvp, img="test/%s.hex" % img, extra=extra)
        _h, rows = gct.read_trace(tr)
        hard = len(gct.od_violations(rows, (gct.corpus.P_SCL, gct.corpus.P_SDA)))
        return o, hard, sim_run.trace_incomplete(o, extra)

    base_c = os.path.join(SCRATCH, "mut_ck_base.vvp")
    rc, log = build([], base_c, src=SRC_TRACE)
    ck_ok = rc == 0
    if not ck_ok:
        print("    *** tb_trace does not compile: %s" % log[:300])
        survivors.append("tb_trace build")
    else:
        for img, peer in sorted({(e[1], e[2]) for e in CLOCKED_MUTANTS}):
            o, hard, why = trace_run(base_c, img, peer)
            nf = o.count("*** FAIL")
            # ⛔ R3: a baseline that did not FINISH is not clean, FAIL lines
            # or not -- its verdicts print from `final` after any stop
            print("    baseline %-11s %d FAIL line(s), %d hard-1 cycle(s)   %s"
                  % (img, nf, hard, "clean" if nf == 0 and hard == 0 and not why
                     else "*** NOT CLEAN%s" % (" (%s)" % why if why else "")))
            if nf or hard or why:
                survivors.append("tb_trace baseline %s" % img)
                ck_ok = False
    if ck_ok:
        for define, img, peer, want, why in CLOCKED_MUTANTS:
            v = os.path.join(SCRATCH, "mut_ck_%s.vvp" % define.lower())
            rc, log = build([define], v, src=SRC_TRACE)
            if rc != 0:
                print("    %-19s BUILD FAIL -- not a kill" % define)
                wrong_reason.append((define, "build"))
                continue
            o, hard, _why = trace_run(v, img, peer)
            killed = ("*** FAIL" in o) or hard > 0
            right = (hard > 0) if want == "OD_HARD1" else (want in o)
            RAN.append(define)
            print("    %-19s %-11s %-34s %s"
                  % (define, img, want[:34],
                     "RED" if killed else "*** SURVIVED ***"))
            print("        %s" % why)
            if not killed:
                survivors.append(define)
            elif not right:
                print("        *** died, but not of `%s` ***" % want)
                wrong_reason.append((define, "wrong reason"))
        for define, why in sorted(CLOCKED_SURVIVORS.items()):
            print("    %-19s declared survivor -- %s" % (define, why[:90]))
    # ⛔ THE FEED LIMIT (a bench plusarg, not an RTL mutant, so not in RAN):
    # +FEEDN past `feedv`'s 16 bytes must stop the bench; 16 must not.
    # ⛔ F6 (meta-test, 10-23): gated on THE BASE tb_trace BUILD (ck_ok's
    # build), not on `rc` -- which was the LAST clocked mutant's build, so a
    # failed mutant build skipped these two arms in silence.
    if not os.path.isfile(base_c):
        print("    *** +FEEDN arms NOT RUN: the base tb_trace did not build")
        survivors.append("+FEEDN (no base build)")
    else:
        for n, want_fatal in ((17, True), (16, False)):
            o = run(base_c, img="test/corpus_spim.hex",
                    extra=["+NBYTES=256", "+PEER=spi", "+NCYC=2000",
                           "+OUT=%s" % os.path.join(SCRATCH, "mut_feed.txt"),
                           "+SEED=1", "+ASYNC=0", "+STAYLOAD=0", "+SCLHOLD=0",
                           "+FEEDN=%d" % n, "+FEED=%s" % ("11" * n)])
            fatal = ("tb_trace: FATAL -- +FEEDN=%d exceeds" % n) in o
            ok = fatal == want_fatal
            print("    %-19s %-40s %s" % ("+FEEDN=%d" % n,
                  "feed past 16 bytes refused" if want_fatal
                  else "16-byte feed accepted (control)",
                  ("RED" if want_fatal else "clean") if ok else "*** WRONG ***"))
            if not ok:
                survivors.append("+FEEDN=%d" % n)

    print()
    print("=" * 78)
    print("VERDICT")
    print("=" * 78)
    print("  mutants defined       : %d"
          % (len(MUTANTS) + len(TX_MUTANTS) + len(EDGE_MUTANTS)
             + len(HALF_MUTANTS) + len(PINRANGE_MUTANTS)
             + len(CLOCKED_MUTANTS) + len(CLOCKED_SURVIVORS)))
    print("  mutants RUN           : %d   %s"
          % (len(RAN), " ".join(sorted(RAN))))
    if SKIPPED_STRUCTURAL:
        # ⛔ NOT "F2 proves these": only M_COMB_OUT is F2's (gate_f2_local);
        # M_NOOP_DRIVES is a characterised survivor (see its entry).
        print("  structural, not run   : %d   %s  (M_COMB_OUT: gate_f2_local; "
              "M_NOOP_DRIVES: characterised survivor)"
              % (len(SKIPPED_STRUCTURAL), " ".join(sorted(SKIPPED_STRUCTURAL))))
    print("  survived (bad)        : %d  %s" % (len(survivors), survivors or ""))
    print("  died of a WRONG reason: %d  %s" % (len(wrong_reason),
                                                wrong_reason or ""))
    ok = not survivors and not wrong_reason
    print()
    if ok:
        print("  ⭐ every piece of double-buffer state is load-bearing, and each")
        print("     mutant died of the assertion it was supposed to trip.")
        print("     ⭐ M_BUF_SWAP is the informative one: it leaves behaviour")
        print("     CORRECT and breaks only the jitter, so it certifies that the")
        print("     swap -- not merely the existence of a second slot -- is what")
        print("     the J reduction comes from.")
    else:
        if survivors:
            print("  ⛔⛔ %d MUTANT(S) SURVIVED. The bench does not test what they"
                  % len(survivors))
            print("      break, so the double buffer's correctness is unevidenced")
            print("      in exactly that respect.")
        if wrong_reason:
            print("  ⛔ %d died for the wrong reason -- see above." % len(wrong_reason))
    # ⛔ POSITIVE TOKEN (Wilson): printed ONLY on the success path
    print()
    print("  GATE mutants: %s" % ("PASSED" if ok else "*** FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
