import JLane.ArmSplit
/-!
# Brick X — a no-pin word's lateness does not move its successor (Wilson 11-15, the plain-lane split)

A lane's dispatch jitter J is quoted per lane: `1 +` its largest certified lateness
(`GapRun.head_late_gap`). On nousb and the uart_rx images (uart_rx_board is the F2 board image
of record) that maximum sits on ONE word: the `OP_LEVEL` on `PIN_NONE` straight after the lane's
ARM -- a timed no-op, released at the edge + 1 before it can be fetched. Every word that samples
or drives certifies at lateness 0. Wilson's condition for dropping that lateness from J: a
theorem that it cannot reach a sample, as `ArmSplit` proved for ARM words.

Two facts, one proved here and one read from the RTL:

* `ord_release` / `ord_late_free` (proved) — an ordinary word's writeback advances its lane's
  release by exactly its own delay (`wb_dly = a_dly`: no clock phase, no HALF), so the next
  word's release is the SAME whatever cycle the writeback happened in — i.e. whatever the word's
  lateness. The successor's own lateness is then the certificate's, computed from that release.
* the word's dispatch touches no pin (read) — every data write is guarded by `pin_real`,
  anchor `wire pin_real = (a_pin < N_PINS[PINW-1:0]);`, and `PIN_NONE` (15) is outside it; the
  RTL's must-fire `M_NOOP_DRIVES` (the guard removed) is what makes the reading checked. The
  checker counts a word as no-pin only when it is a LEVEL on a pin outside `N_PINS` with `mod = 0`
  (no complementary `pinb` drive, no SE0).

So a no-pin word's lateness is invisible on the wire and does not feed any later word's timing:
the lane's observable J is `1 +` the largest certified lateness over the words that touch a pin
(`model/branch_budget.lane_j_pin`).
-/
namespace JLane

/-- An ordinary word's writeback delay is its delay (no clock phase, no HALF halving). -/
theorem ord_wbDly (P : Program2) (x : Engine2) (h : (x.head x.e.cur).op = .ord) :
    x.wbDly P = (x.head x.e.cur).dly := by
  have hc : x.isClk = false := by
    unfold Engine2.isClk
    rw [h]
  unfold Engine2.wbDly
  rw [if_neg (by rw [hc]; intro hh; exact Bool.noConfusion hh.1)]

/-- **The successor's release after an ordinary word.** -/
theorem ord_release (P : Program2) (fw : Engine2 → Word) (w : Option Lane) (x : Engine2)
    (hwb : x.e.st = .wb) (h : (x.head x.e.cur).op = .ord) :
    (step2 P fw w x).e.ts x.e.cur = x.e.ts x.e.cur + (x.head x.e.cur).dly := by
  show x.tsNext P x.e.cur = _
  unfold Engine2.tsNext
  rw [if_pos ⟨hwb, rfl⟩, ord_wbDly P x h]

/-- **Whatever the lateness.** Two writebacks of the same ordinary word on the same lane, from
the same release, at ANY two cycles (any `now`, any other state), give the successor the same
release. -/
theorem ord_late_free (P : Program2) (fw fw' : Engine2 → Word) (w w' : Option Lane)
    (x x' : Engine2) (hwb : x.e.st = .wb) (hwb' : x'.e.st = .wb) (hc : x'.e.cur = x.e.cur)
    (hts : x'.e.ts x.e.cur = x.e.ts x.e.cur) (hh : x'.head x.e.cur = x.head x.e.cur)
    (h : (x.head x.e.cur).op = .ord) :
    (step2 P fw' w' x').e.ts x.e.cur = (step2 P fw w x).e.ts x.e.cur := by
  have h' : (x'.head x'.e.cur).op = .ord := by rw [hc, hh]; exact h
  have e1 := ord_release P fw' w' x' hwb' h'
  rw [hc] at e1
  rw [e1, ord_release P fw w x hwb h, hts, hh]

#print axioms ord_wbDly
#print axioms ord_release
#print axioms ord_late_free

end JLane
