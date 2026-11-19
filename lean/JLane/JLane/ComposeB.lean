import JLane.RestartB
/-!
# Brick C3g — cutting a run at the lane's last flush (`slot_on_composition`, L1, Wilson 11-19)

A cycle `t` of `FlushKill.runBK` is, for lane `y`, in exactly one of three places:
* **before any flush of `y`** -- the first stretch (L2);
* **the restart window** `f + 1`, `f + 2` after `y`'s last flush `f` -- `y`'s head holds its edge
  word (`restart_head_runBK`);
* **a stretch from `f + 3`** -- `restart_runBK`'s start (one word held, in the head) followed by a
  `TrajY` trajectory up to `t`, well formed (`stretch_after_flush`), on which `GapRunT`'s certificate
  applies from `H0 = 1`.

`flush_cut` picks the last flush (`last_true`). Because the cut takes the LAST flush before `t`,
the restart's "no flush at `f + 1`, `f + 2`" is met by construction here; the flush-spacing
contract (K8, Wilson 11-19) enters through the edge-word premise `hedge` at every flush the
composition restarts from.
-/
namespace JLane

/-- **The last `true` before `t`**: either `p` is false on every `j < t`, or there is a last
`f < t` with `p f`, false on every `j` strictly between `f` and `t`. -/
theorem last_true (p : Nat → Bool) : ∀ t : Nat,
    (∀ j, j < t → p j = false) ∨ ∃ f, f < t ∧ p f = true ∧ ∀ j, f < j → j < t → p j = false
  | 0 => Or.inl (fun j hj => absurd hj (Nat.not_lt_zero j))
  | t + 1 => by
    cases hp : p t with
    | true => exact Or.inr ⟨t, by omega, hp, fun j h1 h2 => absurd h2 (by omega)⟩
    | false =>
      rcases last_true p t with h | ⟨f, hf, hpf, hr⟩
      · left
        intro j hj
        rcases Nat.lt_or_ge j t with hlt | hge
        · exact h j hlt
        · rw [show j = t by omega]; exact hp
      · right
        refine ⟨f, by omega, hpf, fun j h1 h2 => ?_⟩
        rcases Nat.lt_or_ge j t with hlt | hge
        · exact hr j h1 hlt
        · rw [show j = t by omega]; exact hp

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- **The cut**: before cycle `t` of `runBK`, `y` was never flushed, or `f` is its last flush. -/
theorem flush_cut (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (y : Lane)
    (t : Nat) :
    (∀ j, j < t → fl (runBK P win usb sreq fl k j X0).x.e.now y = false) ∨
    ∃ f, f < t ∧ fl (runBK P win usb sreq fl k f X0).x.e.now y = true ∧
      ∀ j, f < j → j < t → fl (runBK P win usb sreq fl k j X0).x.e.now y = false :=
  last_true (fun j => fl (runBK P win usb sreq fl k j X0).x.e.now y) t

/-- **The restart window, two cycles.** `y` flushed at `X` with its edge word present, not
flushed the cycle after: its head is valid at `f + 1` (the edge word, K1) and at `f + 2` (frozen:
no retirement, no load, any capture for `y` killed). -/
theorem restart_head_12 (hok : SReqB P sreq) (fl0 fl1 : Lane → Bool) (k0 k1 : Lane → Nat)
    (X X1 X2 : EngBK) (y : Lane)
    (hX1 : X1 = stepBKK P win usb sreq fl0 k0 X) (hX2 : X2 = stepBKK P win usb sreq fl1 k1 X1)
    (hI : WfBK X) (hF0 : FlushOk P win usb sreq fl0 X)
    (hf0 : fl0 y = true) (hk : X.base.hasEdge y (k0 y) = true) (hf1 : fl1 y = false) :
    X1.x.e.headValid y = true ∧ X2.x.e.headValid y = true := by
  have hI1 : WfBK X1 := hX1 ▸ wfBK_step P win usb sreq fl0 k0 hok X hI hF0
  obtain ⟨hv1, -, -⟩ := edge_survives_flushK P win usb sreq fl0 k0 X y hf0 hk
  rw [← hX1] at hv1
  have hb1 : X1.x.buf y = false := by
    rw [hX1]; exact flushK_buf_empty P win usb sreq fl0 k0 X y hf0
  have hnw1 : ¬(X1.x.e.st = .wb ∧ X1.x.e.cur = y) := by
    rw [hX1]; exact no_wb_after_flush P win usb sreq fl0 k0 X y hF0 hf0
  have hcap1 : X1.x.e.pst = .cap → X1.x.e.pl = y → X1.pkill = true := by
    intro hc hp
    rw [hX1, pstK, stepB_pst] at hc
    rw [hX1, plK, stepB_pl] at hp
    obtain ⟨hwt, hpl⟩ := portNextB_cap_from P usb sreq X.base hc
    rw [base_e] at hwt hpl
    rw [hpl] at hp
    rw [hX1, pkillK, if_neg (by rw [hwt]; decide)]
    simp [hwt, hp, hf0]
  obtain ⟨ha2, -, hs2, -, -⟩ :=
    frozen_stepBKK P win usb sreq fl1 k1 X1 y hI1.wf hf1 hnw1 hb1 hcap1
  rw [← hX2] at ha2 hs2
  refine ⟨hv1, ?_⟩
  unfold Engine.headValid at hv1 ⊢
  rw [hs2, ha2]
  exact hv1

/-- **The restart window on a run**: `y` flushed at cycle `f` with its edge word present, not
flushed at `f + 1`: its head is valid at `f + 1` and `f + 2`. -/
theorem restart_head_runBK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (f : Nat) (y : Lane)
    (hF : ∀ j, j < f + 1 → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hfl : fl (runBK P win usb sreq fl k f X0).x.e.now y = true)
    (hedge : (runBK P win usb sreq fl k f X0).base.hasEdge y
      (k (runBK P win usb sreq fl k f X0).x.e.now y) = true)
    (h1 : fl (runBK P win usb sreq fl k (f + 1) X0).x.e.now y = false) :
    (runBK P win usb sreq fl k (f + 1) X0).x.e.headValid y = true ∧
    (runBK P win usb sreq fl k (f + 2) X0).x.e.headValid y = true :=
  restart_head_12 P win usb sreq hok _ _ _ _ (runBK P win usb sreq fl k f X0)
    (runBK P win usb sreq fl k (f + 1) X0) (runBK P win usb sreq fl k (f + 2) X0) y
    (runBK_succ' P win usb sreq fl k f X0) (runBK_succ' P win usb sreq fl k (f + 1) X0)
    (wfBK_run P win usb sreq hok fl k f X0 hI (fun j hj => hF j (by omega)))
    (hF f (by omega)) hfl hedge h1

/-- **A stretch after the last flush.** `f` is `y`'s last flush before `t ≥ f + 3`, its edge word
present: the stretch `f + 3 .. t` of `runBK` is a `TrajY` trajectory for `y`, well formed, starting
with exactly one word held, in the head (`restart_runBK`) -- `GapRunT`'s `H0 = 1` start. -/
theorem stretch_after_flush (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (f t : Nat) (y : Lane) (hft : f + 3 ≤ t)
    (hF : ∀ j, j < t → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hfl : fl (runBK P win usb sreq fl k f X0).x.e.now y = true)
    (hedge : (runBK P win usb sreq fl k f X0).base.hasEdge y
      (k (runBK P win usb sreq fl k f X0).x.e.now y) = true)
    (hlast : ∀ j, f < j → j < t → fl (runBK P win usb sreq fl k j X0).x.e.now y = false) :
    TrajY P win usb sreq y (fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) (t - (f + 3)) ∧
    (∀ n, n ≤ t - (f + 3) → WfB ((fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) n)) ∧
    (runBK P win usb sreq fl k (f + 3) X0).base.held y = 1 ∧
    (runBK P win usb sreq fl k (f + 3) X0).base.e.headValid y = true := by
  obtain ⟨hh, hv, -, -, -⟩ := restart_runBK P win usb sreq hok fl k X0 hI f y
    (fun j hj => hF j (by omega)) hfl hedge
    (hlast (f + 1) (by omega) (by omega)) (hlast (f + 2) (by omega) (by omega))
  refine ⟨?_, ?_, hh, hv⟩
  · exact trajY_runBK_noflush P win usb sreq hok fl k X0 hI y (f + 3) (t - (f + 3)) (by omega)
      (fun j hj => hF j (by omega)) (fun j h1 h2 => hlast j (by omega) (by omega))
  · exact wfB_runBK P win usb sreq hok fl k X0 hI (f + 3) (t - (f + 3))
      (fun j hj => hF j (by omega))

end

#print axioms last_true
#print axioms flush_cut
#print axioms restart_head_12
#print axioms restart_head_runBK
#print axioms stretch_after_flush

end JLane
