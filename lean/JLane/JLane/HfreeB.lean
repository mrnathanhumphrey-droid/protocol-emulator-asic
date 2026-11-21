import JLane.ComposeB
import JLane.GapRunT
/-!
# Brick C3h — L4 `hfree` on a stretch (`slot_on_composition`, Wilson 11-19 / 11-21)

`RespWinB.wb_bound_winBK_fl` takes `hfree`: every writeback of `y` at least two cycles before
writeback `t` came before `t`'s release. `ComposeB.hR_stretch` carried it as a premise. Here it is
discharged on a stretch, by strong induction over the stretch's writebacks:

* **inside the stretch** the release is drift-free: a writeback at `x` moves `y`'s release by its
  gap (`GapRunT.ts_gapT`, `gpT = dly + ext`), and the induction's own bound puts that writeback
  at most `K + 1` past its release; `HrelS` (ArmClose's `hrel` form, for a writeback with a later
  one in the stretch) then puts it before the release it opens, and so before every later one.
  `HrelS` holds by a gap of at least `K + 2` (`hrel_of_gap`; the checker's `gap >= Rr + 3`,
  `Rr = K - 1`, lane-cert check 22) or, for an ARM, vacuously: armed until its edge, which
  flushes `y` and ends the stretch (on the bridged run: owed);
* **before the stretch** (`hpre`): the first stretch has nothing before it; after a flush at `f`
  the lane writes nothing back at `f + 1`, `f + 2` (`RestartB.no_wb_after_flush(2)`) and the
  restart's release is `now f + 1` (`restart_runBK`), so every earlier writeback is before it
  (`hpre_after_flush`).

Measured 11-21 (`hfree_measure`): every window-certified corpus image meets the gap condition on
every non-ARM writeback; the two that do not (pair_busy, uart_tx_busy) are certified by the EDF
scheme, whose own `hfree` is a separate item.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- **Before a restart stretch.** After a flush of `y` at `f`, every writeback of `y` before the
stretch's start `f + 3` came before the restart's release `now f + 1`. -/
theorem hpre_after_flush (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (f : Nat)
    (y : Lane)
    (hF0 : FlushOk P win usb sreq (fl (runBK P win usb sreq fl k f X0).x.e.now)
      (runBK P win usb sreq fl k f X0))
    (hfl : fl (runBK P win usb sreq fl k f X0).x.e.now y = true)
    (hts : (runBK P win usb sreq fl k (f + 3) X0).x.e.ts y
      = (runBK P win usb sreq fl k f X0).x.e.now + 1) :
    ∀ w, w < f + 3 → IsWB y (runBK P win usb sreq fl k w X0).x.e →
      (runBK P win usb sreq fl k w X0).x.e.now < (runBK P win usb sreq fl k (f + 3) X0).x.e.ts y := by
  intro w hw hwb
  have hnw := now_runBK P win usb sreq fl k w X0
  have hnf := now_runBK P win usb sreq fl k f X0
  rcases Nat.lt_or_ge f w with hlt | hle
  · exfalso
    rcases (show w = f + 1 ∨ w = f + 2 by omega) with rfl | rfl
    · have h1 := no_wb_after_flush P win usb sreq (fl (runBK P win usb sreq fl k f X0).x.e.now)
        (k (runBK P win usb sreq fl k f X0).x.e.now) (runBK P win usb sreq fl k f X0) y hF0 hfl
      rw [← runBK_succ' P win usb sreq fl k f X0] at h1
      exact h1 hwb
    · have h2 := no_wb_after_flush2 P win usb sreq (fl (runBK P win usb sreq fl k f X0).x.e.now)
        (fl (runBK P win usb sreq fl k (f + 1) X0).x.e.now)
        (k (runBK P win usb sreq fl k f X0).x.e.now)
        (k (runBK P win usb sreq fl k (f + 1) X0).x.e.now) (runBK P win usb sreq fl k f X0) y hF0 hfl
      rw [← runBK_succ' P win usb sreq fl k f X0, ← runBK_succ' P win usb sreq fl k (f + 1) X0] at h2
      exact h2 hwb
  · omega

/-- **`hrel` on a stretch** (`ArmClose.hrel_words`' form, on `runBK`): a writeback of `y` that
meets its bound (`K + 1` past its release) AND has a later writeback of `y` in the stretch lands
before the release it opens. Two ways it holds: a gap of at least `K + 2` (`hrel_of_gap`: every
non-ARM word the checker passes, lane-cert check 22), or vacuously -- an ARM's writeback has no
later one in its stretch (armed until its edge, and the edge flushes `y`; on the bridged run:
owed, step 3b). -/
def HrelS (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (y : Lane)
    (K s T : Nat) : Prop :=
  ∀ x x2, x < x2 → x2 < T → IsWB y (runBK P win usb sreq fl k (s + x) X0).x.e →
    IsWB y (runBK P win usb sreq fl k (s + x2) X0).x.e →
    (runBK P win usb sreq fl k (s + x) X0).x.e.now
      ≤ (runBK P win usb sreq fl k (s + x) X0).x.e.ts y + K + 1 →
    (runBK P win usb sreq fl k (s + x) X0).x.e.now
      < (runBK P win usb sreq fl k (s + x) X0).x.e.ts y
        + gpT P y (fun n => (runBK P win usb sreq fl k (s + n) X0).base) x

/-- **`hrel` from the gap**: every writeback's gap at least `K + 2` (`gap >= Rr + 3`). -/
theorem hrel_of_gap (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (y : Lane)
    (K s T : Nat)
    (hgap : ∀ x, x < T → IsWB y (runBK P win usb sreq fl k (s + x) X0).x.e →
      K + 2 ≤ gpT P y (fun n => (runBK P win usb sreq fl k (s + n) X0).base) x) :
    HrelS P win usb sreq fl k X0 y K s T := by
  intro x x2 hxx hx2 hwb _hwb2 hb
  have := hgap x (by omega) hwb
  omega

/-- **`hR` on a stretch, `hfree` discharged** (L4 hfree). `hR_stretch`'s premises less `hfree`,
plus `hpre` (writebacks before the stretch are before its release: `hpre_after_flush`, or vacuous
for the first stretch) and `hrel` (a writeback within its bound lands before the release it opens:
`hrel_of_gap` for gaps of at least `K + 2`; an ARM by its edge). Every writeback of the stretch
lands within `K + 1` of its release. -/
theorem hR_stretch_gap (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK)
    (h0 : X0.x.e.st = .idle) (h0ts : ∀ l, X0.x.e.now ≤ X0.x.e.ts l) (y : Lane)
    (hy : P.live y = true) (M S K : Nat) (hK : 3 * M + S + 3 ≤ K) (s T : Nat)
    (hT : TrajY P win usb sreq y (fun n => (runBK P win usb sreq fl k (s + n) X0).base) T)
    (hlastS : ∀ j, s ≤ j + 2 → j < s + T → fl (runBK P win usb sreq fl k j X0).x.e.now y = false)
    (hstart : X0.x.e.now + s ≤ (runBK P win usb sreq fl k s X0).x.e.ts y + 2)
    (hpre : ∀ w, w < s → IsWB y (runBK P win usb sreq fl k w X0).x.e →
      (runBK P win usb sreq fl k w X0).x.e.now < (runBK P win usb sreq fl k s X0).x.e.ts y)
    (hrel : HrelS P win usb sreq fl k X0 y K s T)
    (hM : ∀ c, c + K + 2 ≤ s + T →
      cntBK P win usb sreq fl k (fun e => decOther win y e = true) K
        (runBK P win usb sreq fl k c X0) ≤ M)
    (hS : ∀ c, c + K + 2 ≤ s + T →
      cntBK P win usb sreq fl k (fun e => noDecB win e = true) K
        (runBK P win usb sreq fl k c X0) ≤ S) :
    ∀ x, x < T → IsWB y (runBK P win usb sreq fl k (s + x) X0).x.e →
      (runBK P win usb sreq fl k (s + x) X0).x.e.now
        ≤ (runBK P win usb sreq fl k (s + x) X0).x.e.ts y + K + 1 := by
  intro x
  induction x using Nat.strongRecOn with
  | _ x ih =>
  intro hx hwb
  have hm := ts_monoT P win usb sreq y _ T hT 0 x (by omega)
  simp only [base_e, Nat.add_zero, Nat.zero_add] at hm
  exact wb_bound_winBK_fl P win usb sreq fl k X0 h0 h0ts y hy M S K hK (s + x) hwb
    (fun n hn hle => hlastS n (by
      have hn2 := now_runBK P win usb sreq fl k n X0
      omega) (by omega))
    (fun w hw hwbw => by
      rcases Nat.lt_or_ge w s with hws | hws
      · have := hpre w hws hwbw
        omega
      · obtain ⟨x', rfl⟩ : ∃ x', w = s + x' := ⟨w - s, by omega⟩
        have hb := ih x' (by omega) (by omega) hwbw
        have hg := hrel x' x (by omega) hx hwbw hwb hb
        have hgt := ts_gapT P win usb sreq y
          (fun n => (runBK P win usb sreq fl k (s + n) X0).base) T hT x' x
          (by simp only [base_e]; exact hwbw) (by omega) (by omega)
        simp only [base_e] at hgt
        omega)
    (fun c hc => hM c (by omega)) (fun c hc => hS c (by omega))

/-- **`hR_stretch` without `hfree`** (L4): `CertT.hR`'s form (`Rr = K - 1`) on every retirement
of the stretch, from `hR_stretch_gap`. -/
theorem hR_stretch_nofree (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK)
    (h0 : X0.x.e.st = .idle) (h0ts : ∀ l, X0.x.e.now ≤ X0.x.e.ts l) (y : Lane)
    (hy : P.live y = true) (M S K : Nat) (hK : 3 * M + S + 3 ≤ K) (s T : Nat)
    (hT : TrajY P win usb sreq y (fun n => (runBK P win usb sreq fl k (s + n) X0).base) T)
    (hlastS : ∀ j, s ≤ j + 2 → j < s + T → fl (runBK P win usb sreq fl k j X0).x.e.now y = false)
    (hstart : X0.x.e.now + s ≤ (runBK P win usb sreq fl k s X0).x.e.ts y + 2)
    (hpre : ∀ w, w < s → IsWB y (runBK P win usb sreq fl k w X0).x.e →
      (runBK P win usb sreq fl k w X0).x.e.now < (runBK P win usb sreq fl k s X0).x.e.ts y)
    (hrel : HrelS P win usb sreq fl k X0 y K s T)
    (hM : ∀ c, c + K + 2 ≤ s + T →
      cntBK P win usb sreq fl k (fun e => decOther win y e = true) K
        (runBK P win usb sreq fl k c X0) ≤ M)
    (hS : ∀ c, c + K + 2 ≤ s + T →
      cntBK P win usb sreq fl k (fun e => noDecB win e = true) K
        (runBK P win usb sreq fl k c X0) ≤ S) :
    ∀ x, x < T → IsRet P y ((fun n => (runBK P win usb sreq fl k (s + n) X0).base) x).e →
      ((fun n => (runBK P win usb sreq fl k (s + n) X0).base) x).e.now ≤
        ((fun n => (runBK P win usb sreq fl k (s + n) X0).base) x).e.ts y + (K - 1) + 2 := by
  intro x hx hret
  simp only [base_e] at hret ⊢
  have := hR_stretch_gap P win usb sreq fl k X0 h0 h0ts y hy M S K hK s T hT hlastS hstart hpre
    hrel hM hS x hx (isWB_of_ret P y _ hret)
  omega

end

end JLane
