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
