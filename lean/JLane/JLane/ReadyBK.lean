import JLane.ComposeB
import JLane.SpareB
/-!
# Brick C3h — the ready theorems on the flush run (`slot_on_composition`, hRdy, 11-22)

The six `ready_*_T` theorems (SlotReadyB, SpareB) are proved along one `TrajY` trajectory `τ`,
well formed. `runBK` is such a trajectory on each of `y`'s stretches (ComposeB): from the start
while `y` is never flushed (`stretch_first`), and from `f + 3` after `y`'s last flush `f` with its
edge word present (`stretch_after_flush`); in the restart window `f + 1`, `f + 2` the head is the
kept edge word (K1, `restart_head_12`), no ready theorem asked.

* `StretchAt s t` -- `t` lies in the stretch starting at `s`: `s = 0` with no flush of `y` before
  `t` (the start with no kill pending), or `s = f + 3 ≤ t` with `f` `y`'s last flush before `t`,
  its edge word present;
* `stretch_lift` -- any property `R τ T` that holds for every well-formed `TrajY` trajectory holds
  for `runBK` shifted to the stretch's start, up to `t - s`;
* `ready_*_BK` -- the six ready theorems so lifted: each statement is the `_T` theorem's own
  premises and conclusion (`Rdy*`, generated from its signature) at `τ := runBK` from `s`.

The per-image premises (the capture, the retirements, the gaps, the requester's waits) stay in
the stretch's coordinates (cycle `s + n` of the run is `τ n`): a capture before the stretch's
start is not covered -- a flush clears the lane's slots except the kept edge word.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (y : Lane)

/-- `t` lies in `y`'s stretch starting at `s`. -/
def StretchAt (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (s t : Nat) : Prop :=
  (s = 0 ∧ X0.pkill = false ∧ ∀ j, j < t → fl (runBK P win usb sreq fl k j X0).x.e.now y = false) ∨
  ∃ f, s = f + 3 ∧ f + 3 ≤ t ∧ fl (runBK P win usb sreq fl k f X0).x.e.now y = true ∧
    (runBK P win usb sreq fl k f X0).base.hasEdge y (k (runBK P win usb sreq fl k f X0).x.e.now y)
      = true ∧
    ∀ j, f < j → j < t → fl (runBK P win usb sreq fl k j X0).x.e.now y = false

/-- **The lift**: a property of every well-formed `TrajY` trajectory holds on `y`'s stretch of the
flush run. -/
theorem stretch_lift (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (s t : Nat)
    (hF : ∀ j, j < t → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hstr : StretchAt P win usb sreq y fl k X0 s t)
    (R : (Nat → EngB) → Nat → Prop)
    (hR : ∀ τ T, TrajY P win usb sreq y τ T → (∀ n, n ≤ T → WfB (τ n)) → R τ T) :
    R (fun n => (runBK P win usb sreq fl k (s + n) X0).base) (t - s) := by
  rcases hstr with ⟨rfl, hpk, hnf⟩ | ⟨f, rfl, hft, hfl, hedge, hlast⟩
  · obtain ⟨h1, h2⟩ := stretch_first P win usb sreq hok fl k X0 hI hpk y t hF hnf
    rw [Nat.sub_zero]
    exact hR _ _ h1 h2
  · obtain ⟨h1, h2, -, -⟩ := stretch_after_flush P win usb sreq hok fl k X0 hI f t y hft hF hfl
      hedge hlast
    exact hR _ _ h1 h2

set_option linter.unusedVariables false

/-- `ready_pc1_plain_T`'s statement past its trajectory premises (`hT`, `hWf`), for any `τ` / `T`. -/
def RdyPc1Plain (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) (y : Lane) (τ : Nat → EngB) (T : Nat) : Prop :=
  ∀ (old : Lane → Bool) (c w2 t C : Nat) (ht : t ≤ T)
    (hcap : Hit y (τ c).e) (hempty : (τ c).e.headValid y = false) (hcw : c < w2) (hw2t : w2 < t)
    (hw2 : IsRet P y (τ w2).e)
    (hfirst : cntT τ (fun z => IsRet P y z.e) c = cntT τ (fun z => IsRet P y z.e) w2)
    (hnr : cntT τ (fun z => IsRet P y z.e) (w2 + 1) = cntT τ (fun z => IsRet P y z.e) t)
    (hrel : (τ t).e.ts y ≤ (τ t).e.now)
    (hgap : (τ w2).e.now + ARM_RETIRE_GAP ≤ (τ (w2 + 1)).e.ts y)
    (hq : ∀ j, c + 1 ≤ j → j ≤ c + 1 + L_REFILL * C →
    (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold : ∀ j, c + 1 ≤ j → j ≤ c + 1 + L_REFILL * C →
    (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
    ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC : cntFromT τ (OldIssB P usb sreq old) (c + 1) (L_REFILL * C + 1) ≤ C)
    (hcm : L_REFILL * C ≤ P1B_MARGIN_SCAN),
    (τ t).e.headValid y = true

/-- `ready_pc2_plain_T`'s statement past its trajectory premises (`hT`, `hWf`), for any `τ` / `T`. -/
def RdyPc2Plain (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) (y : Lane) (τ : Nat → EngB) (T : Nat) : Prop :=
  ∀ (old : Lane → Bool) (c w1 w2 t d W1 W2 C1 C2 : Nat)
    (ht : t ≤ T) (hcap : Hit y (τ c).e) (hempty : (τ c).e.headValid y = false)
    (hcw : c < w1) (hw12 : w1 < w2) (hw2t : w2 < t)
    (hw1 : IsRet P y (τ w1).e) (hw2 : IsRet P y (τ w2).e)
    (hfirst : cntT τ (fun z => IsRet P y z.e) c = cntT τ (fun z => IsRet P y z.e) w1)
    (hmid : cntT τ (fun z => IsRet P y z.e) (w1 + 1) = cntT τ (fun z => IsRet P y z.e) w2)
    (hnr : cntT τ (fun z => IsRet P y z.e) (w2 + 1) = cntT τ (fun z => IsRet P y z.e) t)
    (hrel : (τ t).e.ts y ≤ (τ t).e.now)
    (hgap : (τ w1).e.now + ARM_RETIRE_GAP ≤ (τ (w1 + 1)).e.ts y)
    (hd : (τ (w1 + 1)).e.ts y + d ≤ (τ (w2 + 1)).e.ts y) (hd4 : 4 ≤ d)
    (hq1 : ∀ j, c + 1 ≤ j → j ≤ c + 1 + W1 →
    (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold1 : ∀ j, c + 1 ≤ j → j ≤ c + 1 + W1 →
    (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
    ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC1 : cntFromT τ (OldIssB P usb sreq old) (c + 1) (W1 + 1) ≤ C1)
    (hW1 : L_REFILL * C1 ≤ W1)
    (hq2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
    (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
    (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
    ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 →
    cntFromT τ (OldIssB P usb sreq old) a2 (W2 + 1) ≤ C2)
    (hW2 : L_REFILL * C2 ≤ W2) (hcm : W1 + W2 ≤ d - 4),
    (τ t).e.headValid y = true

/-- `ready_pc2_arm_T`'s statement past its trajectory premises (`hT`, `hWf`), for any `τ` / `T`. -/
def RdyPc2Arm (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) (y : Lane) (τ : Nat → EngB) (T : Nat) : Prop :=
  ∀ (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (old : Lane → Bool) (c w1 w2 t W1 W2 C1 C2 : Nat)
    (ht : t ≤ T) (hcap : Hit y (τ c).e) (hempty : (τ c).e.headValid y = false)
    (hcw : c < w1) (hw12 : w1 < w2) (hw2t : w2 < t)
    (hw1 : IsRet P y (τ w1).e) (hw2 : IsRet P y (τ w2).e)
    (hfirst : cntT τ (fun z => IsRet P y z.e) c = cntT τ (fun z => IsRet P y z.e) w1)
    (hmid : cntT τ (fun z => IsRet P y z.e) (w1 + 1) = cntT τ (fun z => IsRet P y z.e) w2)
    (hnr : cntT τ (fun z => IsRet P y z.e) (w2 + 1) = cntT τ (fun z => IsRet P y z.e) t)
    (hrel : (τ t).e.ts y ≤ (τ t).e.now)
    (hgap1 : (τ w1).e.now + ARM_RETIRE_GAP ≤ (τ (w1 + 1)).e.ts y)
    (hgap2 : (τ w2).e.now + ARM_RETIRE_GAP ≤ (τ (w2 + 1)).e.ts y)
    (hq1 : ∀ j, c + 1 ≤ j → j ≤ c + 1 + W1 →
    (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold1 : ∀ j, c + 1 ≤ j → j ≤ c + 1 + W1 →
    (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
    ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC1 : cntFromT τ (OldIssB P usb sreq old) (c + 1) (W1 + 1) ≤ C1)
    (hW1 : L_REFILL * C1 ≤ W1)
    (hq2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
    (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
    (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
    ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 →
    cntFromT τ (OldIssB P usb sreq old) a2 (W2 + 1) ≤ C2)
    (hW2 : L_REFILL * C2 ≤ W2) (hcm : W1 + W2 ≤ P1B2_MARGIN_ARM_SCAN),
    (τ t).e.headValid y = true

/-- `ready_pc1_spare_T`'s statement past its trajectory premises (`hT`, `hWf`), for any `τ` / `T`. -/
def RdyPc1Spare (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) (y : Lane) (τ : Nat → EngB) (T : Nat) : Prop :=
  ∀ (old : Lane → Bool) (c w0 w2 t C k : Nat) (ht : t ≤ T)
    (hcap : Hit y (τ c).e) (hk : k ≤ (τ c).held y)
    (hcw0 : c ≤ w0) (hw02 : w0 < w2) (hw2t : w2 < t)
    (hw0 : IsRet P y (τ w0).e) (hw2 : IsRet P y (τ w2).e)
    (hfirst : cntT τ (fun z => IsRet P y z.e) c + k = cntT τ (fun z => IsRet P y z.e) w2)
    (hnr : cntT τ (fun z => IsRet P y z.e) (w2 + 1) = cntT τ (fun z => IsRet P y z.e) t)
    (hrel : (τ t).e.ts y ≤ (τ t).e.now)
    (hgap : (τ w2).e.now + ARM_RETIRE_GAP ≤ (τ (w2 + 1)).e.ts y)
    (hq : ∀ j, c + 1 ≤ j → j ≤ c + 1 + L_REFILL * C →
    (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold : ∀ j, c + 1 ≤ j → j ≤ c + 1 + L_REFILL * C →
    (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
    ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC : cntFromT τ (OldIssB P usb sreq old) (c + 1) (L_REFILL * C + 1) ≤ C)
    (hcm : L_REFILL * C ≤ P1B_MARGIN_SCAN),
    (τ t).e.headValid y = true

/-- `ready_pc2_plain_spare_T`'s statement past its trajectory premises (`hT`, `hWf`), for any `τ` / `T`. -/
def RdyPc2PlainSpare (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) (y : Lane) (τ : Nat → EngB) (T : Nat) : Prop :=
  ∀ (old : Lane → Bool) (c w0 w1 w2 t d W1 W2 C1 C2 k : Nat)
    (ht : t ≤ T) (hcap : Hit y (τ c).e) (hk : k ≤ (τ c).held y)
    (hcw0 : c ≤ w0) (hw01 : w0 < w1) (hw12 : w1 < w2) (hw2t : w2 < t)
    (hw0 : IsRet P y (τ w0).e) (hw1 : IsRet P y (τ w1).e) (hw2 : IsRet P y (τ w2).e)
    (hfirst : cntT τ (fun z => IsRet P y z.e) c + k = cntT τ (fun z => IsRet P y z.e) w1)
    (hmid : cntT τ (fun z => IsRet P y z.e) (w1 + 1) = cntT τ (fun z => IsRet P y z.e) w2)
    (hnr : cntT τ (fun z => IsRet P y z.e) (w2 + 1) = cntT τ (fun z => IsRet P y z.e) t)
    (hrel : (τ t).e.ts y ≤ (τ t).e.now)
    (hgap : (τ w1).e.now + ARM_RETIRE_GAP ≤ (τ (w1 + 1)).e.ts y)
    (hd : (τ (w1 + 1)).e.ts y + d ≤ (τ (w2 + 1)).e.ts y) (hd4 : 4 ≤ d)
    (hq1 : ∀ j, c + 1 ≤ j → j ≤ c + 1 + W1 →
    (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold1 : ∀ j, c + 1 ≤ j → j ≤ c + 1 + W1 →
    (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
    ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC1 : cntFromT τ (OldIssB P usb sreq old) (c + 1) (W1 + 1) ≤ C1)
    (hW1 : L_REFILL * C1 ≤ W1)
    (hq2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
    (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
    (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
    ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 →
    cntFromT τ (OldIssB P usb sreq old) a2 (W2 + 1) ≤ C2)
    (hW2 : L_REFILL * C2 ≤ W2) (hcm : W1 + W2 ≤ d - 4),
    (τ t).e.headValid y = true

/-- `ready_pc2_arm_spare_T`'s statement past its trajectory premises (`hT`, `hWf`), for any `τ` / `T`. -/
def RdyPc2ArmSpare (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) (y : Lane) (τ : Nat → EngB) (T : Nat) : Prop :=
  ∀ (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (old : Lane → Bool) (c w0 w1 w2 t W1 W2 C1 C2 k : Nat)
    (ht : t ≤ T) (hcap : Hit y (τ c).e) (hk : k ≤ (τ c).held y)
    (hcw0 : c ≤ w0) (hw01 : w0 < w1) (hw12 : w1 < w2) (hw2t : w2 < t)
    (hw0 : IsRet P y (τ w0).e) (hw1 : IsRet P y (τ w1).e) (hw2 : IsRet P y (τ w2).e)
    (hfirst : cntT τ (fun z => IsRet P y z.e) c + k = cntT τ (fun z => IsRet P y z.e) w1)
    (hmid : cntT τ (fun z => IsRet P y z.e) (w1 + 1) = cntT τ (fun z => IsRet P y z.e) w2)
    (hnr : cntT τ (fun z => IsRet P y z.e) (w2 + 1) = cntT τ (fun z => IsRet P y z.e) t)
    (hrel : (τ t).e.ts y ≤ (τ t).e.now)
    (hgap1 : (τ w1).e.now + ARM_RETIRE_GAP ≤ (τ (w1 + 1)).e.ts y)
    (hgap2 : (τ w2).e.now + ARM_RETIRE_GAP ≤ (τ (w2 + 1)).e.ts y)
    (hq1 : ∀ j, c + 1 ≤ j → j ≤ c + 1 + W1 →
    (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold1 : ∀ j, c + 1 ≤ j → j ≤ c + 1 + W1 →
    (∀ i, c + 1 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
    ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC1 : cntFromT τ (OldIssB P usb sreq old) (c + 1) (W1 + 1) ≤ C1)
    (hW1 : L_REFILL * C1 ≤ W1)
    (hq2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
    (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) → (sreq (τ j)).isSome = true)
    (hold2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 → ∀ j, a2 ≤ j → j ≤ a2 + W2 →
    (∀ i, a2 ≤ i → i < j → ¬SlotForB P usb sreq y (τ i)) →
    ∀ w, sreq (τ j) = some w → w = y ∨ old w = true)
    (hC2 : ∀ a2, c + 5 ≤ a2 → a2 ≤ c + 5 + W1 →
    cntFromT τ (OldIssB P usb sreq old) a2 (W2 + 1) ≤ C2)
    (hW2 : L_REFILL * C2 ≤ W2) (hcm : W1 + W2 ≤ P1B2_MARGIN_ARM_SCAN),
    (τ t).e.headValid y = true

/-- **`ready_pc1_plain_T` on the flush run**: on `y`'s stretch from `s` (from the start, no flush of `y`
before `t`; or from `f + 3` after its last flush `f`, the edge word present). -/
theorem ready_pc1_plain_BK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK)
    (hI : WfBK X0) (s t : Nat)
    (hF : ∀ j, j < t → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hstr : StretchAt P win usb sreq y fl k X0 s t) :
    RdyPc1Plain P win usb sreq y (fun n => (runBK P win usb sreq fl k (s + n) X0).base) (t - s) :=
  stretch_lift P win usb sreq y hok fl k X0 hI s t hF hstr _
    (fun τ T hT hWf => ready_pc1_plain_T P win usb sreq y τ T hT hWf)

/-- **`ready_pc2_plain_T` on the flush run**: on `y`'s stretch from `s` (from the start, no flush of `y`
before `t`; or from `f + 3` after its last flush `f`, the edge word present). -/
theorem ready_pc2_plain_BK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK)
    (hI : WfBK X0) (s t : Nat)
    (hF : ∀ j, j < t → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hstr : StretchAt P win usb sreq y fl k X0 s t) :
    RdyPc2Plain P win usb sreq y (fun n => (runBK P win usb sreq fl k (s + n) X0).base) (t - s) :=
  stretch_lift P win usb sreq y hok fl k X0 hI s t hF hstr _
    (fun τ T hT hWf => ready_pc2_plain_T P win usb sreq y τ T hT hWf)

/-- **`ready_pc2_arm_T` on the flush run**: on `y`'s stretch from `s` (from the start, no flush of `y`
before `t`; or from `f + 3` after its last flush `f`, the edge word present). -/
theorem ready_pc2_arm_BK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK)
    (hI : WfBK X0) (s t : Nat)
    (hF : ∀ j, j < t → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hstr : StretchAt P win usb sreq y fl k X0 s t) :
    RdyPc2Arm P win usb sreq y (fun n => (runBK P win usb sreq fl k (s + n) X0).base) (t - s) :=
  stretch_lift P win usb sreq y hok fl k X0 hI s t hF hstr _
    (fun τ T hT hWf => ready_pc2_arm_T P win usb sreq y τ T hT hWf)

/-- **`ready_pc1_spare_T` on the flush run**: on `y`'s stretch from `s` (from the start, no flush of `y`
before `t`; or from `f + 3` after its last flush `f`, the edge word present). -/
theorem ready_pc1_spare_BK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK)
    (hI : WfBK X0) (s t : Nat)
    (hF : ∀ j, j < t → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hstr : StretchAt P win usb sreq y fl k X0 s t) :
    RdyPc1Spare P win usb sreq y (fun n => (runBK P win usb sreq fl k (s + n) X0).base) (t - s) :=
  stretch_lift P win usb sreq y hok fl k X0 hI s t hF hstr _
    (fun τ T hT hWf => ready_pc1_spare_T P win usb sreq y τ T hT hWf)

/-- **`ready_pc2_plain_spare_T` on the flush run**: on `y`'s stretch from `s` (from the start, no flush of `y`
before `t`; or from `f + 3` after its last flush `f`, the edge word present). -/
theorem ready_pc2_plain_spare_BK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK)
    (hI : WfBK X0) (s t : Nat)
    (hF : ∀ j, j < t → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hstr : StretchAt P win usb sreq y fl k X0 s t) :
    RdyPc2PlainSpare P win usb sreq y (fun n => (runBK P win usb sreq fl k (s + n) X0).base) (t - s) :=
  stretch_lift P win usb sreq y hok fl k X0 hI s t hF hstr _
    (fun τ T hT hWf => ready_pc2_plain_spare_T P win usb sreq y τ T hT hWf)

/-- **`ready_pc2_arm_spare_T` on the flush run**: on `y`'s stretch from `s` (from the start, no flush of `y`
before `t`; or from `f + 3` after its last flush `f`, the edge word present). -/
theorem ready_pc2_arm_spare_BK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK)
    (hI : WfBK X0) (s t : Nat)
    (hF : ∀ j, j < t → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hstr : StretchAt P win usb sreq y fl k X0 s t) :
    RdyPc2ArmSpare P win usb sreq y (fun n => (runBK P win usb sreq fl k (s + n) X0).base) (t - s) :=
  stretch_lift P win usb sreq y hok fl k X0 hI s t hF hstr _
    (fun τ T hT hWf => ready_pc2_arm_spare_T P win usb sreq y τ T hT hWf)

end

end JLane
