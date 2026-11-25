# v2 defects

Defects found in v2 RTL that is already in pushed history, recorded before their fix lands
(the order the 11-23 park ruling set for v1 errata). v1 (`v1-lock`) errata live in
`V1_ERRATA.md`; an entry here names whether v1 carries the defect.
Each entry names where it was found, what introduced it, how to see it, and the fix.

## V2E1 — an FT timeout leaves the edge word alive when the buffer loads it that same cycle (found 2026-11-24)

**What.** At a FALLTHROUGH timeout the K6 drop (Wilson 11-22) removes the lane's held
PC+2 word wherever it is: a tagged slot, the buffer, or a fetch in flight. In
`src/pe_engine.v` the drop reads the tags as they stand at the start of the cycle:

```verilog
if (tg_s[hix[winner]]) l_actv[hix[winner]] <= 1'b0;
if (tg_s[six[winner]]) l_actv[six[winner]] <= 1'b0;
if (tg_b[winner]) l_bufv[winner] <= 1'b0;
...
tg_s[hix[winner]] <= 1'b0;
tg_s[six[winner]] <= 1'b0;
tg_b[winner]      <= 1'b0;
```

Earlier in the same sequential block, the buffer load (`loadTo`, slot buffer piece 2)
moves a buffered word into the lane's empty spare (or empty head) and carries its tag
across. When the edge word sits in the buffer and the spare emptied the cycle
before, both fire in one cycle:

- the load writes `l_actv[spare] <= 1`, `tg_s[spare] <= 1`, `l_bufv <= 0`;
- the drop sees `tg_s[spare] = 0` (the old value), so it clears no slot; its
  `l_bufv <= 0` repeats the load's; its `tg_s[spare] <= 0` comes last and wins.

The PC+2 word ends the cycle valid in the spare with no tag. The drop missed it,
and nothing later knows it is the edge word.

**Effect.** The lane falls through to PC+1 still holding its old PC+2 word. The
FTTMO check fires the next cycle ("still holds its PC+2 after its FALLTHROUGH
timeout"). Once the lane's PC moves past that address the stale word reaches the
head, and SLOTORD fires ("the head holds the word of 40, its PC is 44"). Dispatch reads
the head, so the lane is set to issue the word of an address it has already passed.
The pin-level difference against the model has not yet been measured.

**Seen on.** Scratch images only, from the 11-24 targeted probe (Wilson's ruling of
11-24 on the unreached slot-buffer points). The start-up-order family
(`run_ftflush.dw_image(n, ds, wd)`, n 1–4, ds {2,4,6,8}, wd {4,6,8,10}) with timeouts
{2,4,8,16,40} and FT edges swept: 76 of its 320 images, 894 of 9,768 runs, every
one with the edge word in the buffer at the timeout, and no other run. Timeouts of 2
and 4 carry most of them. Smallest witness: `dw_image(1, 2, 8)`, timeout 2, no FT
edge — lane 0 times out at 53,606,000 with the spare empty and the buffer holding
its tagged PC+2; FTTMO at 53,623,000.

Not reached by `run_ftflush`'s 8 images (1,127 runs) or `run_slotbuf`'s 4, which is
why the gate set stayed green. The other images of record have not been measured
for it.

**Introduced in.** e15edaa (slot buffer piece 3, the K6 drop at every timeout), on
top of bf2401a's load. Identical on ab4d2fc: the same 894 runs give the same asserts
with and without the 11-24 stale-tag clears.

**v1.** Not present: `v1-lock` has no slot buffer and no FALLTHROUGH.

**Fix.** 07a1150: `tmo_drop` is the dispatch's own drop condition, term for term, and
`tmo_ldblk` stops both buffer loads for the timeout winner whose buffer is tagged, in
that cycle only. The word stays in the buffer, where the drop's `l_bufv <= 0` removes it.
The 894 runs above give 0 asserts on the fixed RTL. `M_FT_TMO_LOADRACE` removes the
block; `run_ftflush`'s `dwrace` (`dw_image(1, 2, 8)`, timeout 2) kills it, and
`dwrace2` (`dw_image(2, 6, 4)`, timeout 16) is the second witness. Both run clean.

## V2E2 — an FT ARM at another FT ARM's PC+1 or PC+2 breaks the lane's word order (found 2026-11-24)

**What.** Slot buffer piece 3 gives a FALLTHROUGH ARM its two words by the slot
requester: the edge word (PC+2) first, carrying the edge tag, then the timeout word
(PC+1). While those words are owed, an ARM captured for the lane does not raise a request
of its own (`src/pe_engine.v`, `cap_isarm`: "an ARM at its PC+1 / PC+2: no nested
raise"). `pe_isa` does not refuse that placement (`arm_lane_problems` checks only that an
FT ARM has a PC+2 and that it is not a SHIFT). So an inner FT ARM at the outer one's PC+1
or PC+2 runs with `ft_ne` / `ft_nt` / `sq_n` all clear and none of its words tagged, while
its writeback still applies K6's placement (`ft_k6 = OP_ARM && mod[1] && !ft_spt`, no test
of whether the ARM raised). Two faults follow:

- **A second copy of the inner ARM's PC+1 (SLOTORD).** The lane's head holds the word of
  the inner ARM's PC+1 after its PC has moved past it, so that word sits in the lane
  twice. Consistent with this path: with no request raised, nothing outranks the round
  robin, so at the inner ARM's no-swap writeback the scan can issue `l_fpc` (PC+1),
  untagged, into the spare (`ft_spt` does not see a fetch issued in that cycle), while the
  head, left empty, is refilled from `l_pc` (PC+1 again). **The cycle-by-cycle path has
  not been traced.**
- **An untagged PC+2 kept past the inner ARM's timeout (FTTMO).** The K6 drop removes only
  tagged words; the inner ARM's PC+2 was never tagged, so it survives the timeout.

**Effect.** SLOTORD fires; the head holds a word the lane's PC has passed, so dispatch is
set to issue an address the program has already executed. FTTMO fires when the inner ARM
times out still holding its PC+2. The pin-level difference against the model has not been
measured.

**Seen on.** Scratch images only, from the 11-24 probe of agent 2's `siss` question (an
untagged word issued into the spare in an FT ARM's no-swap writeback cycle). Lane 0 =
`[A, A', L0, L1, L0, loop]` (inner FT ARM at PC+1, "n1") or `[A, L0, A', L1, L0, loop]` (at
PC+2, "n2"), both ARMs on `run_arm2`'s pin A, timeouts {2, 8, 40}; lanes 1-4 idle or busy
(words of d = b + k, b in {2, 4, 6, 8, 10}); flips -1 and armed-6 .. armed+60, `tb_arm2`
with `run_ftflush`'s arguments. 2,448 runs on f04d66b:

- n1, idle port: SLOTORD in all 68 runs at every timeout, no edge needed. Smallest
  witness: n1, timeout 2, idle, no edge -- "lane 0's head holds the word of 40, its PC is
  44" (words from 32: the inner ARM is at 36, its PC+1 at 40).
- n1, busy port: FTTMO at timeout 40 (3 to 18 runs per image), none at 2 or 8 -- "still
  holds its PC+2 (44)", the inner ARM's PC+2.
- n2: SLOTORD at timeouts 8 and 40 (3 to 38 runs per image; at 40 on the idle port FTTMO
  too, 29 runs), none at 2.

No image of record places an ARM at an FT ARM's PC+1 or PC+2, which is why the gate set
stayed green.

**Introduced in.** e15edaa (slot buffer piece 3). The four strongest witnesses (n1 t2 idle,
n1 t40 b4, n2 t8 idle, n2 t40 idle; 272 runs each) built on the current `tb_arm2`:
bf2401a (piece 2, which has SLOTORD) 0 asserts; e15edaa 68 / 18 / 3 / 38 asserting runs;
f04d66b identical. FTTMO and the K6 drop first exist in e15edaa, so its half cannot be
checked earlier. f07ce27 (before the slot buffer) has neither check and gives 0, which
shows nothing.

**v1.** Not present: `v1-lock` has no slot buffer and no FALLTHROUGH.

**Fix.** Pending a ruling: refuse the nesting at load (`pe_isa`), or give a nested FT ARM
its own request and tags in the RTL.
