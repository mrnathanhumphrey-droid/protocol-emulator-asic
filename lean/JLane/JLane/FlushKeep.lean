import JLane.BufEng
/-!
# Brick K1 — the edge word survives the flush (Wilson 11-17, `edge_survives_flush`)

With the depth-2 buffer (`BufEng`), a FALLTHROUGH ARM fetches its **edge word** (PC+2) first and
its timeout word (PC+1) second (`Buf.lean`). Today's flush (`FlushStep.stepF_flush_empty`, the RTL
as built 11-14) empties both of the lane's slots at the edge, so the edge path waits for a refill:
`FlushLate.flush_head_late`, `FLUSH_REFILL_LATE + B` past the release. The registry
(`branch_budget.READY_RULES`, rule `ft_edge`) owes the theorem that removes that wait.

**The contract (what the RTL must do; agent 1's flush is written to match this step).** At a
FALLTHROUGH edge on lane `l`, with `k l` the fetch index of the ARM's edge word:
* (K1) the word with fetch index `k l` -- in either slot, in the buffer, or being captured for
  `l` in the edge's own cycle -- is **kept**, and is the lane's head after the cycle;
* (K2) every other word of the lane (the timeout word, anything behind it) is cleared, and the
  buffer is emptied;
* (K3) a word already in a slot stays in that slot (only the head select moves); a word from the
  buffer or the port is filed into the lane's current head slot;
* (K4) the lane is released the cycle after the edge (`FlushStep.tsF`, unchanged);
* other lanes are untouched (`stepBK` is `BufEng.stepB` on them).

The case the shipped RTL gets wrong for this purpose: an edge in the CAP cycle of the edge
word's own fetch. `FlushStep` (11-14): "an edge in CAP's own cycle is written after the capture
in the same `always` block, so the slot ends empty". Under (K1) that capture is kept. It is not
a corner: through the scan the edge word is captured at `c + 4` and the earliest edge is at
`c + 4` (`edge_capture_by_edge`), so the tight case is exactly that cycle.

Proved:
* `edge_survives_flush` -- (K1, K4): the head is valid after the edge cycle, holds fetch index
  `k l`, and the lane is released that same cycle: the edge path's head is valid **at** its
  release (lateness 0 from the flush, against `FLUSH_REFILL_LATE + B` without the keep);
* `flush_keeps_only_edge`, `flush_buf_empty` -- (K2): the only word the lane holds after the
  edge is the edge word; the timeout word never survives (`flush_drops_timeout`);
* `flush_empty_of_absent` -- with no edge word held or arriving, the lane is empty: the refill
  path (`FlushLate`) applies unchanged;
* `flush_keep_slot` -- (K3);
* `stepBK_other` -- other lanes are `stepB`'s;
* `edge_capture_by_edge`, `edge_valid_by_release` -- the timing: the edge word is captured no
  later than the edge (scan `c + 4`, at capture `c + 3`; the edge is after the ARM's writeback,
  `ArmSplit.arm_release_T_bus`, which is at `c + 3` or later, `Slot.p1b_capture`), so it is valid
  by the release `E + 1`, margin `P1B_MARGIN_SCAN` = 0 at the earliest edge.

Owed (the carry-through, K2 brick): `WfB` preserved across `stepBK`, and the run-level link that
the edge word, once captured, is still held at the edge (the armed lane is not dispatched,
`Armed.ArmInv`; no retirement moves it). Until then `edge_survives_flush` takes "held or
arriving at the edge" as its premise (`hasEdge`).
-/
namespace JLane

/-- The lane holds the word with fetch index `k` in slot `s`. -/
def EngB.inSlot (x : EngB) (l : Lane) (k : Nat) (s : Slot) : Bool :=
  x.e.actv l s && decide (x.sq l s = k)

/-- The lane's buffer holds the word with fetch index `k`. -/
def EngB.inBuf (x : EngB) (l : Lane) (k : Nat) : Bool :=
  x.buf l && decide (x.bsq l = k)

/-- This cycle's capture is for `l` and carries fetch index `k`. -/
def EngB.inCap (x : EngB) (l : Lane) (k : Nat) : Bool :=
  decide (x.e.pst = .cap) && decide (l = x.e.pl) && decide (x.psq = k)

/-- The edge word (fetch index `k`) is held by lane `l` or arrives for it this cycle. -/
def EngB.hasEdge (x : EngB) (l : Lane) (k : Nat) : Bool :=
  x.inSlot l k true || x.inSlot l k false || x.inBuf l k || x.inCap l k

/-- (K3) Where the kept word is after the flush: the slot already holding it; from the buffer
or the port, the lane's current head slot. -/
def keepSlot (x : EngB) (l : Lane) (k : Nat) : Slot :=
  if x.inSlot l k true = true then true
  else if x.inSlot l k false = true then false
  else x.e.sel l

/-- One cycle of the buffered engine with FALLTHROUGH edges `fl` that **keep** each flushed
lane's edge word `k l` (K1–K4). -/
def stepBK (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) (fl : Lane → Bool) (k : Lane → Nat) (x : EngB) : EngB :=
  let y := stepB P win usb sreq x
  { y with
    e := { y.e with
      actv := fun l s => if fl l = true
        then x.hasEdge l (k l) && decide (s = keepSlot x l (k l)) else y.e.actv l s
      sel := fun l => if fl l = true then keepSlot x l (k l) else y.e.sel l
      ts := fun l => if fl l = true then x.e.now + 1 else y.e.ts l }
    buf := fun l => if fl l = true then false else y.buf l
    sq := fun l s => if fl l = true ∧ s = keepSlot x l (k l) then k l else y.sq l s }

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (fl : Lane → Bool) (k : Lane → Nat)

theorem stepBK_now (x : EngB) : (stepBK P win usb sreq fl k x).e.now = x.e.now + 1 :=
  stepB_e_now P win usb sreq x

/-- **`edge_survives_flush`** (K1, K4). At a FALLTHROUGH edge on `l` whose edge word is held or
arriving, after the cycle the head is valid, it is the edge word, and the lane is released that
same cycle: the edge path's head is valid at its release. -/
theorem edge_survives_flush (x : EngB) (l : Lane) (hf : fl l = true)
    (hk : x.hasEdge l (k l) = true) :
    (stepBK P win usb sreq fl k x).e.headValid l = true ∧
    (stepBK P win usb sreq fl k x).sq l ((stepBK P win usb sreq fl k x).e.sel l) = k l ∧
    (stepBK P win usb sreq fl k x).e.ts l = (stepBK P win usb sreq fl k x).e.now := by
  refine ⟨?_, ?_, ?_⟩
  · simp [stepBK, Engine.headValid, hf, hk]
  · simp [stepBK, hf]
  · rw [stepBK_now]
    simp [stepBK, hf]

/-- (K2) The only word a flushed lane holds after the cycle is its edge word, in its head. -/
theorem flush_keeps_only_edge (x : EngB) (l : Lane) (hf : fl l = true) (s : Slot)
    (h : (stepBK P win usb sreq fl k x).e.actv l s = true) :
    s = (stepBK P win usb sreq fl k x).e.sel l ∧ (stepBK P win usb sreq fl k x).sq l s = k l := by
  simp only [stepBK, hf, if_true, Bool.and_eq_true, decide_eq_true_eq] at h
  refine ⟨?_, ?_⟩
  · simp [stepBK, hf, h.2]
  · simp [stepBK, hf, h.2]

/-- (K2) The flushed lane's buffer is empty after the cycle. -/
theorem flush_buf_empty (x : EngB) (l : Lane) (hf : fl l = true) :
    (stepBK P win usb sreq fl k x).buf l = false := by
  simp [stepBK, hf]

/-- (K2) The timeout word (any fetch index other than the edge word's) is not held after the
edge, in either slot. -/
theorem flush_drops_timeout (x : EngB) (l : Lane) (hf : fl l = true) (j : Nat) (hj : j ≠ k l)
    (s : Slot) :
    ¬((stepBK P win usb sreq fl k x).e.actv l s = true ∧
      (stepBK P win usb sreq fl k x).sq l s = j) := by
  rintro ⟨ha, hs⟩
  have := (flush_keeps_only_edge P win usb sreq fl k x l hf s ha).2
  exact hj (hs.symm.trans this)

/-- With no edge word held or arriving, the flushed lane is empty: the refill path
(`FlushLate.flush_head_late`) applies unchanged. -/
theorem flush_empty_of_absent (x : EngB) (l : Lane) (hf : fl l = true)
    (hk : x.hasEdge l (k l) = false) (s : Slot) :
    (stepBK P win usb sreq fl k x).e.actv l s = false := by
  simp [stepBK, hf, hk]

/-- (K3) A word already in a slot stays in that slot. `huniq`: the two slots do not carry the
same fetch index (the order theorem `BufEng.order_kept` hands indices out once; its link to this
step is in the owed carry-through). -/
theorem flush_keep_slot (x : EngB) (l : Lane) (hf : fl l = true) (s : Slot)
    (hs : x.inSlot l (k l) s = true)
    (huniq : ¬(x.inSlot l (k l) true = true ∧ x.inSlot l (k l) false = true)) :
    (stepBK P win usb sreq fl k x).e.sel l = s := by
  show (if fl l = true then keepSlot x l (k l) else _) = s
  rw [if_pos hf]
  unfold keepSlot
  cases s
  · have ht : ¬x.inSlot l (k l) true = true := fun ht => huniq ⟨ht, hs⟩
    rw [if_neg ht, if_pos hs]
  · rw [if_pos hs]

/-- Other lanes: the buffered engine's step. -/
theorem stepBK_other (x : EngB) (l : Lane) (hf : fl l = false) :
    (∀ s, (stepBK P win usb sreq fl k x).e.actv l s = (stepB P win usb sreq x).e.actv l s) ∧
    (stepBK P win usb sreq fl k x).e.sel l = (stepB P win usb sreq x).e.sel l ∧
    (stepBK P win usb sreq fl k x).e.ts l = (stepB P win usb sreq x).e.ts l ∧
    (stepBK P win usb sreq fl k x).buf l = (stepB P win usb sreq x).buf l ∧
    (∀ s, (stepBK P win usb sreq fl k x).sq l s = (stepB P win usb sreq x).sq l s) := by
  refine ⟨fun s => ?_, ?_, ?_, ?_, fun s => ?_⟩ <;> simp [stepBK, hf]

end

/-! ### The timing: the edge word is captured no later than the edge -/

/-- Through the scan the edge word (fetched first) is captured at `c + 4` (`two_fetch_scan`); the
ARM writes back at `c + 3` or later (`p1b_capture`) and its edge comes after its writeback
(`arm_release_T_bus`). So the edge word's capture is at or before the edge: held at the edge, or
captured in the edge's own cycle (the case (K1) keeps). -/
theorem edge_capture_by_edge (c wb E : Nat) (hwb : c + 3 ≤ wb) (hE : wb < E) :
    c + (P1B_FILL_SCAN - 1) ≤ E := by
  simp only [P1B_FILL_SCAN, L_REFILL]
  omega

/-- Issued at capture the edge word is captured at `c + 3`: also by the edge. -/
theorem edge_capture_by_edge_direct (c wb E : Nat) (hwb : c + 3 ≤ wb) (hE : wb < E) :
    c + (P1B_FILL_DIRECT - 1) ≤ E := by
  simp only [P1B_FILL_DIRECT, L_REFILL]
  omega

/-- The edge word is valid by the edge path's release `E + 1`, with `P1B_MARGIN_SCAN` (0) to
spare at the earliest edge. -/
theorem edge_valid_by_release (c wb E : Nat) (hwb : c + 3 ≤ wb) (hE : wb < E) :
    c + P1B_FILL_SCAN + P1B_MARGIN_SCAN ≤ E + 1 := by
  simp only [P1B_FILL_SCAN, P1B_MARGIN_SCAN, DISPATCH_CYCLES, ARM_RETIRE_GAP, L_REFILL]
  omega

#print axioms edge_survives_flush
#print axioms flush_keeps_only_edge
#print axioms flush_drops_timeout
#print axioms flush_empty_of_absent
#print axioms flush_keep_slot
#print axioms edge_capture_by_edge
#print axioms edge_valid_by_release

end JLane
