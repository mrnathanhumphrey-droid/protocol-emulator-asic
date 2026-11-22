import JLane.CloseBKSpan
import JLane.ComposeB
/-!
# Brick C3g — the release chain on the bridged run (the flush lemma for `hspan`, `runBK` half)

On the flush run a flush never lowers the view's release (`FlushChain.ts_chainF_ge`). On `runBK`
there is no view: an arming writeback sets `ts + dly + ext` (for a FALLTHROUGH ARM, its deadline
`D`), and the edge's flush sets `now + 1` -- an edge before `D` lowers the release. So the chain
counts an arming writeback's gap as the checker does, `gA` (the ARM's span gap: the earliest
edge after its release, or its timeout), not as `dly + ext`:

* the timeout path (no flush before the next writeback): the writeback opened `dly + ext ≥ gA`
  (`hgw`);
* the edge path: the flush releases at `edge + 1 ≥ release + gA` (`hge`, the edge-timing
  premise); `armed_origin` ties each flush to its ARM, and nothing of the lane is written back
  while it is armed (`ArmInvB`);
* the chain starts at a writeback of the lane (the anchor of `wb_closeBK_span`'s `hspan`), so it
  never starts while the lane is armed -- the dip from `D` to `edge + 1` is never counted from
  inside.

`ts_chainBK_ge` states it on `runBK` (`runBA_proj`).
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)
  (kt : Nat → Lane → Nat) (A0 : EngBA)

/-- What lane `y`'s writeback at `x` contributes to the chain: an ARM's span gap `gA x` at an
arming writeback, `dly + ext` at any other, nothing off a writeback. -/
def cBA (y : Lane) (gA : Nat → Nat) (x : Nat) : Nat :=
  if IsWB y (runBA P win usb sreq isArm edge kt x A0).X.x.e then
    (if (runBA P win usb sreq isArm edge kt x A0).arms P isArm y = true then gA x
     else P.dly y + P.ext (runBA P win usb sreq isArm edge kt x A0).X.x.e.now y)
  else 0

/-- The contributions over `[a, a + n)`. -/
def gsumBA (y : Lane) (gA : Nat → Nat) (a : Nat) : Nat → Nat
  | 0 => 0
  | n + 1 => gsumBA y gA a n + cBA P win usb sreq isArm edge kt A0 y gA (a + n)

theorem gsumBA_skip (y : Lane) (gA : Nat → Nat) (a m : Nat) :
    ∀ d, (∀ i, i < d → cBA P win usb sreq isArm edge kt A0 y gA (a + m + i) = 0) →
      gsumBA P win usb sreq isArm edge kt A0 y gA a (m + d)
        = gsumBA P win usb sreq isArm edge kt A0 y gA a m
  | 0, _ => rfl
  | d + 1, h => by
    have ih := gsumBA_skip y gA a m d (fun i hi => h i (by omega))
    show gsumBA P win usb sreq isArm edge kt A0 y gA a (m + d)
        + cBA P win usb sreq isArm edge kt A0 y gA (a + (m + d)) = _
    rw [ih, show a + (m + d) = a + m + d by omega, h d (by omega), Nat.add_zero]

/-- A hit releases the lane one past now. -/
theorem tsBA_hit (n : Nat) (y : Lane)
    (h : (runBA P win usb sreq isArm edge kt n A0).hit y = true) :
    (runBA P win usb sreq isArm edge kt (n + 1) A0).X.x.e.ts y
      = (runBA P win usb sreq isArm edge kt n A0).X.x.e.now + 1 := by
  rw [runBA_succ]
  show (if (runBA P win usb sreq isArm edge kt n A0).hit y = true
      then (runBA P win usb sreq isArm edge kt n A0).X.base.e.now + 1
      else (stepB P (winA win (runBA P win usb sreq isArm edge kt n A0).armed) usb sreq
        (runBA P win usb sreq isArm edge kt n A0).X.base).e.ts y) = _
  rw [if_pos h, base_e]

/-- No hit: the release moves only by the writeback rule. -/
theorem tsBA_nohit (n : Nat) (y : Lane)
    (h : (runBA P win usb sreq isArm edge kt n A0).hit y = false) :
    (runBA P win usb sreq isArm edge kt (n + 1) A0).X.x.e.ts y
      = tsNext P (runBA P win usb sreq isArm edge kt n A0).X.x.e y := by
  rw [runBA_succ]
  exact stepBKK_ts_y P (winA win (runBA P win usb sreq isArm edge kt n A0).armed) usb sreq _ _ _ y h

/-- **The release chain on the armed run**: from a writeback of `y`, the release after `n` cycles
is at least the release then plus each writeback's contribution, an ARM's counted as its span
gap `gA` -- given `gA` within the writeback's own opening (`hgw`) and its edge no earlier than
`gA` past its release, less one (`hge`). -/
theorem ts_chainBA_ge (hedge : ∀ t l, t + 1 ≤ edge t l) (hA : ArmInvB A0)
    (h0a : ∀ l, A0.armed l = false) (y : Lane) (gA : Nat → Nat) (a : Nat)
    (hwa : IsWB y (runBA P win usb sreq isArm edge kt a A0).X.x.e)
    (hgw : ∀ x, IsWB y (runBA P win usb sreq isArm edge kt x A0).X.x.e →
      (runBA P win usb sreq isArm edge kt x A0).arms P isArm y = true →
      gA x ≤ P.dly y + P.ext (runBA P win usb sreq isArm edge kt x A0).X.x.e.now y)
    (hge : ∀ x, (runBA P win usb sreq isArm edge kt x A0).arms P isArm y = true →
      (runBA P win usb sreq isArm edge kt x A0).X.x.e.ts y + gA x
        ≤ edge (runBA P win usb sreq isArm edge kt x A0).X.x.e.now y + 1) :
    ∀ n, (runBA P win usb sreq isArm edge kt a A0).X.x.e.ts y
        + gsumBA P win usb sreq isArm edge kt A0 y gA a n
      ≤ (runBA P win usb sreq isArm edge kt (a + n) A0).X.x.e.ts y := by
  have hI := fun i => armInvB_runBA P win usb sreq isArm edge hedge kt A0 hA i
  have noWBa : ∀ i, (runBA P win usb sreq isArm edge kt i A0).armed y = true →
      ¬IsWB y (runBA P win usb sreq isArm edge kt i A0).X.x.e := fun i ha hw =>
    (hI i).1 y ha ⟨by rw [hw.1]; decide, hw.2⟩
  have key : ∀ N, ∀ n, n < N → (runBA P win usb sreq isArm edge kt a A0).X.x.e.ts y
        + gsumBA P win usb sreq isArm edge kt A0 y gA a n
      ≤ (runBA P win usb sreq isArm edge kt (a + n) A0).X.x.e.ts y := by
    intro N
    induction N with
    | zero => intro n hn; exact absurd hn (Nat.not_lt_zero n)
    | succ N ih =>
      intro n hn
      rcases Nat.lt_or_ge n N with hlt | hge'
      · exact ih n hlt
      · cases n with
        | zero => simp [gsumBA]
        | succ k =>
          show _ ≤ (runBA P win usb sreq isArm edge kt (a + k + 1) A0).X.x.e.ts y
          have hstep : gsumBA P win usb sreq isArm edge kt A0 y gA a (k + 1)
              = gsumBA P win usb sreq isArm edge kt A0 y gA a k
                + cBA P win usb sreq isArm edge kt A0 y gA (a + k) := rfl
          cases hh : (runBA P win usb sreq isArm edge kt (a + k) A0).hit y with
          | true =>
            have hh' := hh
            unfold EngBA.hit at hh'
            simp only [Bool.and_eq_true, decide_eq_true_eq] at hh'
            obtain ⟨ha, hnow⟩ := hh'
            obtain ⟨t0, ht0, harm0, hE0, hpers⟩ :=
              armed_origin P win usb sreq isArm edge kt A0 h0a y (a + k) ha
            -- the ARM is inside the chain: the lane was not armed at its start (a writeback)
            have ht0a : a ≤ t0 := by
              rcases Nat.lt_or_ge t0 a with hlt' | hge''
              · exact absurd hwa (noWBa a (hpers a hlt' (by omega)).1)
              · exact hge''
            have hwb0 : IsWB y (runBA P win usb sreq isArm edge kt t0 A0).X.x.e := by
              have h' := harm0
              simp only [EngBA.arms, Bool.and_eq_true, decide_eq_true_eq] at h'
              obtain ⟨⟨⟨hst, hcur⟩, -⟩, -⟩ := h'
              exact ⟨hst, hcur.symm⟩
            have hc0 : cBA P win usb sreq isArm edge kt A0 y gA t0 = gA t0 := by
              unfold cBA
              rw [if_pos hwb0, if_pos harm0]
            -- armed from the ARM to the hit: no writeback of y in between
            have hskip := gsumBA_skip P win usb sreq isArm edge kt A0 y gA a (t0 - a + 1)
              (a + k + 1 - (t0 + 1)) (fun i hi => by
                unfold cBA
                rw [if_neg (noWBa _ (hpers (a + (t0 - a + 1) + i) (by omega) (by omega)).1)])
            rw [show t0 - a + 1 + (a + k + 1 - (t0 + 1)) = k + 1 by omega] at hskip
            have hst0 : gsumBA P win usb sreq isArm edge kt A0 y gA a (t0 - a + 1)
                = gsumBA P win usb sreq isArm edge kt A0 y gA a (t0 - a)
                  + cBA P win usb sreq isArm edge kt A0 y gA (a + (t0 - a)) := rfl
            rw [show a + (t0 - a) = t0 by omega, hc0] at hst0
            have hih := ih (t0 - a) (by omega)
            rw [show a + (t0 - a) = t0 by omega] at hih
            have hg := hge t0 harm0
            have hts := tsBA_hit P win usb sreq isArm edge kt A0 (a + k) y hh
            omega
          | false =>
            have hik := ih k (by omega)
            have hts := tsBA_nohit P win usb sreq isArm edge kt A0 (a + k) y hh
            by_cases hw : IsWB y (runBA P win usb sreq isArm edge kt (a + k) A0).X.x.e
            · have hc : cBA P win usb sreq isArm edge kt A0 y gA (a + k)
                  ≤ P.dly y + P.ext (runBA P win usb sreq isArm edge kt (a + k) A0).X.x.e.now y := by
                unfold cBA
                rw [if_pos hw]
                split
                · rename_i harm
                  exact hgw (a + k) hw harm
                · exact Nat.le_refl _
              have hts' : (runBA P win usb sreq isArm edge kt (a + k + 1) A0).X.x.e.ts y
                  = (runBA P win usb sreq isArm edge kt (a + k) A0).X.x.e.ts y + P.dly y
                    + P.ext (runBA P win usb sreq isArm edge kt (a + k) A0).X.x.e.now y := by
                rw [hts]
                unfold tsNext
                rw [if_pos ⟨hw.1, hw.2.symm⟩]
              omega
            · have hc : cBA P win usb sreq isArm edge kt A0 y gA (a + k) = 0 := by
                unfold cBA
                rw [if_neg hw]
              have hts' : (runBA P win usb sreq isArm edge kt (a + k + 1) A0).X.x.e.ts y
                  = (runBA P win usb sreq isArm edge kt (a + k) A0).X.x.e.ts y := by
                rw [hts]
                unfold tsNext
                rw [if_neg (fun h' => hw ⟨h'.1, h'.2.symm⟩)]
              omega
  intro n
  exact key (n + 1) n (by omega)

/-- **The release chain on `runBK`** (the bridged run): `ts_chainBA_ge` through `runBA_proj`. -/
theorem ts_chainBK_ge (hedge : ∀ t l, t + 1 ≤ edge t l) (hA : ArmInvB A0)
    (h0a : ∀ l, A0.armed l = false) (y : Lane) (gA : Nat → Nat) (a : Nat)
    (hwa : IsWB y (runBA P win usb sreq isArm edge kt a A0).X.x.e)
    (hgw : ∀ x, IsWB y (runBA P win usb sreq isArm edge kt x A0).X.x.e →
      (runBA P win usb sreq isArm edge kt x A0).arms P isArm y = true →
      gA x ≤ P.dly y + P.ext (runBA P win usb sreq isArm edge kt x A0).X.x.e.now y)
    (hge : ∀ x, (runBA P win usb sreq isArm edge kt x A0).arms P isArm y = true →
      (runBA P win usb sreq isArm edge kt x A0).X.x.e.ts y + gA x
        ≤ edge (runBA P win usb sreq isArm edge kt x A0).X.x.e.now y + 1) (n : Nat) :
    (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq (flS P win usb sreq isArm edge kt A0)
        kt a A0.X).x.e.ts y + gsumBA P win usb sreq isArm edge kt A0 y gA a n
      ≤ (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt (a + n) A0.X).x.e.ts y := by
  have h := ts_chainBA_ge P win usb sreq isArm edge kt A0 hedge hA h0a y gA a hwa hgw hge n
  rw [runBA_proj P win usb sreq isArm edge kt A0, runBA_proj P win usb sreq isArm edge kt A0] at h
  exact h

end

end JLane
