import JLane.ArmP
/-!
# Brick R7 — the half-range bound, ahead side (agent 1's time-wrap question, 11-23)

The RTL keeps `now` and `ts` in 16 bits and compares them by the signed difference
(`tf_diff = ts - now`), so the model's unbounded `ts` maps onto the RTL's only while every
lane's `ts` stays within half the range of `now`. This file proves the side **ahead** of `now`
on the RTL-side armed run (`ArmP.stepBPR`), for **every** lane (armed, parked and halted ones
included):

* `stepBPR_ts` -- the four writes of `ts` in one cycle: a plain edge's rebase (`now + off`), a
  timeout's keep, a flush (`now`), else the writeback's advance (`tsNext`, `+ dly + ext`);
* `HalfAhead D` -- the invariant: every `ts` at most `D` ahead of `now`, every latched offset at
  most `D`, and the lane in DRIVE / WB unarmed with `ts ≤ now` (it was dispatched released);
* `stepBPR_halfAhead`, `runBPR_halfAhead` -- it holds every cycle, given the winner's contract
  (`hwin`, as `ArmT` / `Close`: it names only released lanes), every writeback's
  `dly + ext ≤ D` (`hD`) and every ARM's and park's offset `≤ D` (`hoW`, `hhW`);
* `runBPR_ts_ahead` -- **`ts ≤ now + D`**, so `ts - now ≤ 32767` whenever `D ≤ 32767`.

The side behind `now` needs the response bound (a released lane is served within the window
`K`), so it excludes the lanes nothing serves: armed no-timeout, parked and halted lanes. Item 1
of it is here:
* `stepBPR_ts_quiet`, `stepBPR_reb_quiet`, `runBPR_rel_flat` -- a quiet lane (`EngBP.quiet`: not
  written back, no plain edge, no timeout, no flush; every unarmed lane off its writeback,
  `quiet_of_unarmed`) keeps its `ts`, its rebase bit and so its release;
* `runBPR_behind_back`, `runBPR_behind_back_ts` -- **a gap bound at a writeback holds all
  through the quiet stretch before it**: `now ≤ rel + W` at the end gives `now + n ≤ rel + W`
  `n` cycles earlier (and `now ≤ ts + W + 1`). With `W = K + 1` from the response bound
  (`RespWinB.wb_bound_winBK_fl`, on `runBK`; its transfer to `runBPR` is item 2) every cycle up
  to a lane's next writeback is inside the window.

Item 2, the response bound on this run (re-proved, not transferred):
* `wb_bound_winBPR` -- `RespWinB.wb_bound_winBK`'s window argument on any run `R` of `stepBPR`
  (`IsRunBPR`; `isRun_runBPR`), each cycle with its own masked winner `winA win (R n).mask`
  (Lemma A per cycle: `runR_lemA`). A lane unarmed since the start writes back within `K + 1`
  of its `ts`, under the window budget counted along `R` (`cntW`: `M` other-lane decisions, `S`
  undecided idle cycles, `K ≥ 3M + S + 3`). No `Ready` / `NotMid` premise: Lemma A's per-cycle
  identity needs only "not decided";
* `behind_winBPR` (with `runR_ts_flat`) -- so at every cycle of the quiet stretch before that
  writeback, `now + (t - c) ≤ ts + K + 1`.
Open: a live, unarmed lane with **no** later writeback (the bound is conditional on one).
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)
  (isFT : EngB → Bool) (offW : EngB → Nat) (ntW : EngB → Bool)
  (isPark : EngB → Bool) (hdW : EngB → Nat)

/-- **The four writes of `ts`.** -/
theorem stepBPR_ts (wd nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) (l : Lane) :
    (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.x.e.ts l =
      if B.pe l = true then B.A.X.x.e.now + B.off l
      else if B.tmo win l = true then B.A.X.x.e.ts l
      else if B.fl win l = true then B.A.X.x.e.now
      else tsNext (P.haltP B.halt) B.A.X.x.e l := by
  have h1 : (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.x.e.ts l =
      if B.pe l = true then B.A.X.x.e.now + B.off l
      else if B.tmo win l = true then B.A.X.x.e.ts l
      else if B.fl win l = true then B.A.X.base.e.now
      else tsNext (P.haltP B.halt) B.A.X.base.e l := rfl
  rw [h1, base_e]

/-- The dispatch registers after the cycle: the base step's (`dispNext`, the winner masked). -/
theorem stepBPR_disp (wd nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) :
    (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.x.e.st
        = (dispNext (winA win B.mask) B.A.X.x.e).st ∧
      (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.x.e.cur
        = (dispNext (winA win B.mask) B.A.X.x.e).cur := by
  have h1 : (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.x.e.st
      = (dispNext (winA win B.mask) B.A.X.base.e).st := rfl
  have h2 : (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.x.e.cur
      = (dispNext (winA win B.mask) B.A.X.base.e).cur := rfl
  rw [h1, h2, base_e]
  exact ⟨rfl, rfl⟩

/-- An unarmed lane has no edge, no timeout, no flush and no plain edge. -/
theorem unarmed_quiet (B : EngBP) (l : Lane) (h : B.A.armed l = false) :
    B.pe l = false ∧ B.tmo win l = false ∧ B.fl win l = false := by
  have hh : B.A.hit l = false := by unfold EngBA.hit; rw [h]; simp
  have ht : B.tmo win l = false := by unfold EngBP.tmo EngBA.tmo; rw [h]; simp
  refine ⟨?_, ht, ?_⟩
  · unfold EngBP.pe; rw [hh]; simp
  · unfold EngBP.fl EngBP.ends; rw [hh, ht]; simp

/-- Arming and parking happen only at a writeback. -/
theorem arms_parks_wb (B : EngBP) (l : Lane) (h : B.A.X.x.e.st ≠ .wb) :
    B.A.arms P isArm l = false ∧ B.parks isPark l = false := by
  constructor
  · unfold EngBA.arms; simp [h]
  · unfold EngBP.parks; simp [h]

/-- **The ahead invariant.** -/
structure HalfAhead (D : Nat) (B : EngBP) : Prop where
  ts  : ∀ l, B.A.X.x.e.ts l ≤ B.A.X.x.e.now + D
  off : ∀ l, B.off l ≤ D
  cur : B.A.X.x.e.st ≠ .idle →
    B.A.X.x.e.ts B.A.X.x.e.cur ≤ B.A.X.x.e.now ∧ B.A.armed B.A.X.x.e.cur = false

theorem stepBPR_halfAhead (D : Nat)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hD : ∀ n l, P.dly l + P.ext n l ≤ D) (hoW : ∀ b, offW b ≤ D) (hhW : ∀ b, hdW b ≤ D)
    (wd nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) (hI : HalfAhead D B) :
    HalfAhead D (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B) := by
  have hnow := stepBPR_now P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B
  obtain ⟨hst, hcur⟩ := stepBPR_disp P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B
  constructor
  · -- every ts at most D ahead
    intro l
    rw [stepBPR_ts, hnow]
    split
    · have := hI.off l; omega
    · split
      · have := hI.ts l; omega
      · split
        · omega
        · unfold tsNext
          split
          · rename_i hwb
            obtain ⟨h1, h2⟩ := hwb
            have hc := (hI.cur (by rw [h1]; decide)).1
            rw [← h2] at hc
            have := hD B.A.X.x.e.now l
            show B.A.X.x.e.ts l + P.dly l + P.ext B.A.X.x.e.now l ≤ _
            omega
          · have := hI.ts l; omega
  · -- every latched offset at most D
    intro l
    show (if B.parks isPark l = true then hdW B.A.X.base
      else if B.A.arms P isArm l = true then offW B.A.X.base else B.off l) ≤ D
    split
    · exact hhW _
    · split
      · exact hoW _
      · exact hI.off l
  · -- the lane in DRIVE / WB was dispatched released and unarmed
    intro hne
    rw [hst] at hne
    rw [hcur]
    cases hs : B.A.X.x.e.st with
    | wb =>
      exfalso; apply hne; unfold dispNext; rw [hs]
    | drive =>
      have hd : (dispNext (winA win B.mask) B.A.X.x.e).cur = B.A.X.x.e.cur := by
        unfold dispNext; rw [hs]
      rw [hd]
      have hc := hI.cur (by rw [hs]; decide)
      obtain ⟨hpe, htm, hfl⟩ := unarmed_quiet win B _ hc.2
      obtain ⟨har, hpk⟩ := arms_parks_wb P isArm isPark B B.A.X.x.e.cur (by rw [hs]; decide)
      constructor
      · rw [stepBPR_ts, hnow, hpe, htm, hfl]
        simp only [Bool.false_eq_true, if_false]
        unfold tsNext
        rw [if_neg (by rw [hs]; simp)]
        omega
      · show (if (B.ends win _ || wd _) = true then false
          else if (B.A.arms P isArm _ || B.parks isPark _) = true then true else B.A.armed _) = false
        rw [har, hpk, hc.2]
        simp
    | idle =>
      unfold dispNext at hne ⊢
      rw [hs] at hne ⊢
      cases hw : winA win B.mask B.A.X.x.e with
      | none => rw [hw] at hne; dsimp only at hne; exact absurd rfl hne
      | some w =>
        rw [hw] at hne; dsimp only at hne ⊢
        by_cases hv : B.A.X.x.e.headValid w = true
        · rw [if_pos hv]
          -- the winner: unmasked, so unarmed; released by the contract
          have hwa : win B.A.X.x.e = some w ∧ B.mask w = false := by
            unfold winA at hw
            cases hw0 : win B.A.X.x.e with
            | none => rw [hw0] at hw; simp at hw
            | some v =>
              rw [hw0] at hw; dsimp only at hw
              by_cases hm : B.mask v = true
              · rw [if_pos hm] at hw; simp at hw
              · rw [if_neg hm] at hw
                have := Option.some.inj hw
                subst this
                exact ⟨rfl, by simpa using hm⟩
          have harm : B.A.armed w = false := by
            have := hwa.2; unfold EngBP.mask at this; simp at this; exact this.1
          have hrel := (hwin _ _ hwa.1).2
          obtain ⟨hpe, htm, hfl⟩ := unarmed_quiet win B w harm
          obtain ⟨har, hpk⟩ := arms_parks_wb P isArm isPark B w (by rw [hs]; decide)
          constructor
          · show (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.x.e.ts w
              ≤ (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.x.e.now
            rw [stepBPR_ts, hnow, hpe, htm, hfl]
            simp only [Bool.false_eq_true, if_false]
            unfold tsNext
            rw [if_neg (by rw [hs]; simp)]
            omega
          · show (if (B.ends win w || wd w) = true then false
              else if (B.A.arms P isArm w || B.parks isPark w) = true then true
              else B.A.armed w) = false
            rw [har, hpk, harm]
            simp
        · rw [if_neg hv] at hne; exact absurd rfl hne

/-- **The ahead invariant holds every cycle.** -/
theorem runBPR_halfAhead (D : Nat)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hD : ∀ n l, P.dly l + P.ext n l ≤ D) (hoW : ∀ b, offW b ≤ D) (hhW : ∀ b, hdW b ≤ D)
    (wdt nwt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) (B0 : EngBP) (h0 : HalfAhead D B0) :
    ∀ n, HalfAhead D (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0)
  | 0 => h0
  | n + 1 => stepBPR_halfAhead P win usb sreq isArm edge isFT offW ntW isPark hdW D hwin hD hoW hhW
      _ _ _ _ (runBPR_halfAhead D hwin hD hoW hhW wdt nwt kt B0 h0 n)

/-- **Every lane's `ts` is at most `D` ahead of `now`, every cycle** -- with `D ≤ 32767`, inside
the RTL's signed half range on the ahead side. -/
theorem runBPR_ts_ahead (D : Nat)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hD : ∀ n l, P.dly l + P.ext n l ≤ D) (hoW : ∀ b, offW b ≤ D) (hhW : ∀ b, hdW b ≤ D)
    (wdt nwt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) (B0 : EngBP) (h0 : HalfAhead D B0)
    (n : Nat) (l : Lane) :
    (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0).A.X.x.e.ts l
      ≤ (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0).A.X.x.e.now + D :=
  (runBPR_halfAhead P win usb sreq isArm edge isFT offW ntW isPark hdW D hwin hD hoW hhW
    wdt nwt kt B0 h0 n).ts l

/-- An idle start with every `ts` at most `D` ahead and every offset at most `D` satisfies the
invariant (no lane in DRIVE / WB). -/
theorem halfAhead_idle (D : Nat) (B : EngBP) (hs : B.A.X.x.e.st = .idle)
    (hts : ∀ l, B.A.X.x.e.ts l ≤ B.A.X.x.e.now + D) (hoff : ∀ l, B.off l ≤ D) :
    HalfAhead D B :=
  ⟨hts, hoff, fun h => absurd hs h⟩

/-! ### The side behind `now`, item 1: `ts` and the rebase bit are flat between writebacks -/

/-- Lane `l` is quiet this cycle: not written back, no plain edge, no timeout, no flush. -/
def EngBP.quiet (B : EngBP) (win : Engine → Option Lane) (l : Lane) : Prop :=
  ¬(B.A.X.x.e.st = .wb ∧ l = B.A.X.x.e.cur) ∧ B.pe l = false ∧ B.tmo win l = false ∧
    B.fl win l = false

/-- An unarmed lane not at its writeback is quiet. -/
theorem quiet_of_unarmed (B : EngBP) (l : Lane) (ha : B.A.armed l = false)
    (hw : ¬(B.A.X.x.e.st = .wb ∧ l = B.A.X.x.e.cur)) : B.quiet win l :=
  let h := unarmed_quiet win B l ha
  ⟨hw, h.1, h.2.1, h.2.2⟩

/-- **A quiet cycle leaves `ts` as it was.** -/
theorem stepBPR_ts_quiet (wd nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) (l : Lane)
    (hq : B.quiet win l) :
    (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.x.e.ts l
      = B.A.X.x.e.ts l := by
  obtain ⟨hw, hpe, htm, hfl⟩ := hq
  rw [stepBPR_ts, hpe, htm, hfl]
  simp only [Bool.false_eq_true, if_false]
  unfold tsNext
  rw [if_neg hw]

/-- **... and the rebase bit.** -/
theorem stepBPR_reb_quiet (wd nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) (l : Lane)
    (hq : B.quiet win l) :
    (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.reb l
      = B.A.X.reb l := by
  obtain ⟨hw, hpe, htm, hfl⟩ := hq
  have h1 : (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.reb l =
      if B.pe l = true then decide (B.off l = 0)
      else if B.tmo win l = true then B.A.X.reb l
      else if B.fl win l = true then true
      else if B.A.X.x.e.st = .wb ∧ l = B.A.X.x.e.cur ∧
          0 < (P.haltP B.halt).dly l + (P.haltP B.halt).ext B.A.X.x.e.now l then false
      else B.A.X.reb l := rfl
  rw [h1, hpe, htm, hfl]
  simp only [Bool.false_eq_true, if_false]
  rw [if_neg (fun h => hw ⟨h.1, h.2.1⟩)]

theorem stepBPR_rel_quiet (wd nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) (l : Lane)
    (hq : B.quiet win l) :
    (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.rel l
      = B.A.X.rel l := by
  unfold EngBK.rel
  rw [stepBPR_ts_quiet P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B l hq,
    stepBPR_reb_quiet P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B l hq]

theorem runBPR_now (wdt nwt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) (B0 : EngBP) :
    ∀ n, (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0).A.X.x.e.now
      = B0.A.X.x.e.now + n
  | 0 => rfl
  | n + 1 => by
    show (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW _ _ _
      (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0)).A.X.x.e.now = _
    rw [stepBPR_now, runBPR_now wdt nwt kt B0 n]
    omega

/-- **The release is flat across a quiet stretch.** -/
theorem runBPR_rel_flat (wdt nwt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) (B0 : EngBP)
    (l : Lane) (c : Nat) :
    ∀ n, (∀ i, i < n →
        (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (c + i) B0).quiet win l) →
      (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (c + n) B0).A.X.rel l
        = (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt c B0).A.X.rel l
  | 0, _ => rfl
  | n + 1, hq => by
    show (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW _ _ _
      (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (c + n) B0)).A.X.rel l = _
    rw [stepBPR_rel_quiet P win usb sreq isArm edge isFT offW ntW isPark hdW _ _ _ _ l (hq n (by omega))]
    exact runBPR_rel_flat wdt nwt kt B0 l c n (fun i hi => hq i (by omega))

/-- **A gap bound at the end of a quiet stretch holds all through it**: if `now ≤ rel + W` at
cycle `c + n` (the response bound at `l`'s writeback) and `l` is quiet on `[c, c + n)`, then
`now ≤ rel + W` at every cycle `c` before it -- the release does not move and `now` only
grows. -/
theorem runBPR_behind_back (wdt nwt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) (B0 : EngBP)
    (l : Lane) (c n W : Nat)
    (hq : ∀ i, i < n →
      (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (c + i) B0).quiet win l)
    (hW : (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (c + n) B0).A.X.x.e.now
      ≤ (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (c + n) B0).A.X.rel l + W) :
    (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt c B0).A.X.x.e.now + n
      ≤ (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt c B0).A.X.rel l + W := by
  rw [runBPR_rel_flat P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt B0 l c n hq,
    runBPR_now P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt B0 (c + n)] at hW
  rw [runBPR_now P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt B0 c]
  omega

/-- In `ts` terms (`ts ≤ rel`): `now ≤ ts + W + 1` all through the stretch. -/
theorem runBPR_behind_back_ts (wdt nwt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) (B0 : EngBP)
    (l : Lane) (c n W : Nat)
    (hq : ∀ i, i < n →
      (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (c + i) B0).quiet win l)
    (hW : (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (c + n) B0).A.X.x.e.now
      ≤ (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (c + n) B0).A.X.rel l + W) :
    (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt c B0).A.X.x.e.now
      ≤ (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt c B0).A.X.x.e.ts l + W + 1 := by
  have h := runBPR_behind_back P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt B0 l c n W hq hW
  have hr : (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt c B0).A.X.rel l
      ≤ (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt c B0).A.X.x.e.ts l + 1 := by
    unfold EngBK.rel; have := rbit_le ((runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt c B0).A.X.reb l); omega
  omega

/-! ### The side behind `now`, item 2: the response bound on the RTL-side run

`RespWinB.wb_bound_winBK`'s window argument, re-proved on any trajectory `R` of `stepBPR` (every
`R (n + 1)` one `stepBPR` of `R n`, whatever its watchdog, no-swap and kept-index inputs). Each
cycle dispatches with **that cycle's** masked winner `winA win (R n).mask` (armed and halted
lanes out), so Lemma A's per-cycle identity (`LemmaAN.lemA_step_n`) is applied with it, cycle by
cycle; the window counts are taken along `R` with the same per-cycle winner. The lane `y` is
unarmed through the stretch (its `ts` moves only at its own writebacks); nothing else is asked
of it -- a lane that is never served has no writeback and the bound says nothing about it. -/

/-- `R` is a run of `stepBPR`. -/
def IsRunBPR (R : Nat → EngBP) : Prop :=
  ∀ n, ∃ wd nw k, R (n + 1) = stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k (R n)

/-- `y` is decided this cycle, by the cycle's masked winner. -/
def DecP (y : Lane) (B : EngBP) : Prop := Dec (winA win B.mask) y B.A.X.x.e

/-- The count of cycles `c, …, c + n - 1` of `R` satisfying `Q`. -/
def cntW (Q : EngBP → Bool) (R : Nat → EngBP) (c : Nat) : Nat → Nat
  | 0 => 0
  | n + 1 => cntW Q R c n + (if Q (R (c + n)) = true then 1 else 0)

/-- The dispatch FSM after a `stepBPR` is `step`'s, with the masked winner. -/
theorem stepBPR_st_step (wd nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) :
    (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.x.e.st
        = (step P (winA win B.mask) B.A.X.x.e).st ∧
      (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.x.e.cur
        = (step P (winA win B.mask) B.A.X.x.e).cur :=
  stepBPR_disp P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B

section run
variable (R : Nat → EngBP) (hR : IsRunBPR P win usb sreq isArm edge isFT offW ntW isPark hdW R)
include hR

theorem runR_st (n : Nat) :
    (R (n + 1)).A.X.x.e.st = (step P (winA win (R n).mask) (R n).A.X.x.e).st ∧
      (R (n + 1)).A.X.x.e.cur = (step P (winA win (R n).mask) (R n).A.X.x.e).cur := by
  obtain ⟨wd, nw, k, h⟩ := hR n
  rw [h]
  exact stepBPR_st_step P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k (R n)

theorem runR_now : ∀ n, (R n).A.X.x.e.now = (R 0).A.X.x.e.now + n
  | 0 => rfl
  | n + 1 => by
    obtain ⟨wd, nw, k, h⟩ := hR n
    rw [h, stepBPR_now, runR_now n]
    omega

/-- An unarmed lane's `ts` never decreases, and is flat off its writeback. -/
theorem runR_ts_step (y : Lane) (n : Nat) (ha : (R n).A.armed y = false) :
    (R n).A.X.x.e.ts y ≤ (R (n + 1)).A.X.x.e.ts y ∧
      (¬IsWB y (R n).A.X.x.e → (R (n + 1)).A.X.x.e.ts y = (R n).A.X.x.e.ts y) := by
  obtain ⟨wd, nw, k, h⟩ := hR n
  rw [h]
  obtain ⟨hpe, htm, hfl⟩ := unarmed_quiet win (R n) y ha
  constructor
  · rw [stepBPR_ts, hpe, htm, hfl]
    simp only [Bool.false_eq_true, if_false]
    exact tsNext_ge _ _ _
  · intro hw
    exact stepBPR_ts_quiet P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k (R n) y
      (quiet_of_unarmed win (R n) y ha (fun h' => hw ⟨h'.1, h'.2.symm⟩))

theorem runR_ts_mono (y : Lane) :
    ∀ j, (∀ n, n < j → (R n).A.armed y = false) → (R 0).A.X.x.e.ts y ≤ (R j).A.X.x.e.ts y
  | 0, _ => Nat.le_refl _
  | j + 1, ha => Nat.le_trans (runR_ts_mono y j (fun n hn => ha n (by omega)))
      (runR_ts_step P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y j (ha j (by omega))).1

theorem runR_dec_wb (y : Lane) (a : Nat) (h : DecP win y (R a)) :
    (R (a + 1)).A.X.x.e.st = .drive ∧ IsWB y (R (a + 2)).A.X.x.e := by
  obtain ⟨h1, h2⟩ := step_of_dec P (winA win (R a).mask) (R a).A.X.x.e y h
  obtain ⟨s1, c1⟩ := runR_st P win usb sreq isArm edge isFT offW ntW isPark hdW R hR a
  have hd : (R (a + 1)).A.X.x.e.st = .drive := s1.trans h1
  obtain ⟨h3, h4⟩ := step_drive P (winA win (R (a + 1)).mask) (R (a + 1)).A.X.x.e hd
  obtain ⟨s2, c2⟩ := runR_st P win usb sreq isArm edge isFT offW ntW isPark hdW R hR (a + 1)
  exact ⟨hd, s2.trans h3, (c2.trans h4).trans (c1.trans h2)⟩

theorem runR_wb_back (h0 : (R 0).A.X.x.e.st = .idle) (t : Nat) (y : Lane)
    (hwb : IsWB y (R t).A.X.x.e) : ∃ s, t = s + 2 ∧ DecP win y (R s) := by
  obtain ⟨hst, hcur⟩ := hwb
  cases t with
  | zero => rw [h0] at hst; cases hst
  | succ t =>
    obtain ⟨s1, c1⟩ := runR_st P win usb sreq isArm edge isFT offW ntW isPark hdW R hR t
    rw [s1] at hst
    obtain ⟨hd, hc⟩ := back_wb P _ _ hst
    cases t with
    | zero => rw [h0] at hd; cases hd
    | succ s =>
      obtain ⟨s2, c2⟩ := runR_st P win usb sreq isArm edge isFT offW ntW isPark hdW R hR s
      rw [s2] at hd
      have hdec := back_drive P _ _ hd
      refine ⟨s, rfl, ?_⟩
      have : (step P (winA win (R s).mask) (R s).A.X.x.e).cur = y := by
        rw [← c2, ← hc, ← c1]; exact hcur
      unfold DecP
      rw [← this]
      exact hdec

/-- **Lemma A along `R`**, each cycle with its own masked winner. -/
theorem runR_lemA (y : Lane) (c : Nat) :
    ∀ n, (∀ s, s < n → ¬DecP win y (R (c + s))) →
      3 * cntW (fun B => decOther (winA win B.mask) y B.A.X.x.e) R c n
        + cntW (fun B => noDecB (winA win B.mask) B.A.X.x.e) R c n + ph (R c).A.X.x.e.st
        = n + ph (R (c + n)).A.X.x.e.st
  | 0, _ => by simp [cntW]
  | n + 1, hnd => by
    have ih := runR_lemA y c n (fun s hs => hnd s (by omega))
    have h1 := lemA_step_n P (winA win (R (c + n)).mask) y (R (c + n)).A.X.x.e (hnd n (by omega))
    rw [← (runR_st P win usb sreq isArm edge isFT offW ntW isPark hdW R hR (c + n)).1] at h1
    show 3 * (cntW _ R c n + (if decOther (winA win (R (c + n)).mask) y (R (c + n)).A.X.x.e = true
        then 1 else 0))
      + (cntW _ R c n + (if noDecB (winA win (R (c + n)).mask) (R (c + n)).A.X.x.e = true
        then 1 else 0)) + ph (R c).A.X.x.e.st = n + 1 + ph (R (c + n + 1)).A.X.x.e.st
    omega

/-- **The response bound on the RTL-side run**: every writeback of a lane unarmed since the
start lands within `K + 1` of its timestamp, given the window budget counted along the run (`M`
other-lane decisions, `S` idle cycles with no decision, in every `K ≥ 3M + S + 3` window), with
each cycle's masked winner. -/
theorem wb_bound_winBPR (h0 : (R 0).A.X.x.e.st = .idle) (y : Lane)
    (h0ts : (R 0).A.X.x.e.now ≤ (R 0).A.X.x.e.ts y)
    (M S K : Nat) (hK : 3 * M + S + 3 ≤ K)
    (t : Nat) (hwb : IsWB y (R t).A.X.x.e)
    (hun : ∀ n, n < t → (R n).A.armed y = false)
    (hfree : ∀ w, w + 2 < t → IsWB y (R w).A.X.x.e → (R w).A.X.x.e.now < (R t).A.X.x.e.ts y)
    (hM : ∀ c, c + K + 2 ≤ t →
      cntW (fun B => decOther (winA win B.mask) y B.A.X.x.e) R c K ≤ M)
    (hS : ∀ c, c + K + 2 ≤ t →
      cntW (fun B => noDecB (winA win B.mask) B.A.X.x.e) R c K ≤ S) :
    (R t).A.X.x.e.now ≤ (R t).A.X.x.e.ts y + K + 1 := by
  obtain ⟨D, rfl, hdec⟩ := runR_wb_back P win usb sreq isArm edge isFT offW ntW isPark hdW R hR h0 t y hwb
  have hidle : (R D).A.X.x.e.st = .idle := hdec.1
  have hdrive := (runR_dec_wb P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y D hdec).1
  have t1 := (runR_ts_step P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y D
    (hun D (by omega))).2 (not_wb_of_st y _ (by rw [hidle]; decide))
  have t2 := (runR_ts_step P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y (D + 1)
    (hun (D + 1) (by omega))).2 (not_wb_of_st y _ (by rw [hdrive]; decide))
  have hts2 : (R (D + 2)).A.X.x.e.ts y = (R D).A.X.x.e.ts y := t2.trans t1
  have hnow := runR_now P win usb sreq isArm edge isFT offW ntW isPark hdW R hR
  rw [hts2, hnow (D + 2)]
  rw [hts2] at hfree
  by_cases hfit : (R 0).A.X.x.e.now + D + 1 ≤ (R D).A.X.x.e.ts y + K
  · omega
  · exfalso
    have hts0 := runR_ts_mono P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y D
      (fun n hn => hun n (by omega))
    obtain ⟨c, rfl⟩ : ∃ c, D = c + K := ⟨D - K, by omega⟩
    have noWB : ∀ w, c ≤ w → w < c + K → ¬IsWB y (R w).A.X.x.e := by
      intro w hcw hwD hw
      have h1 := hfree w (by omega) hw
      have h2 := hnow w
      omega
    have hnd : ∀ s, s < K → ¬DecP win y (R (c + s)) := by
      intro s hs hds
      obtain ⟨hd1, hw2⟩ := runR_dec_wb P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y
        (c + s) hds
      rcases Nat.lt_or_ge (c + s + 2) (c + K) with hlt | hge
      · exact noWB (c + s + 2) (by omega) hlt hw2
      · have : c + K = c + s + 1 ∨ c + K = c + s + 2 := by omega
        rcases this with h | h
        · rw [h, hd1] at hidle; cases hidle
        · rw [h, hw2.1] at hidle; cases hidle
    have hA := runR_lemA P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y c K hnd
    have hm := hM c (by omega)
    have hs := hS c (by omega)
    have h2 := ph_le (R c).A.X.x.e.st
    omega

end run

/-- `runBPR` is a run of `stepBPR`. -/
theorem isRun_runBPR (wdt nwt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) (B0 : EngBP) :
    IsRunBPR P win usb sreq isArm edge isFT offW ntW isPark hdW
      (fun n => runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0) :=
  fun n => ⟨_, _, _, rfl⟩

/-- An unarmed lane off its writebacks keeps its `ts` along `R`. -/
theorem runR_ts_flat (R : Nat → EngBP)
    (hR : IsRunBPR P win usb sreq isArm edge isFT offW ntW isPark hdW R) (y : Lane) (c : Nat) :
    ∀ n, (∀ i, i < n → (R (c + i)).A.armed y = false ∧ ¬IsWB y (R (c + i)).A.X.x.e) →
      (R (c + n)).A.X.x.e.ts y = (R c).A.X.x.e.ts y
  | 0, _ => rfl
  | n + 1, h => by
    have ih := runR_ts_flat R hR y c n (fun i hi => h i (by omega))
    have hs := (runR_ts_step P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y (c + n)
      (h n (by omega)).1).2 (h n (by omega)).2
    show (R (c + n + 1)).A.X.x.e.ts y = _
    rw [hs, ih]

/-- **The side behind `now`, every cycle up to a writeback**: if `y`'s writeback at `t` is
within `K + 1` of its timestamp (`wb_bound_winBPR`) and `y` is unarmed and not written back on
`[c, t)`, then at every such cycle `now + (t - c) ≤ ts + K + 1`. -/
theorem behind_winBPR (R : Nat → EngBP)
    (hR : IsRunBPR P win usb sreq isArm edge isFT offW ntW isPark hdW R) (y : Lane) (c n K : Nat)
    (hq : ∀ i, i < n → (R (c + i)).A.armed y = false ∧ ¬IsWB y (R (c + i)).A.X.x.e)
    (hW : (R (c + n)).A.X.x.e.now ≤ (R (c + n)).A.X.x.e.ts y + K + 1) :
    (R c).A.X.x.e.now + n ≤ (R c).A.X.x.e.ts y + K + 1 := by
  rw [runR_ts_flat P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y c n hq,
    runR_now P win usb sreq isArm edge isFT offW ntW isPark hdW R hR (c + n)] at hW
  rw [runR_now P win usb sreq isArm edge isFT offW ntW isPark hdW R hR c]
  omega

end

end JLane
