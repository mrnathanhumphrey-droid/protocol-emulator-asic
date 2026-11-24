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
  undecided idle cycles in a window where `y` waits -- `WaitP`: unarmed, unhalted, released,
  undecided -- `K ≥ 3M + S + 3`). No `Ready` / `NotMid` premise: Lemma A's per-cycle identity
  needs only "not decided";
* `behind_winBPR` (with `runR_ts_flat`) -- so at every cycle of the quiet stretch before that
  writeback, `now + (t - c) ≤ ts + K + 1`.

Item 3, the closure and progress:
* `wb_close_BPR` -- every writeback before `T` within `K + 1`, by induction over time; `hfree`
  from the induction and the gap premise `dly + ext ≥ K + 2` (`hgap`; gate_lane_cert check 22
  certifies `gap ≥ Rr + 3`);
* `behind_all_BPR` -- **at every cycle `n` with `n + K + 2 ≤ T`, `now ≤ ts + K + 1`**: a released
  lane not in its own dispatch is decided within `K` (else Lemma A breaks the budget), so writes
  back within `K + 2`, `ts` flat in between (`runR_noWB`, `least_or_none`);
* `halfRange_BPR` -- both sides on `runBPR`: `ts ≤ now + D` and `now ≤ ts + K + 1`, for a lane
  unarmed and unhalted to `T`. With `D ≤ 32767` and `K + 1 ≤ 32768` the RTL's signed `tf_diff`
  reads every such lane correctly.
Scope of item 3: a lane unarmed from an idle start.

Item 4, the restart (every arming episode's end):
* the chain anchored at the release `rel = ts + reb` (`runR_rel_step`, `wb_bound_rel`,
  `wb_close_rel`, `behind_rel`), started from any cycle where the lane is not in its own dispatch
  and `now ≤ rel`; the gap premise is the bridged one, `K + 2 + reb ≤ dly + ext`;
* `restart_at_edge` -- the cycle after any edge of the lane (plain, HALF, a park's rise,
  FALLTHROUGH) meets that start: unarmed, not in its own dispatch (it was armed, so masked), and
  `rel = edge + max 1 off` (or `edge + 1` after the flush);
* `halfRange_episode` -- **from the cycle after an edge, while the lane stays unarmed and
  unhalted: `ts ≤ now + D` and `now ≤ ts + K + 2`** (one more than item 3: the rebase bit).
Not covered: the cycles after a FALLTHROUGH *timeout* (it keeps `ts`, already at or below `now`;
no release-at-`now` start), and the lanes excluded by design while armed / halted.
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

/-- `y` waits this cycle: unarmed, not halted, released, not decided. The idle-cycle budget `S`
is asked only of windows where `y` waits throughout (as `RespWinB.wb_bound_winBK_fl`'s `hS`). -/
def WaitP (y : Lane) (B : EngBP) : Prop :=
  B.A.armed y = false ∧ B.halt y = false ∧ B.A.X.x.e.ts y ≤ B.A.X.x.e.now ∧ ¬DecP win y B

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

instance (y : Lane) (B : EngBP) : Decidable (DecP win y B) :=
  inferInstanceAs (Decidable (Dec (winA win B.mask) y B.A.X.x.e))

/-- Below `k`: a least witness, or none (constructive). -/
theorem least_or_none (p : Nat → Prop) [DecidablePred p] :
    ∀ k, (∃ s, s < k ∧ p s ∧ ∀ s', s' < s → ¬p s') ∨ (∀ s, s < k → ¬p s)
  | 0 => Or.inr (fun _ h => absurd h (Nat.not_lt_zero _))
  | k + 1 => by
    rcases least_or_none p k with ⟨s0, h1, h2, h3⟩ | h
    · exact Or.inl ⟨s0, by omega, h2, h3⟩
    · by_cases hk : p k
      · exact Or.inl ⟨k, by omega, hk, h⟩
      · refine Or.inr (fun s hs hp => ?_)
        rcases Nat.lt_or_ge s k with hl | hg
        · exact h s hl hp
        · have : s = k := by omega
          subst this
          exact hk hp

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

theorem runR_ts_mono2 (y : Lane) (a : Nat) :
    ∀ j, (∀ n, n < j → (R (a + n)).A.armed y = false) →
      (R a).A.X.x.e.ts y ≤ (R (a + j)).A.X.x.e.ts y
  | 0, _ => Nat.le_refl _
  | j + 1, ha => Nat.le_trans (runR_ts_mono2 y a j (fun n hn => ha n (by omega)))
      (runR_ts_step P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y (a + j)
        (ha j (by omega))).1

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
    (hnh : ∀ n, n < t → (R n).halt y = false)
    (hfree : ∀ w, w + 2 < t → IsWB y (R w).A.X.x.e → (R w).A.X.x.e.now < (R t).A.X.x.e.ts y)
    (hM : ∀ c, c + K + 2 ≤ t →
      cntW (fun B => decOther (winA win B.mask) y B.A.X.x.e) R c K ≤ M)
    (hS : ∀ c, c + K + 2 ≤ t → (∀ i, i < K → WaitP win y (R (c + i))) →
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
    have hs := hS c (by omega) (fun i hi => by
      refine ⟨hun _ (by omega), hnh _ (by omega), ?_, hnd i hi⟩
      have hmo := runR_ts_mono2 P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y (c + i)
        (K - i) (fun n hn => hun _ (by omega))
      have e : c + i + (K - i) = c + K := by omega
      rw [e] at hmo
      have := hnow (c + i)
      omega)
    have h2 := ph_le (R c).A.X.x.e.st
    omega

/-! ### Item 3: the closure, progress, and the side behind `now` at every cycle -/

theorem runR_wb_prev (y : Lane) (a : Nat) (hw : IsWB y (R (a + 1)).A.X.x.e) :
    (R a).A.X.x.e.st = .drive ∧ (R a).A.X.x.e.cur = y := by
  obtain ⟨s1, c1⟩ := runR_st P win usb sreq isArm edge isFT offW ntW isPark hdW R hR a
  obtain ⟨hst, hcur⟩ := hw
  rw [s1] at hst
  obtain ⟨hd, hc⟩ := back_wb P _ _ hst
  exact ⟨hd, hc.symm.trans (c1.symm.trans hcur)⟩

theorem runR_wb_dec (y : Lane) (a : Nat) (hw : IsWB y (R (a + 2)).A.X.x.e) :
    DecP win y (R a) := by
  obtain ⟨hd, hc⟩ := runR_wb_prev P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y (a + 1) hw
  obtain ⟨s1, c1⟩ := runR_st P win usb sreq isArm edge isFT offW ntW isPark hdW R hR a
  rw [s1] at hd
  have hdec := back_drive P _ _ hd
  unfold DecP
  rw [← hc, c1]
  exact hdec

/-- No writeback of `y` for two cycles past its last decision, from a cycle not in its own
dispatch. -/
theorem runR_noWB (y : Lane) (n m : Nat)
    (hm : ¬((R n).A.X.x.e.st ≠ .idle ∧ (R n).A.X.x.e.cur = y))
    (hnd : ∀ s, s < m → ¬DecP win y (R (n + s))) :
    ∀ j, j < m + 2 → ¬IsWB y (R (n + j)).A.X.x.e := by
  intro j hj hw
  match j, hw with
  | 0, hw =>
    have hw0 : IsWB y (R n).A.X.x.e := hw
    exact hm ⟨by rw [hw0.1]; decide, hw0.2⟩
  | 1, hw =>
    obtain ⟨hd, hc⟩ := runR_wb_prev P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y n hw
    exact hm ⟨by rw [hd]; decide, hc⟩
  | j' + 2, hw =>
    have e : n + (j' + 2) = n + j' + 2 := by omega
    rw [e] at hw
    exact hnd j' (by omega) (runR_wb_dec P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y
      (n + j') hw)

/-- An unarmed lane off its writebacks keeps its `ts` along `R`. -/
theorem runR_ts_flat (y : Lane) (c : Nat) :
    ∀ n, (∀ i, i < n → (R (c + i)).A.armed y = false ∧ ¬IsWB y (R (c + i)).A.X.x.e) →
      (R (c + n)).A.X.x.e.ts y = (R c).A.X.x.e.ts y
  | 0, _ => rfl
  | n + 1, h => by
    have ih := runR_ts_flat y c n (fun i hi => h i (by omega))
    have hs := (runR_ts_step P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y (c + n)
      (h n (by omega)).1).2 (h n (by omega)).2
    show (R (c + n + 1)).A.X.x.e.ts y = _
    rw [hs, ih]

/-- A writeback of an unarmed lane advances its `ts` by `dly + ext`. -/
theorem runR_ts_wb (y : Lane) (n : Nat) (ha : (R n).A.armed y = false)
    (hw : IsWB y (R n).A.X.x.e) :
    (R (n + 1)).A.X.x.e.ts y = (R n).A.X.x.e.ts y + P.dly y + P.ext (R n).A.X.x.e.now y := by
  obtain ⟨wd, nw, k, h⟩ := hR n
  rw [h]
  obtain ⟨hpe, htm, hfl⟩ := unarmed_quiet win (R n) y ha
  rw [stepBPR_ts, hpe, htm, hfl]
  simp only [Bool.false_eq_true, if_false]
  unfold tsNext
  rw [if_pos ⟨hw.1, hw.2.symm⟩]
  rfl

/-- **The closure**: every writeback of `y` before `T` lands within `K + 1` of its `ts`, by strong
induction over time; `hfree` from the induction and the gap (`hgap`: every writeback's
`dly + ext ≥ K + 2`, gate_lane_cert check 22's `gap ≥ Rr + 3`). -/
theorem wb_close_BPR (h0 : (R 0).A.X.x.e.st = .idle) (y : Lane)
    (h0ts : (R 0).A.X.x.e.now ≤ (R 0).A.X.x.e.ts y)
    (M S K : Nat) (hK : 3 * M + S + 3 ≤ K) (T : Nat)
    (hun : ∀ n, n < T → (R n).A.armed y = false)
    (hnh : ∀ n, n < T → (R n).halt y = false)
    (hgap : ∀ n, n < T → IsWB y (R n).A.X.x.e → K + 2 ≤ P.dly y + P.ext (R n).A.X.x.e.now y)
    (hM : ∀ c, c + K + 2 ≤ T →
      cntW (fun B => decOther (winA win B.mask) y B.A.X.x.e) R c K ≤ M)
    (hS : ∀ c, c + K + 2 ≤ T → (∀ i, i < K → WaitP win y (R (c + i))) →
      cntW (fun B => noDecB (winA win B.mask) B.A.X.x.e) R c K ≤ S) :
    ∀ t, t < T → IsWB y (R t).A.X.x.e → (R t).A.X.x.e.now ≤ (R t).A.X.x.e.ts y + K + 1 := by
  have key : ∀ N, ∀ t, t < N → t < T → IsWB y (R t).A.X.x.e →
      (R t).A.X.x.e.now ≤ (R t).A.X.x.e.ts y + K + 1 := by
    intro N
    induction N with
    | zero => intro t ht; exact absurd ht (Nat.not_lt_zero t)
    | succ N ih =>
    intro t htN htT hwb
    have IH : ∀ w, w < t → w < T → IsWB y (R w).A.X.x.e →
        (R w).A.X.x.e.now ≤ (R w).A.X.x.e.ts y + K + 1 :=
      fun w hw => ih w (by omega)
    refine wb_bound_winBPR P win usb sreq isArm edge isFT offW ntW isPark hdW R hR h0 y h0ts M S K
      hK t hwb (fun n hn => hun n (by omega)) (fun n hn => hnh n (by omega)) ?_
      (fun c hc => hM c (by omega)) (fun c hc hw => hS c (by omega) hw)
    intro w hw hwbw
    have hb := IH w (by omega) (by omega) hwbw
    have h1 := runR_ts_wb P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y w
      (hun w (by omega)) hwbw
    have hg := hgap w (by omega) hwbw
    have hmo := runR_ts_mono2 P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y (w + 1)
      (t - (w + 1)) (fun n hn => hun _ (by omega))
    have e : w + 1 + (t - (w + 1)) = t := by omega
    rw [e] at hmo
    omega
  intro t ht
  exact key (t + 1) t (Nat.lt_succ_self t) ht

/-- **The side behind `now`, every cycle**: on a run where `y` stays unarmed and unhalted to `T`,
at every cycle `n` with `n + K + 2 ≤ T`, `now ≤ ts + K + 1`. A released lane not in its own
dispatch is decided within `K` cycles (else the window budget fails, Lemma A), so it writes back
within `K + 2`, inside the closure's bound, with `ts` flat in between. -/
theorem behind_all_BPR (h0 : (R 0).A.X.x.e.st = .idle) (y : Lane)
    (h0ts : (R 0).A.X.x.e.now ≤ (R 0).A.X.x.e.ts y)
    (M S K : Nat) (hK : 3 * M + S + 3 ≤ K) (T : Nat)
    (hun : ∀ n, n < T → (R n).A.armed y = false)
    (hnh : ∀ n, n < T → (R n).halt y = false)
    (hgap : ∀ n, n < T → IsWB y (R n).A.X.x.e → K + 2 ≤ P.dly y + P.ext (R n).A.X.x.e.now y)
    (hM : ∀ c, c + K + 2 ≤ T →
      cntW (fun B => decOther (winA win B.mask) y B.A.X.x.e) R c K ≤ M)
    (hS : ∀ c, c + K + 2 ≤ T → (∀ i, i < K → WaitP win y (R (c + i))) →
      cntW (fun B => noDecB (winA win B.mask) B.A.X.x.e) R c K ≤ S)
    (n : Nat) (hn : n + K + 2 ≤ T) :
    (R n).A.X.x.e.now ≤ (R n).A.X.x.e.ts y + K + 1 := by
  have hclose := wb_close_BPR P win usb sreq isArm edge isFT offW ntW isPark hdW R hR h0 y h0ts
    M S K hK T hun hnh hgap hM hS
  have hnow := runR_now P win usb sreq isArm edge isFT offW ntW isPark hdW R hR
  by_cases hr : (R n).A.X.x.e.now ≤ (R n).A.X.x.e.ts y
  · omega
  · -- in its own writeback
    by_cases hwb : IsWB y (R n).A.X.x.e
    · exact hclose n (by omega) hwb
    · -- in its own DRIVE: written back next cycle, ts flat
      by_cases hdr : (R n).A.X.x.e.st = .drive ∧ (R n).A.X.x.e.cur = y
      · obtain ⟨s1, c1⟩ := runR_st P win usb sreq isArm edge isFT offW ntW isPark hdW R hR n
        obtain ⟨h3, h4⟩ := step_drive P (winA win (R n).mask) (R n).A.X.x.e hdr.1
        have hw1 : IsWB y (R (n + 1)).A.X.x.e := ⟨s1.trans h3, (c1.trans h4).trans hdr.2⟩
        have hb := hclose (n + 1) (by omega) hw1
        have hf := (runR_ts_step P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y n
          (hun n (by omega))).2 hwb
        have := hnow (n + 1)
        have := hnow n
        omega
      · have hm : ¬((R n).A.X.x.e.st ≠ .idle ∧ (R n).A.X.x.e.cur = y) := by
          rintro ⟨hne, hc⟩
          cases hs : (R n).A.X.x.e.st with
          | idle => exact hne hs
          | drive => exact hdr ⟨hs, hc⟩
          | wb => exact hwb ⟨hs, hc⟩
        -- progress: decided within K
        rcases least_or_none (fun s => DecP win y (R (n + s))) K with ⟨s0, hsK, hdec, hmin⟩ | hnd
        rotate_left
        · exfalso
          have noW := runR_noWB P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y n K hm hnd
          have hA := runR_lemA P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y n K hnd
          have hmM := hM n (by omega)
          have hsS := hS n (by omega) (fun i hi => by
            refine ⟨hun _ (by omega), hnh _ (by omega), ?_, hnd i hi⟩
            have hf := runR_ts_flat P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y n i
              (fun j hj => ⟨hun _ (by omega), noW j (by omega)⟩)
            have := hnow (n + i)
            have := hnow n
            omega)
          have h2 := ph_le (R n).A.X.x.e.st
          omega
        have noW := runR_noWB P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y n
          (s0) hm hmin
        have hw2 := (runR_dec_wb P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y
          (n + s0) hdec).2
        have e : n + s0 + 2 = n + (s0 + 2) := by omega
        rw [e] at hw2
        have hb := hclose (n + (s0 + 2)) (by omega) hw2
        have hf := runR_ts_flat P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y n
          (s0 + 2) (fun j hj => ⟨hun _ (by omega), noW j hj⟩)
        have := hnow (n + (s0 + 2))
        have := hnow n
        omega

end run

/-- `runBPR` is a run of `stepBPR`. -/
theorem isRun_runBPR (wdt nwt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) (B0 : EngBP) :
    IsRunBPR P win usb sreq isArm edge isFT offW ntW isPark hdW
      (fun n => runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0) :=
  fun n => ⟨_, _, _, rfl⟩

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

/-- **The half range on `runBPR`** (agent 1's time-wrap question): a lane unarmed and unhalted to
`T` has, at every cycle `n` with `n + K + 2 ≤ T`, `ts ≤ now + D` and `now ≤ ts + K + 1` -- so with
`D ≤ 32767` and `K + 1 ≤ 32768` the RTL's signed 16-bit `tf_diff` reads it correctly. -/
theorem halfRange_BPR (D : Nat)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hD : ∀ n l, P.dly l + P.ext n l ≤ D) (hoW : ∀ b, offW b ≤ D) (hhW : ∀ b, hdW b ≤ D)
    (wdt nwt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) (B0 : EngBP) (hA0 : HalfAhead D B0)
    (h0 : B0.A.X.x.e.st = .idle) (y : Lane) (h0ts : B0.A.X.x.e.now ≤ B0.A.X.x.e.ts y)
    (M S K : Nat) (hK : 3 * M + S + 3 ≤ K) (T : Nat)
    (hun : ∀ n, n < T →
      (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0).A.armed y = false)
    (hnh : ∀ n, n < T →
      (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0).halt y = false)
    (hgap : ∀ n, n < T →
      IsWB y (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0).A.X.x.e →
      K + 2 ≤ P.dly y
        + P.ext (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0).A.X.x.e.now y)
    (hM : ∀ c, c + K + 2 ≤ T →
      cntW (fun B => decOther (winA win B.mask) y B.A.X.x.e)
        (fun n => runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0) c K ≤ M)
    (hS : ∀ c, c + K + 2 ≤ T → (∀ i, i < K →
        WaitP win y (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (c + i) B0)) →
      cntW (fun B => noDecB (winA win B.mask) B.A.X.x.e)
        (fun n => runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0) c K ≤ S)
    (n : Nat) (hn : n + K + 2 ≤ T) :
    (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0).A.X.x.e.ts y
        ≤ (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0).A.X.x.e.now + D ∧
      (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0).A.X.x.e.now
        ≤ (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0).A.X.x.e.ts y
          + K + 1 :=
  ⟨runBPR_ts_ahead P win usb sreq isArm edge isFT offW ntW isPark hdW D hwin hD hoW hhW
      wdt nwt kt B0 hA0 n y,
    behind_all_BPR P win usb sreq isArm edge isFT offW ntW isPark hdW
      (fun n => runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0)
      (isRun_runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt B0)
      h0 y h0ts M S K hK T hun hnh hgap hM hS n hn⟩

/-! ### Item 4: the restart -- the bound anchored at the release, from any cycle

After an arming ends at its edge, the lane's `ts` is the edge cycle (a FALLTHROUGH flush, or a
plain edge with `off = 0`) with the rebase bit set, so `ts` sits one below `now` while the
release `rel = ts + reb` does not. The chain below is items 2-3 anchored at `rel` (as
`RespWinB.wb_bound_winBK_fl`), started from any cycle where the lane is not in its own dispatch
(`NotMid`, in place of an idle engine) and released no earlier than `now`. -/

/-- The rebase bit after one cycle. -/
theorem stepBPR_reb (wd nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) (l : Lane) :
    (stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B).A.X.reb l =
      if B.pe l = true then decide (B.off l = 0)
      else if B.tmo win l = true then B.A.X.reb l
      else if B.fl win l = true then true
      else if B.A.X.x.e.st = .wb ∧ l = B.A.X.x.e.cur ∧
          0 < (P.haltP B.halt).dly l + (P.haltP B.halt).ext B.A.X.x.e.now l then false
      else B.A.X.reb l := rfl

theorem rel_eq (X : EngBK) (l : Lane) : X.rel l = X.x.e.ts l + (if X.reb l = true then 1 else 0) :=
  rfl

section run2
variable (R : Nat → EngBP) (hR : IsRunBPR P win usb sreq isArm edge isFT offW ntW isPark hdW R)
include hR

/-- An unarmed lane's release: never decreases, flat off its writeback, and at a writeback with
`dly + ext > 0` it is the old `ts` plus `dly + ext` (the rebase bit cleared). -/
theorem runR_rel_step (y : Lane) (n : Nat) (ha : (R n).A.armed y = false) :
    (R n).A.X.rel y ≤ (R (n + 1)).A.X.rel y ∧
      (¬IsWB y (R n).A.X.x.e → (R (n + 1)).A.X.rel y = (R n).A.X.rel y) ∧
      (IsWB y (R n).A.X.x.e → 0 < P.dly y + P.ext (R n).A.X.x.e.now y →
        (R (n + 1)).A.X.rel y = (R n).A.X.x.e.ts y + P.dly y + P.ext (R n).A.X.x.e.now y) := by
  obtain ⟨wd, nw, k, h⟩ := hR n
  rw [h]
  obtain ⟨hpe, htm, hfl⟩ := unarmed_quiet win (R n) y ha
  have hts := stepBPR_ts P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k (R n) y
  have hrb := stepBPR_reb P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k (R n) y
  rw [hpe, htm, hfl] at hts hrb
  simp only [Bool.false_eq_true, if_false] at hts hrb
  have e1 : (P.haltP (R n).halt).dly = P.dly := rfl
  have e2 : (P.haltP (R n).halt).ext = P.ext := rfl
  rw [e1, e2] at hrb
  unfold tsNext at hts
  rw [e1, e2] at hts
  generalize stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k (R n) = B' at hts hrb ⊢
  have hr0 := rel_eq (R n).A.X y
  have hr1 := rel_eq B'.A.X y
  by_cases hw : (R n).A.X.x.e.st = .wb ∧ y = (R n).A.X.x.e.cur
  · have hw' : IsWB y (R n).A.X.x.e := ⟨hw.1, hw.2.symm⟩
    have hts' : B'.A.X.x.e.ts y
        = (R n).A.X.x.e.ts y + P.dly y + P.ext (R n).A.X.x.e.now y := by rw [hts, if_pos hw]
    by_cases hd : 0 < P.dly y + P.ext (R n).A.X.x.e.now y
    · have hrb' : B'.A.X.reb y = false := by rw [hrb, if_pos ⟨hw.1, hw.2, hd⟩]
      rw [hrb'] at hr1
      have hb := rbit_le ((R n).A.X.reb y)
      refine ⟨?_, fun h' => absurd hw' h', fun _ _ => ?_⟩
      · simp only [Bool.false_eq_true, if_false] at hr1; omega
      · simp only [Bool.false_eq_true, if_false] at hr1; omega
    · have hrb' : B'.A.X.reb y = (R n).A.X.reb y := by
        rw [hrb, if_neg (fun h' => hd h'.2.2)]
      rw [hrb'] at hr1
      refine ⟨by omega, fun h' => absurd hw' h', fun _ h' => absurd h' hd⟩
  · have hts' : B'.A.X.x.e.ts y = (R n).A.X.x.e.ts y := by rw [hts, if_neg hw]
    have hrb' : B'.A.X.reb y = (R n).A.X.reb y := by
      rw [hrb, if_neg (fun h' => hw ⟨h'.1, h'.2.1⟩)]
    rw [hrb'] at hr1
    exact ⟨by omega, fun _ => by omega, fun h' => absurd ⟨h'.1, h'.2.symm⟩ hw⟩

theorem runR_rel_mono2 (y : Lane) (a : Nat) :
    ∀ j, (∀ n, n < j → (R (a + n)).A.armed y = false) →
      (R a).A.X.rel y ≤ (R (a + j)).A.X.rel y
  | 0, _ => Nat.le_refl _
  | j + 1, ha => Nat.le_trans (runR_rel_mono2 y a j (fun n hn => ha n (by omega)))
      (runR_rel_step P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y (a + j)
        (ha j (by omega))).1

theorem runR_rel_flat2 (y : Lane) (c : Nat) :
    ∀ n, (∀ i, i < n → (R (c + i)).A.armed y = false ∧ ¬IsWB y (R (c + i)).A.X.x.e) →
      (R (c + n)).A.X.rel y = (R c).A.X.rel y
  | 0, _ => rfl
  | n + 1, h => by
    have ih := runR_rel_flat2 y c n (fun i hi => h i (by omega))
    have hs := (runR_rel_step P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y (c + n)
      (h n (by omega)).1).2.1 (h n (by omega)).2
    show (R (c + n + 1)).A.X.rel y = _
    rw [hs, ih]

/-- A writeback of `y` at `t`, from a start where `y` is not in its own dispatch, is two cycles
after `y`'s decision. -/
theorem runR_wb_back2 (h0m : ¬((R 0).A.X.x.e.st ≠ .idle ∧ (R 0).A.X.x.e.cur = y)) (t : Nat)
    (hwb : IsWB y (R t).A.X.x.e) : ∃ s, t = s + 2 ∧ DecP win y (R s) := by
  match t, hwb with
  | 0, hwb => exact absurd ⟨by rw [hwb.1]; decide, hwb.2⟩ h0m
  | 1, hwb =>
    obtain ⟨hd, hc⟩ := runR_wb_prev P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y 0 hwb
    exact absurd ⟨by rw [hd]; decide, hc⟩ h0m
  | s + 2, hwb => exact ⟨s, rfl, runR_wb_dec P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y s hwb⟩

/-- `y` waits, released by the RTL's release. -/
def WaitR (y : Lane) (B : EngBP) : Prop :=
  B.A.armed y = false ∧ B.halt y = false ∧ B.A.X.rel y ≤ B.A.X.x.e.now ∧ ¬DecP win y B

/-- **The response bound, anchored at the release, from any start** where `y` is not in its own
dispatch and released no earlier than `now`. -/
theorem wb_bound_rel (y : Lane) (h0m : ¬((R 0).A.X.x.e.st ≠ .idle ∧ (R 0).A.X.x.e.cur = y))
    (h0rel : (R 0).A.X.x.e.now ≤ (R 0).A.X.rel y)
    (M S K : Nat) (hK : 3 * M + S + 3 ≤ K)
    (t : Nat) (hwb : IsWB y (R t).A.X.x.e)
    (hun : ∀ n, n < t → (R n).A.armed y = false)
    (hnh : ∀ n, n < t → (R n).halt y = false)
    (hfree : ∀ w, w + 2 < t → IsWB y (R w).A.X.x.e → (R w).A.X.x.e.now < (R t).A.X.rel y)
    (hM : ∀ c, c + K + 2 ≤ t →
      cntW (fun B => decOther (winA win B.mask) y B.A.X.x.e) R c K ≤ M)
    (hS : ∀ c, c + K + 2 ≤ t → (∀ i, i < K → WaitR win y (R (c + i))) →
      cntW (fun B => noDecB (winA win B.mask) B.A.X.x.e) R c K ≤ S) :
    (R t).A.X.x.e.now ≤ (R t).A.X.rel y + K + 1 := by
  obtain ⟨D, rfl, hdec⟩ := runR_wb_back2 P win usb sreq isArm edge isFT offW ntW isPark hdW R hR h0m t hwb
  have hidle : (R D).A.X.x.e.st = .idle := hdec.1
  have hdrive := (runR_dec_wb P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y D hdec).1
  have t1 := (runR_rel_step P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y D
    (hun D (by omega))).2.1 (not_wb_of_st y _ (by rw [hidle]; decide))
  have t2 := (runR_rel_step P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y (D + 1)
    (hun (D + 1) (by omega))).2.1 (not_wb_of_st y _ (by rw [hdrive]; decide))
  have hrel2 : (R (D + 2)).A.X.rel y = (R D).A.X.rel y := t2.trans t1
  have hnow := runR_now P win usb sreq isArm edge isFT offW ntW isPark hdW R hR
  rw [hrel2, hnow (D + 2)]
  rw [hrel2] at hfree
  by_cases hfit : (R 0).A.X.x.e.now + D + 1 ≤ (R D).A.X.rel y + K
  · omega
  · exfalso
    have hr0 := runR_rel_mono2 P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y 0 D
      (fun n hn => hun _ (by omega))
    rw [Nat.zero_add] at hr0
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
    have hs := hS c (by omega) (fun i hi => by
      refine ⟨hun _ (by omega), hnh _ (by omega), ?_, hnd i hi⟩
      have hmo := runR_rel_mono2 P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y (c + i)
        (K - i) (fun n hn => hun _ (by omega))
      have e : c + i + (K - i) = c + K := by omega
      rw [e] at hmo
      have := hnow (c + i)
      omega)
    have h2 := ph_le (R c).A.X.x.e.st
    omega

/-- **The closure, anchored at the release**: the gap premise is the bridged one
(`HfreeR.hrelR_bridged`'s `hgap`): `K + 2` plus the rebase bit, at most `dly + ext`. -/
theorem wb_close_rel (y : Lane) (h0m : ¬((R 0).A.X.x.e.st ≠ .idle ∧ (R 0).A.X.x.e.cur = y))
    (h0rel : (R 0).A.X.x.e.now ≤ (R 0).A.X.rel y)
    (M S K : Nat) (hK : 3 * M + S + 3 ≤ K) (T : Nat)
    (hun : ∀ n, n < T → (R n).A.armed y = false)
    (hnh : ∀ n, n < T → (R n).halt y = false)
    (hgap : ∀ n, n < T → IsWB y (R n).A.X.x.e →
      K + 2 + (if (R n).A.X.reb y = true then 1 else 0) ≤ P.dly y + P.ext (R n).A.X.x.e.now y)
    (hM : ∀ c, c + K + 2 ≤ T →
      cntW (fun B => decOther (winA win B.mask) y B.A.X.x.e) R c K ≤ M)
    (hS : ∀ c, c + K + 2 ≤ T → (∀ i, i < K → WaitR win y (R (c + i))) →
      cntW (fun B => noDecB (winA win B.mask) B.A.X.x.e) R c K ≤ S) :
    ∀ t, t < T → IsWB y (R t).A.X.x.e → (R t).A.X.x.e.now ≤ (R t).A.X.rel y + K + 1 := by
  have key : ∀ N, ∀ t, t < N → t < T → IsWB y (R t).A.X.x.e →
      (R t).A.X.x.e.now ≤ (R t).A.X.rel y + K + 1 := by
    intro N
    induction N with
    | zero => intro t ht; exact absurd ht (Nat.not_lt_zero t)
    | succ N ih =>
    intro t htN htT hwb
    refine wb_bound_rel P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y h0m h0rel M S K
      hK t hwb (fun n hn => hun n (by omega)) (fun n hn => hnh n (by omega)) ?_
      (fun c hc => hM c (by omega)) (fun c hc hw => hS c (by omega) hw)
    intro w hw hwbw
    have hb := ih w (by omega) (by omega) hwbw
    have hg := hgap w (by omega) hwbw
    have h1 := (runR_rel_step P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y w
      (hun w (by omega))).2.2 hwbw (by omega)
    have hr := rel_eq (R w).A.X y
    have hmo := runR_rel_mono2 P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y (w + 1)
      (t - (w + 1)) (fun n hn => hun _ (by omega))
    have e : w + 1 + (t - (w + 1)) = t := by omega
    rw [e] at hmo
    omega
  intro t ht
  exact key (t + 1) t (Nat.lt_succ_self t) ht

/-- **Behind `now`, every cycle, anchored at the release**: `now ≤ rel + K + 1` at every cycle
`n` with `n + K + 2 ≤ T` (so `now ≤ ts + K + 2`). -/
theorem behind_rel (y : Lane) (h0m : ¬((R 0).A.X.x.e.st ≠ .idle ∧ (R 0).A.X.x.e.cur = y))
    (h0rel : (R 0).A.X.x.e.now ≤ (R 0).A.X.rel y)
    (M S K : Nat) (hK : 3 * M + S + 3 ≤ K) (T : Nat)
    (hun : ∀ n, n < T → (R n).A.armed y = false)
    (hnh : ∀ n, n < T → (R n).halt y = false)
    (hgap : ∀ n, n < T → IsWB y (R n).A.X.x.e →
      K + 2 + (if (R n).A.X.reb y = true then 1 else 0) ≤ P.dly y + P.ext (R n).A.X.x.e.now y)
    (hM : ∀ c, c + K + 2 ≤ T →
      cntW (fun B => decOther (winA win B.mask) y B.A.X.x.e) R c K ≤ M)
    (hS : ∀ c, c + K + 2 ≤ T → (∀ i, i < K → WaitR win y (R (c + i))) →
      cntW (fun B => noDecB (winA win B.mask) B.A.X.x.e) R c K ≤ S)
    (n : Nat) (hn : n + K + 2 ≤ T) :
    (R n).A.X.x.e.now ≤ (R n).A.X.rel y + K + 1 := by
  have hclose := wb_close_rel P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y h0m h0rel
    M S K hK T hun hnh hgap hM hS
  have hnow := runR_now P win usb sreq isArm edge isFT offW ntW isPark hdW R hR
  by_cases hr : (R n).A.X.x.e.now ≤ (R n).A.X.rel y
  · omega
  · by_cases hwb : IsWB y (R n).A.X.x.e
    · exact hclose n (by omega) hwb
    · by_cases hdr : (R n).A.X.x.e.st = .drive ∧ (R n).A.X.x.e.cur = y
      · obtain ⟨s1, c1⟩ := runR_st P win usb sreq isArm edge isFT offW ntW isPark hdW R hR n
        obtain ⟨h3, h4⟩ := step_drive P (winA win (R n).mask) (R n).A.X.x.e hdr.1
        have hw1 : IsWB y (R (n + 1)).A.X.x.e := ⟨s1.trans h3, (c1.trans h4).trans hdr.2⟩
        have hb := hclose (n + 1) (by omega) hw1
        have hf := (runR_rel_step P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y n
          (hun n (by omega))).2.1 hwb
        have := hnow (n + 1)
        have := hnow n
        omega
      · have hm : ¬((R n).A.X.x.e.st ≠ .idle ∧ (R n).A.X.x.e.cur = y) := by
          rintro ⟨hne, hc⟩
          cases hs : (R n).A.X.x.e.st with
          | idle => exact hne hs
          | drive => exact hdr ⟨hs, hc⟩
          | wb => exact hwb ⟨hs, hc⟩
        rcases least_or_none (fun s => DecP win y (R (n + s))) K with ⟨s0, hsK, hdec, hmin⟩ | hnd
        rotate_left
        · exfalso
          have noW := runR_noWB P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y n K hm hnd
          have hA := runR_lemA P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y n K hnd
          have hmM := hM n (by omega)
          have hsS := hS n (by omega) (fun i hi => by
            refine ⟨hun _ (by omega), hnh _ (by omega), ?_, hnd i hi⟩
            have hf := runR_rel_flat2 P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y n i
              (fun j hj => ⟨hun _ (by omega), noW j (by omega)⟩)
            have := hnow (n + i)
            have := hnow n
            omega)
          have h2 := ph_le (R n).A.X.x.e.st
          omega
        have noW := runR_noWB P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y n s0 hm hmin
        have hw2 := (runR_dec_wb P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y
          (n + s0) hdec).2
        have e : n + s0 + 2 = n + (s0 + 2) := by omega
        rw [e] at hw2
        have hb := hclose (n + (s0 + 2)) (by omega) hw2
        have hf := runR_rel_flat2 P win usb sreq isArm edge isFT offW ntW isPark hdW R hR y n
          (s0 + 2) (fun j hj => ⟨hun _ (by omega), noW j hj⟩)
        have := hnow (n + (s0 + 2))
        have := hnow n
        omega

end run2

/-- An armed or halted lane is never the masked winner. -/
theorem winA_mask (win : Engine → Option Lane) (B : EngBP) (l : Lane) (h : B.mask l = true)
    (e : Engine) : winA win B.mask e ≠ some l := by
  unfold winA
  cases hw : win e with
  | none => simp
  | some v =>
    simp only
    by_cases hv : v = l
    · subst hv; rw [if_pos h]; simp
    · split
      · simp
      · intro hc; exact hv (Option.some.inj hc)

/-- **The restart**: the cycle after an edge of `y` (a plain edge, HALF, a park's rise, or a
FALLTHROUGH edge) meets the release-anchored chain's start: `y` unarmed, not in its own
dispatch, and released no earlier than `now` (`rel = edge + max 1 off`, or `edge + 1` for the
flush). `hH`: the ahead invariant at the edge (`runBPR_halfAhead`). -/
theorem restart_at_edge (D : Nat) (wd nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) (y : Lane)
    (hH : HalfAhead D B) (hhit : B.A.hit y = true) :
    let B' := stepBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B
    B'.A.armed y = false ∧
      ¬(B'.A.X.x.e.st ≠ .idle ∧ B'.A.X.x.e.cur = y) ∧
      B'.A.X.x.e.now ≤ B'.A.X.rel y := by
  intro B'
  have harm : B.A.armed y = true := by
    unfold EngBA.hit at hhit; simp only [Bool.and_eq_true] at hhit; exact hhit.1
  have hnow := stepBPR_now P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B
  refine ⟨?_, ?_, ?_⟩
  · show (if (B.ends win y || wd y) = true then false else _) = false
    rw [if_pos (by unfold EngBP.ends; rw [hhit]; simp)]
  · -- not mid at the edge (armed), not decided there (masked): not mid after
    have hm : NotMid y B.A.X.x.e := by
      rintro ⟨hne, hc⟩
      have := (hH.cur hne).2
      rw [hc, harm] at this
      cases this
    have hnd : ¬Dec (winA win B.mask) y B.A.X.x.e := fun hd =>
      winA_mask win B y (by unfold EngBP.mask; rw [harm]; simp) B.A.X.x.e hd.2.1
    have h := notMid_step P (winA win B.mask) y B.A.X.x.e hm hnd
    obtain ⟨s1, c1⟩ := stepBPR_st_step P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B
    unfold NotMid at h
    show ¬(B'.A.X.x.e.st ≠ .idle ∧ B'.A.X.x.e.cur = y)
    rw [show B'.A.X.x.e.st = _ from s1, show B'.A.X.x.e.cur = _ from c1]
    exact h
  · show B'.A.X.x.e.now ≤ B'.A.X.rel y
    rw [show B'.A.X.x.e.now = _ from hnow]
    cases hft : B.ft y with
    | false =>
      have hpe : B.pe y = true := by unfold EngBP.pe; rw [hhit, hft]; rfl
      rw [show B'.A.X.rel y = _ from
        stepBPR_pe_rel P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B y hpe]
      omega
    | true =>
      have hpe : B.pe y = false := by unfold EngBP.pe; rw [hft]; simp
      have htm : B.tmo win y = false := by
        unfold EngBP.tmo; rw [hit_tmo_excl B.A win y hhit]; simp
      have hfl : B.fl win y = true := by
        unfold EngBP.fl EngBP.ends; rw [hhit, hft]; simp
      have hts := stepBPR_ts P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B y
      have hrb := stepBPR_reb P win usb sreq isArm edge isFT offW ntW isPark hdW wd nw k B y
      rw [hpe, htm, hfl] at hts hrb
      simp only [Bool.false_eq_true, if_false, if_true] at hts hrb
      show B.A.X.x.e.now + 1 ≤ B'.A.X.x.e.ts y + (if B'.A.X.reb y = true then 1 else 0)
      rw [show B'.A.X.x.e.ts y = _ from hts, show B'.A.X.reb y = _ from hrb]
      simp

/-- A shifted run is a run. -/
theorem isRun_shift (R : Nat → EngBP)
    (hR : IsRunBPR P win usb sreq isArm edge isFT offW ntW isPark hdW R) (a : Nat) :
    IsRunBPR P win usb sreq isArm edge isFT offW ntW isPark hdW (fun m => R (a + m)) :=
  fun m => hR (a + m)

/-- **The half range after an arming episode** (the restart): on `runBPR`, from the cycle after
an edge of `y` at `e`, while `y` stays unarmed and unhalted to `e + 1 + T`, every cycle
`e + 1 + n` with `n + K + 2 ≤ T` has `ts ≤ now + D` and `now ≤ ts + K + 2`. The premises are
those of `halfRange_BPR`, read on the episode (`R m = runBPR (e + 1 + m)`), with the gap's
rebase bit (`K + 2 + reb ≤ dly + ext`, the bridged form). -/
theorem halfRange_episode (D : Nat)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hD : ∀ n l, P.dly l + P.ext n l ≤ D) (hoW : ∀ b, offW b ≤ D) (hhW : ∀ b, hdW b ≤ D)
    (wdt nwt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) (B0 : EngBP) (hA0 : HalfAhead D B0)
    (y : Lane) (e : Nat)
    (hhit : (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt e B0).A.hit y = true)
    (M S K : Nat) (hK : 3 * M + S + 3 ≤ K) (T : Nat)
    (hun : ∀ n, n < T →
      (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (e + 1 + n) B0).A.armed y
        = false)
    (hnh : ∀ n, n < T →
      (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (e + 1 + n) B0).halt y
        = false)
    (hgap : ∀ n, n < T →
      IsWB y (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (e + 1 + n) B0).A.X.x.e →
      K + 2 + (if (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (e + 1 + n)
          B0).A.X.reb y = true then 1 else 0)
        ≤ P.dly y + P.ext
          (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (e + 1 + n) B0).A.X.x.e.now y)
    (hM : ∀ c, c + K + 2 ≤ T →
      cntW (fun B => decOther (winA win B.mask) y B.A.X.x.e)
        (fun m => runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (e + 1 + m) B0)
        c K ≤ M)
    (hS : ∀ c, c + K + 2 ≤ T → (∀ i, i < K →
        WaitR win y (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt
          (e + 1 + (c + i)) B0)) →
      cntW (fun B => noDecB (winA win B.mask) B.A.X.x.e)
        (fun m => runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (e + 1 + m) B0)
        c K ≤ S)
    (n : Nat) (hn : n + K + 2 ≤ T) :
    (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (e + 1 + n) B0).A.X.x.e.ts y
        ≤ (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (e + 1 + n) B0).A.X.x.e.now
          + D ∧
      (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (e + 1 + n) B0).A.X.x.e.now
        ≤ (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (e + 1 + n) B0).A.X.x.e.ts y
          + K + 2 := by
  have hHe := runBPR_halfAhead P win usb sreq isArm edge isFT offW ntW isPark hdW D hwin hD hoW hhW
    wdt nwt kt B0 hA0 e
  obtain ⟨_, h0m, h0rel⟩ := restart_at_edge P win usb sreq isArm edge isFT offW ntW isPark hdW D
    _ _ _ _ y hHe hhit
  have hRun := isRun_shift P win usb sreq isArm edge isFT offW ntW isPark hdW
    (fun n => runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt n B0)
    (isRun_runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt B0) (e + 1)
  have hb := behind_rel P win usb sreq isArm edge isFT offW ntW isPark hdW
    (fun m => runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (e + 1 + m) B0)
    hRun y (by simpa using h0m) (by simpa using h0rel) M S K hK T hun hnh hgap hM hS n hn
  have hr := rel_eq
    (runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (e + 1 + n) B0).A.X y
  have hrb := rbit_le
    ((runBPR P win usb sreq isArm edge isFT offW ntW isPark hdW wdt nwt kt (e + 1 + n) B0).A.X.reb y)
  refine ⟨runBPR_ts_ahead P win usb sreq isArm edge isFT offW ntW isPark hdW D hwin hD hoW hhW
    wdt nwt kt B0 hA0 (e + 1 + n) y, ?_⟩
  simp only at hb
  omega

end

end JLane
