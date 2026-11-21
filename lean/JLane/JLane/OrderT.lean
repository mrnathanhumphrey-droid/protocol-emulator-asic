import JLane.ComposeB
/-!
# Brick K6t — the timeout word on the timeout path (Wilson 11-20, rulings 1a / 1b)

K6 (Wilson 11-20 ruling 1a): **at a FALLTHROUGH timeout the head select moves to the timeout word
PC+1 and the edge word PC+2 is dropped** -- K2 mirrored; PC+2 is refetched if the path reaches
it. On the buffered engine this is the keep-flush the edge already is (`FlushKill.stepBKK`,
`fl l = true`, kept index `k l`), with the kept index the timeout word's: the lane keeps exactly
that word, in its head, and clears every other (the edge word included). So no new engine
transition is needed: the K6 swap is `stepBKK` at the deadline with `k` = PC+1's index.

Proved:
* `ft_timeout_captured_T` -- **ruling 1b, as a lemma**: with the two slot waits inside the
  timeout's room (`a + W1 + W2 + 8 ≤ T`: the free-port fill `P1B2_FILL_SCAN` = 9 from the ARM's
  capture `a - 1`, plus the waits -- `Buf.p1b2_margin_timeout_scan`'s `FILL + L ≤ T`), the slot's
  second fetch for `y` (PC+1, fetched second behind the edge word) is captured unkilled strictly
  before the deadline, with the index `nr + held` of its issue cycle. No late PC+1 exists, so K5
  needs no extension to this path;
* `ready_ft_timeout_T` -- **`ft_timeout`'s run theorem**: a stretch ending at the timeout's
  keep-flush of `y`; if the second fetch's index is the kept index (`hidx2`: the swap keeps the
  word fetched second after the ARM -- K6 + K7) and no retirement consumes it first (`hord`, as
  `ready_ft_edge_T`), then the timeout word is held at the deadline, and the cycle after it is
  `y`'s valid head with the kept index, released that cycle.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- **Ruling 1b: the timeout word is captured by the deadline.** Window 1 from the raise `a`
(the slot's first fetch, the edge word); window 2 from the scan after its capture (`a2 =
j1 + 4`, the second fetch, the timeout word). With `a + W1 + W2 + 8 ≤ T`, the second fetch is
issued at `j2`, captured unkilled at `j2 + 3 < T` with index `nr + held` of cycle `j2`. -/
theorem ft_timeout_captured_T (hok : SReqB P sreq) (fl : Nat → Lane → Bool)
    (k : Nat → Lane → Nat) (X0 : EngBK) (hI : WfBK X0) (y : Lane) (s T : Nat) (τ : Nat → EngB)
    (hτ : ∀ n, τ n = (runBK P win usb sreq fl k (s + n) X0).base)
    (hT : TrajY P win usb sreq y τ T)
    (hF : ∀ j, j < s + T → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hnf : ∀ j, s ≤ j + 2 → j < s + T → fl (runBK P win usb sreq fl k j X0).x.e.now y = false)
    (old : Lane → Bool) (a W1 W2 C1 C2 : Nat) (hn : a + W1 + W2 + 8 ≤ T)
    (hq1 : ∀ j, a ≤ j → j ≤ a + W1 → (∀ i, a ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      (sreq (τ j)).isSome = true)
    (hold1 : ∀ j, a ≤ j → j ≤ a + W1 → (∀ i, a ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC1 : cntFromT τ (OldIssB P usb sreq old) a (W1 + 1) ≤ C1)
    (hW1 : rem (τ a).e.pst + L_REFILL * C1 ≤ W1)
    (hq2 : ∀ a2, a + 4 ≤ a2 → a2 ≤ a + W1 + 4 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
      (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold2 : ∀ a2, a + 4 ≤ a2 → a2 ≤ a + W1 + 4 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
      (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC2 : ∀ a2, a + 4 ≤ a2 → a2 ≤ a + W1 + 4 →
      cntFromT τ (OldIssB P usb sreq old) a2 (W2 + 1) ≤ C2)
    (hW2 : L_REFILL * C2 ≤ W2) :
    ∃ j1 j2, a ≤ j1 ∧ j1 ≤ a + W1 ∧ SlotForB P usb sreq y (τ j1) ∧
      (∀ i, a ≤ i → i < j1 → ¬SlotForB P usb sreq y (τ i)) ∧
      j1 + 4 ≤ j2 ∧ j2 ≤ j1 + 4 + W2 ∧ j2 + 3 < T ∧ SlotForB P usb sreq y (τ j2) ∧
      (∀ i, j1 + 4 ≤ i → i < j2 → ¬SlotForB P usb sreq y (τ i)) ∧
      (runBK P win usb sreq fl k (s + (j2 + 3)) X0).base.inCap y
        ((τ j2).nr y + (τ j2).held y) = true ∧
      (runBK P win usb sreq fl k (s + (j2 + 3)) X0).pkill = false := by
  obtain ⟨j1, h11, h12, hs1, hmin1, -, -⟩ := slot_cap_index P win usb sreq hok fl k X0 hI y s T
    τ hτ hT hF hnf old a W1 C1 (by omega) hq1 hold1 hC1 hW1
  have hh1 := slot_issue_cap_T P win usb sreq y τ T hT j1 (by omega) hs1.1 hs1.2.1 hs1.2.2
  have hsc : (τ (j1 + 4)).e.pst = .scan :=
    hit_then_scanT P win usb sreq y τ T hT (j1 + 3) (by omega) hh1
  obtain ⟨j2, h21, h22, hs2, hmin2, hcap, hpk⟩ := slot_cap_index P win usb sreq hok fl k X0 hI
    y s T τ hτ hT hF hnf old (j1 + 4) W2 C2 (by omega)
    (hq2 (j1 + 4) (by omega) (by omega)) (hold2 (j1 + 4) (by omega) (by omega))
    (hC2 (j1 + 4) (by omega) (by omega)) (by rw [hsc]; simp only [rem]; omega)
  exact ⟨j1, j2, h11, h12, hs1, hmin1, h21, h22, by omega, hs2, hmin2, hcap, hpk⟩

/-- **`ready_ft_timeout_T`** (`READY_RULES` ft_timeout's run theorem; K6 as ruled 11-20). A
stretch `s … s + T` of `runBK` ends at the timeout's keep-flush of `y` at `s + T` (the swap:
the lane keeps the timeout word, the edge word is dropped). With the two slot waits inside the
timeout's room, the second fetch's index the kept index (`hidx2`: the swap keeps the word
fetched second after the ARM, K6 + K7) and that word never the head a retirement consumes
before the deadline (`hord`), the timeout word is held at the deadline, and the cycle after it
is `y`'s valid head with the kept index, released that cycle. -/
theorem ready_ft_timeout_T (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (y : Lane) (s T : Nat) (τ : Nat → EngB)
    (hτ : ∀ n, τ n = (runBK P win usb sreq fl k (s + n) X0).base)
    (hT : TrajY P win usb sreq y τ T)
    (hF : ∀ j, j ≤ s + T → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hnf : ∀ j, s ≤ j + 2 → j < s + T → fl (runBK P win usb sreq fl k j X0).x.e.now y = false)
    (hfl : fl (runBK P win usb sreq fl k (s + T) X0).x.e.now y = true)
    (old : Lane → Bool) (a W1 W2 C1 C2 : Nat) (hn : a + W1 + W2 + 8 ≤ T)
    (hq1 : ∀ j, a ≤ j → j ≤ a + W1 → (∀ i, a ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      (sreq (τ j)).isSome = true)
    (hold1 : ∀ j, a ≤ j → j ≤ a + W1 → (∀ i, a ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC1 : cntFromT τ (OldIssB P usb sreq old) a (W1 + 1) ≤ C1)
    (hW1 : rem (τ a).e.pst + L_REFILL * C1 ≤ W1)
    (hq2 : ∀ a2, a + 4 ≤ a2 → a2 ≤ a + W1 + 4 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
      (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold2 : ∀ a2, a + 4 ≤ a2 → a2 ≤ a + W1 + 4 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
      (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
      ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC2 : ∀ a2, a + 4 ≤ a2 → a2 ≤ a + W1 + 4 →
      cntFromT τ (OldIssB P usb sreq old) a2 (W2 + 1) ≤ C2)
    (hW2 : L_REFILL * C2 ≤ W2)
    (hidx2 : ∀ j1 j2, a ≤ j1 → j1 ≤ a + W1 → SlotForB P usb sreq y (τ j1) →
      (∀ i, a ≤ i → i < j1 → ¬SlotForB P usb sreq y (τ i)) →
      j1 + 4 ≤ j2 → j2 ≤ j1 + 4 + W2 → SlotForB P usb sreq y (τ j2) →
      (∀ i, j1 + 4 ≤ i → i < j2 → ¬SlotForB P usb sreq y (τ i)) →
      (τ j2).nr y + (τ j2).held y = k (runBK P win usb sreq fl k (s + T) X0).x.e.now y)
    (hord : ∀ i, s ≤ i → i < s + T → (runBK P win usb sreq fl k i X0).base.e.st = .wb →
      y = (runBK P win usb sreq fl k i X0).base.e.cur →
      P.ret (runBK P win usb sreq fl k i X0).base.e.now
        (runBK P win usb sreq fl k i X0).base.e.cur = true →
      (runBK P win usb sreq fl k i X0).base.inSlot y
        (k (runBK P win usb sreq fl k (s + T) X0).x.e.now y)
        ((runBK P win usb sreq fl k i X0).base.e.sel y) = false) :
    (runBK P win usb sreq fl k (s + T) X0).base.hasEdge y
      (k (runBK P win usb sreq fl k (s + T) X0).x.e.now y) = true ∧
    (runBK P win usb sreq fl k (s + T + 1) X0).x.e.headValid y = true ∧
    (runBK P win usb sreq fl k (s + T + 1) X0).x.sq y
      ((runBK P win usb sreq fl k (s + T + 1) X0).x.e.sel y)
      = (runBK P win usb sreq fl k (s + T + 1) X0).x.nr y ∧
    (runBK P win usb sreq fl k (s + T + 1) X0).x.e.ts y
      = (runBK P win usb sreq fl k (s + T + 1) X0).x.e.now := by
  obtain ⟨j1, j2, h11, h12, hs1, hmin1, h21, h22, hlt, hs2, hmin2, hcap, hpk⟩ :=
    ft_timeout_captured_T P win usb sreq hok fl k X0 hI y s T τ hτ hT
      (fun j hj => hF j (by omega)) hnf old a W1 W2 C1 C2 hn hq1 hold1 hC1 hW1 hq2 hold2 hC2 hW2
  rw [hidx2 j1 j2 h11 h12 hs1 hmin1 h21 h22 hs2 hmin2] at hcap
  -- the timeout word, captured before the deadline, is held at it
  have hE : (runBK P win usb sreq fl k (s + T) X0).base.hasEdge y
      (k (runBK P win usb sreq fl k (s + T) X0).x.e.now y) = true := by
    have hp := held_persist_runBK P win usb sreq hok fl k X0 hI y _ (s + (j2 + 3))
      (Or.inr ⟨hcap, hpk⟩) (s + T - (s + (j2 + 3)) - 1)
      (fun i hi1 hi2 => ⟨hnf i (by omega) (by omega), hord i (by omega) (by omega)⟩)
      (fun j' hj' => hF j' (by omega))
    rw [show s + (j2 + 3) + (s + T - (s + (j2 + 3)) - 1 + 1) = s + T by omega] at hp
    rw [← holds_base] at hp
    exact holds_hasEdge _ y _ hp
  refine ⟨hE, ?_⟩
  -- the swap: the keep-flush keeps it in the head (the edge word dropped, K2 mirrored)
  have := edge_survives_flushK P win usb sreq _ _ (runBK P win usb sreq fl k (s + T) X0) y hfl hE
  rw [← runBK_succ'] at this
  exact this

end

#print axioms ft_timeout_captured_T
#print axioms ready_ft_timeout_T

end JLane
