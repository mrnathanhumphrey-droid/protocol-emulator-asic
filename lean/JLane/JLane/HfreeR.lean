import JLane.HfreeB
/-!
# Brick C3d — `hnf` and `hfree` in run coordinates (`slot_on_composition`, closure step 3)

`RespWinB.wb_bound_winBK_fl` takes, at a writeback `t` of `y`:

* `hnf` — `y` is not flushed at a cycle `n < t` at or past `t`'s release. This holds on every
  `runBK`, with no premise: a flush at `n` sets `y`'s release to `now n + 1` (`ts_flush_stepBK`),
  and from there it never drops below that -- a later flush sets it later still, an unflushed
  cycle only moves it forward (`ts_after_flushBK`). So `ts t ≥ now n + 1` (`hnf_runBK`).
* `hfree` — every writeback `w` of `y` with `w + 2 < t` came before `t`'s release. In
  `HfreeB.hR_stretch_gap` this was proved on a stretch; here it is in run coordinates, the form
  `wb_closeBK`'s strong induction over time needs (`hfree_runBK`): a flush of `y` in `[w, t)` puts
  `t`'s release past it; with none, `HrelR` (a writeback within its bound, with a later one and no
  flush between, lands before the release it opens -- `RespClose.wb_close`'s `hrel`, restricted
  as `HfreeB.HrelS` is) and monotonicity give it.

`HrelR` on the bridged run (`hrelR_bridged`): an ARM's writeback has no later writeback of `y`
before a flush (armed until a hit, a hit is a flush, `winA` never picks an armed lane), so it holds
vacuously there; every other writeback by its gap (`K + 2 ≤ dly + ext`, lane-cert check 22).
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- A flush of `y` sets its release to the next cycle. -/
theorem ts_flush_stepBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X : EngBK) (n : Nat)
    (y : Lane) (hf : fl (runBK P win usb sreq fl k n X).x.e.now y = true) :
    (runBK P win usb sreq fl k (n + 1) X).x.e.ts y = (runBK P win usb sreq fl k n X).x.e.now + 1 := by
  rw [runBK_succ']
  show (if fl (runBK P win usb sreq fl k n X).x.e.now y = true
      then (runBK P win usb sreq fl k n X).base.e.now + 1
      else (stepB P win usb sreq (runBK P win usb sreq fl k n X).base).e.ts y) = _
  rw [if_pos hf, base_e]

/-- **After a flush, the release stays past it**, whatever follows. -/
theorem ts_after_flushBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X : EngBK) (n : Nat)
    (y : Lane) (hf : fl (runBK P win usb sreq fl k n X).x.e.now y = true) :
    ∀ d, (runBK P win usb sreq fl k n X).x.e.now + 1
      ≤ (runBK P win usb sreq fl k (n + 1 + d) X).x.e.ts y
  | 0 => by
    have := ts_flush_stepBK P win usb sreq fl k X n y hf
    show _ ≤ (runBK P win usb sreq fl k (n + 1) X).x.e.ts y
    omega
  | d + 1 => by
    have ih := ts_after_flushBK fl k X n y hf d
    have hn := now_runBK P win usb sreq fl k n X
    have hn2 := now_runBK P win usb sreq fl k (n + 1 + d) X
    rw [show n + 1 + (d + 1) = n + 1 + d + 1 by omega]
    cases hf2 : fl (runBK P win usb sreq fl k (n + 1 + d) X).x.e.now y with
    | false =>
      rw [runBK_succ']
      exact Nat.le_trans ih (ts_step_leBK P win usb sreq _ _ _ y hf2)
    | true =>
      have := ts_flush_stepBK P win usb sreq fl k X (n + 1 + d) y hf2
      omega

/-- **`hnf` on every `runBK`**: no flush of `y` before `t` at or past `t`'s release. -/
theorem hnf_runBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (y : Lane)
    (t : Nat) :
    ∀ n, n < t → (runBK P win usb sreq fl k t X0).x.e.ts y ≤ (runBK P win usb sreq fl k n X0).x.e.now →
      fl (runBK P win usb sreq fl k n X0).x.e.now y = false := by
  intro n hn hle
  cases hf : fl (runBK P win usb sreq fl k n X0).x.e.now y with
  | false => rfl
  | true =>
    exfalso
    have := ts_after_flushBK P win usb sreq fl k X0 n y hf (t - n - 1)
    rw [show n + 1 + (t - n - 1) = t by omega] at this
    omega

/-- Over a span from `w`: either `y` is unflushed throughout, or its release at the end is past
`now w` (a flush in the span, and `ts_after_flushBK`). Constructive, by induction on the span. -/
theorem flush_or_clearBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (y : Lane)
    (w : Nat) : ∀ d,
    (∀ j, w ≤ j → j < w + d → fl (runBK P win usb sreq fl k j X0).x.e.now y = false) ∨
      (runBK P win usb sreq fl k w X0).x.e.now + 1 ≤ (runBK P win usb sreq fl k (w + d) X0).x.e.ts y
  | 0 => Or.inl (fun j h1 h2 => absurd h2 (by omega))
  | d + 1 => by
    have hnw := now_runBK P win usb sreq fl k w X0
    have hnd := now_runBK P win usb sreq fl k (w + d) X0
    rw [show w + (d + 1) = w + d + 1 by omega]
    rcases flush_or_clearBK fl k X0 y w d with hc | hp
    · cases hf : fl (runBK P win usb sreq fl k (w + d) X0).x.e.now y with
      | false =>
        left
        intro j h1 h2
        rcases Nat.lt_or_ge j (w + d) with hlt | hge
        · exact hc j h1 hlt
        · rw [show j = w + d by omega]; exact hf
      | true =>
        right
        have := ts_flush_stepBK P win usb sreq fl k X0 (w + d) y hf
        omega
    · right
      cases hf : fl (runBK P win usb sreq fl k (w + d) X0).x.e.now y with
      | false =>
        rw [runBK_succ']
        exact Nat.le_trans hp (ts_step_leBK P win usb sreq _ _ _ y hf)
      | true =>
        have := ts_flush_stepBK P win usb sreq fl k X0 (w + d) y hf
        omega

/-- **`hrel` in run coordinates**: a writeback of `y` within its bound, with a later writeback of
`y` and no flush of `y` between, lands before the release it opens. -/
def HrelR (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (y : Lane) (K : Nat) :
    Prop :=
  ∀ x x2, x < x2 → IsWB y (runBK P win usb sreq fl k x X0).x.e →
    IsWB y (runBK P win usb sreq fl k x2 X0).x.e →
    (∀ j, x ≤ j → j < x2 → fl (runBK P win usb sreq fl k j X0).x.e.now y = false) →
    (runBK P win usb sreq fl k x X0).x.e.now ≤ (runBK P win usb sreq fl k x X0).x.e.ts y + K + 1 →
    (runBK P win usb sreq fl k x X0).x.e.now < (runBK P win usb sreq fl k (x + 1) X0).x.e.ts y

/-- **`hfree` in run coordinates**: given the bound on every earlier writeback of `y` (the
closure's induction) and `HrelR`, every writeback of `y` two or more cycles before writeback `t`
came before `t`'s release. -/
theorem hfree_runBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (y : Lane)
    (K t : Nat) (hwb : IsWB y (runBK P win usb sreq fl k t X0).x.e)
    (hrel : HrelR P win usb sreq fl k X0 y K)
    (hb : ∀ w, w < t → IsWB y (runBK P win usb sreq fl k w X0).x.e →
      (runBK P win usb sreq fl k w X0).x.e.now ≤ (runBK P win usb sreq fl k w X0).x.e.ts y + K + 1) :
    ∀ w, w + 2 < t → IsWB y (runBK P win usb sreq fl k w X0).x.e →
      (runBK P win usb sreq fl k w X0).x.e.now < (runBK P win usb sreq fl k t X0).x.e.ts y := by
  intro w hw hwbw
  have hnw := now_runBK P win usb sreq fl k w X0
  rcases flush_or_clearBK P win usb sreq fl k X0 y w (t - w) with hnf | hpast
  · have hnf' : ∀ j, w ≤ j → j < t → fl (runBK P win usb sreq fl k j X0).x.e.now y = false :=
      fun j h1 h2 => hnf j h1 (by omega)
    have h1 := hrel w t (by omega) hwbw hwb hnf' (hb w (by omega) hwbw)
    have h2 := ts_mono_winBK P win usb sreq fl k y X0 (w + 1) (t - (w + 1))
      (fun s hs => hnf' (w + 1 + s) (by omega) (by omega))
    rw [show w + 1 + (t - (w + 1)) = t by omega] at h2
    omega
  · rw [show w + (t - w) = t by omega] at hpast
    omega

end

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)
  (kt : Nat → Lane → Nat) (A0 : EngBA)

/-- **`HrelR` on the bridged run**: an ARM's retiring writeback has no later writeback of `y`
before a flush, so it holds vacuously there; every other writeback by its gap (`hgap`: non-ARM
words, lane-cert check 22). -/
theorem hrelR_bridged (hedge : ∀ t l, t + 1 ≤ edge t l) (hA : ArmInvB A0)
    (h0 : A0.X.x.e.st = .idle) (y : Lane) (K : Nat)
    (hgap : ∀ x,
      IsWB y (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt x A0.X).x.e →
      (runBA P win usb sreq isArm edge kt x A0).arms P isArm y = false →
      K + 2 ≤ P.dly y + P.ext (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt x A0.X).x.e.now y) :
    HrelR P (winS P win usb sreq isArm edge kt A0) usb sreq (flS P win usb sreq isArm edge kt A0)
      kt A0.X y K := by
  intro x x2 hxx hwb hwb2 hnf hb
  cases harm : (runBA P win usb sreq isArm edge kt x A0).arms P isArm y with
  | false =>
    have hg := hgap x hwb harm
    have ht := ts_wb_bridged P win usb sreq isArm edge kt A0 x y hwb (hnf x (Nat.le_refl x) hxx)
    omega
  | true =>
    exfalso
    obtain ⟨D, hD, hdec⟩ := wb_backBK P (winS P win usb sreq isArm edge kt A0) usb sreq
      (flS P win usb sreq isArm edge kt A0) kt A0.X h0 x2 y hwb2
    -- the decision is after the ARM's writeback: not at it (idle vs wb), not the cycle before
    -- (that decision drives at x, not a writeback)
    have hD1 : x + 1 ≤ D := by
      rcases Nat.lt_or_ge D (x + 1) with hlt | hge
      · exfalso
        rcases (show D = x ∨ D + 1 = x by omega) with hEq | hEq
        · rw [hEq] at hdec
          have h1 := hdec.1
          rw [hwb.1] at h1
          cases h1
        · have hdr : (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
              (flS P win usb sreq isArm edge kt A0) kt (D + 1) A0.X).x.e.st = .drive := by
            rw [runBK_succ', stepBKK_st]
            exact (step_of_dec P (winS P win usb sreq isArm edge kt A0) _ y hdec).1
          rw [hEq, hwb.1] at hdr
          cases hdr
      · exact hge
    have ha := armed_after_arm P win usb sreq isArm edge kt A0 hedge hA y x harm
      (D - (x + 1)) (fun j hj => by
        rw [← flS_runBK P win usb sreq isArm edge kt A0]
        exact hnf (x + 1 + j) (by omega) (by omega))
    rw [show x + 1 + (D - (x + 1)) = D by omega] at ha
    exact arm_no_dec P win usb sreq isArm edge kt A0 D y ha hdec

end

end JLane
