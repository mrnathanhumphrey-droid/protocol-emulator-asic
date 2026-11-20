import JLane.RestartB
import JLane.FlushHeld
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

/-! ### L2: the first stretch (no flush of `y` yet)

`trajY_runBK_noflush` starts at `s ≥ 2`: a killed capture at `m + 2` is traced back to a flush at
`m` or `m + 1`. Cycles 0 and 1 have no two cycles behind them inside the run; they are covered by
the start having no kill pending (`X0.pkill = false`): at cycle 0 nothing is killed, and a killed
capture for `y` at cycle 1 would need the kill set at cycle 0 by a flush of `y`. -/

/-- **No killed capture for `y` at cycle 1**: the start has no kill pending and `y` is not flushed
at cycle 0. -/
theorem no_kill_one (fl0 : Lane → Bool) (k0 : Lane → Nat) (X : EngBK) (y : Lane)
    (hpk : X.pkill = false) (hf0 : fl0 y = false) :
    ¬((stepBKK P win usb sreq fl0 k0 X).kc = true ∧ (stepBKK P win usb sreq fl0 k0 X).x.e.pl = y)
    := by
  rintro ⟨hkc, hp⟩
  obtain ⟨hc, hk1⟩ := kc_spec _ hkc
  rw [pstK, stepB_pst] at hc
  rw [plK, stepB_pl] at hp
  obtain ⟨hwt, hpl⟩ := portNextB_cap_from P usb sreq X.base hc
  rw [base_e] at hwt hpl
  rw [hpl] at hp
  rw [pkillK, if_neg (by rw [hwt]; decide), hpk, hp, hf0] at hk1
  cases hk1

/-- **The first stretch.** From a start with no kill pending, well formed, over `T` cycles in which
`y` is never flushed: `runBK` from cycle 0 is a `TrajY` trajectory for `y`, well formed. With
both slots full at the start it is `GapRunT`'s `H0 = 2` start. -/
theorem stretch_first (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (hpk : X0.pkill = false) (y : Lane) (T : Nat)
    (hF : ∀ j, j < T → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hnf : ∀ j, j < T → fl (runBK P win usb sreq fl k j X0).x.e.now y = false) :
    TrajY P win usb sreq y (fun n => (runBK P win usb sreq fl k (0 + n) X0).base) T ∧
    (∀ n, n ≤ T → WfB ((fun n => (runBK P win usb sreq fl k (0 + n) X0).base) n)) := by
  refine ⟨?_, wfB_runBK P win usb sreq hok fl k X0 hI 0 T (fun j hj => hF j (by omega))⟩
  apply trajY_runBK P win usb sreq fl k X0 y 0 T
  intro n hn
  refine ⟨hnf (0 + n) (by omega), ?_⟩
  match n, hn with
  | 0, _ =>
    rintro ⟨hkc, -⟩
    have h0 : runBK P win usb sreq fl k (0 + 0) X0 = X0 := rfl
    rw [h0] at hkc
    rw [(kc_spec X0 hkc).2] at hpk
    cases hpk
  | 1, _ =>
    have h1 : runBK P win usb sreq fl k (0 + 1) X0
        = stepBKK P win usb sreq (fl X0.x.e.now) (k X0.x.e.now) X0 := rfl
    rw [h1]
    exact no_kill_one P win usb sreq _ _ X0 y hpk (hnf 0 (by omega))
  | m + 2, hm =>
    rintro ⟨hkc, hp⟩
    rw [show 0 + (m + 2) = m + 2 by omega] at hkc hp
    rcases kill_prov_runBK P win usb sreq hok fl k X0 hI m y
        (fun j hj => hF j (by omega)) hkc hp with h | h
    · rw [hnf (m + 1) (by omega)] at h; cases h
    · rw [hnf m (by omega)] at h; cases h

/-! ### L3: the head over a whole run

`CertT` bundles `GapRunT.head_late_gapT`'s certificate conditions along one stretch `τ` of horizon
`T` (the lateness condition `hlate` at the stretch's end `T`). `head_valid_runBK` cuts the run at
`y`'s last flush before `t` (`flush_cut`) and reads the head at `t` from the place `t` falls in:
the first stretch (`stretch_first`, `H0` given at the start), the restart window (`f + 1`: the
edge word, K1; `f + 2`: frozen), or the stretch from `f + 3` (`stretch_after_flush`, `H0 = 1`).
The certificate is asked only of the stretch that holds `t`; `Rr`, `Z`, `L` are whole-run
functions, read from the stretch's start. The edge word at each flush (`hedge`) is where the
flush-spacing contract K8 enters (`rtl_contracts.CONTRACT_PREMISES` flush_spacing). -/

/-- `head_late_gapT`'s certificate along `τ` up to `T`. -/
structure CertT (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) (y : Lane) (τ : Nat → EngB) (T B : Nat) (Rr Z L : Nat → Nat) :
    Prop where
  hR : ∀ x, x < T → IsRet P y (τ x).e → (τ x).e.now ≤ (τ x).e.ts y + Rr x + 2
  hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSumT P usb sreq y τ a m ≤ B
  hZ0 : ∀ x, x < T → IsRet P y (τ x).e → Rr x ≤ Z x
  hZF : ∀ x, x < T → IsRet P y (τ x).e → NpfAt y (τ x).e → Rr x + DSTAR + B ≤ Z x
  hZC : ∀ x x2, x2 < T → ConsecT P y τ x x2 → Z x + DSTAR + B ≤ rdT y τ x x2 + Z x2
  hZS0 : ∀ w0, w0 < T → IsRet P y (τ w0).e → cntT τ (fun z => IsRet P y z.e) w0 = 0 →
    (τ 0).held y = 1 → (τ 0).e.now + DSTAR + B ≤ (τ w0).e.ts y + Z w0 + 3
  hHD : ∀ x, x < T → IsRet P y (τ x).e → NpfAt y (τ x).e →
    Rr x + HEAD_SLACK + B ≤ gpT P y τ x + L x
  hHN : ∀ x x2, x2 < T → ConsecT P y τ x x2 →
    Z x + HEAD_SLACK + B ≤ rdT y τ x x2 + gpT P y τ x2 + L x2
  hHS0 : ∀ w0, w0 < T → IsRet P y (τ w0).e → cntT τ (fun z => IsRet P y z.e) w0 = 0 →
    (τ 0).held y = 1 → (τ 0).e.now + HEAD_SLACK + B ≤ (τ w0).e.ts y + gpT P y τ w0 + L w0 + 3
  hlate : ∀ x, x < T → IsRet P y (τ x).e →
    cntT τ (fun z => IsRet P y z.e) (x + 1) = cntT τ (fun z => IsRet P y z.e) T →
    (τ T).e.ts y + L x ≤ (τ T).e.now

/-- **The head at the end of a certified stretch** (`head_late_gapT` at `t = T`). -/
theorem head_of_cert (hok : SReqB P sreq) (y : Lane) (hy : P.live y = true) (τ : Nat → EngB)
    (T B : Nat) (Rr Z L : Nat → Nat) (hT : TrajY P win usb sreq y τ T)
    (hWf : ∀ n, n ≤ T → WfB (τ n)) (hH0 : (τ 0).held y = 1 ∨ (τ 0).held y = 2)
    (hC : CertT P win usb sreq y τ T B Rr Z L) : (τ T).e.headValid y = true :=
  head_late_gapT P win usb sreq y τ hok hy T hT hWf B Rr Z L hH0 hC.hR hC.hB hC.hZ0 hC.hZF
    hC.hZC hC.hZS0 hC.hHD hC.hHN hC.hHS0 T (Nat.le_refl T) hC.hlate

/-- **L3: the head over a whole run with flushes.** At any cycle `t` of `runBK`, `y`'s head is
valid, given the flush conditions before `t`, the edge word at each flush of `y` (K1; K8 behind
it), the start's words (`H0`), and the certificate on the stretch that holds `t`: from 0 when `y`
was never flushed before `t` (`hC0`), from `f + 3` when `f` is its last flush and `t ≥ f + 3`
(`hCf`). In the restart window `f + 1`, `f + 2` the head is the edge word, no certificate asked. -/
theorem head_valid_runBK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (hpk : X0.pkill = false) (y : Lane) (hy : P.live y = true)
    (t B : Nat) (Rr Z L : Nat → Nat)
    (hF : ∀ j, j < t → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hedge : ∀ f, f < t → fl (runBK P win usb sreq fl k f X0).x.e.now y = true →
      (runBK P win usb sreq fl k f X0).base.hasEdge y
        (k (runBK P win usb sreq fl k f X0).x.e.now y) = true)
    (hH0 : (runBK P win usb sreq fl k 0 X0).base.held y = 1 ∨
      (runBK P win usb sreq fl k 0 X0).base.held y = 2)
    (hC0 : (∀ j, j < t → fl (runBK P win usb sreq fl k j X0).x.e.now y = false) →
      CertT P win usb sreq y (fun n => (runBK P win usb sreq fl k (0 + n) X0).base) t B
        Rr Z L)
    (hCf : ∀ f, f + 3 ≤ t → fl (runBK P win usb sreq fl k f X0).x.e.now y = true →
      (∀ j, f < j → j < t → fl (runBK P win usb sreq fl k j X0).x.e.now y = false) →
      CertT P win usb sreq y (fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base)
        (t - (f + 3)) B (fun n => Rr (f + 3 + n)) (fun n => Z (f + 3 + n))
        (fun n => L (f + 3 + n))) :
    (runBK P win usb sreq fl k t X0).x.e.headValid y = true := by
  rcases flush_cut P win usb sreq fl k X0 y t with hnone | ⟨f, hft, hfl, hlast⟩
  · -- the first stretch
    obtain ⟨hT, hW⟩ := stretch_first P win usb sreq hok fl k X0 hI hpk y t hF hnone
    have h := head_of_cert P win usb sreq hok y hy _ t B Rr Z L hT hW hH0 (hC0 hnone)
    have e : (runBK P win usb sreq fl k (0 + t) X0) = runBK P win usb sreq fl k t X0 := by
      rw [Nat.zero_add]
    simp only [e, base_e] at h
    exact h
  · by_cases hw : t ≤ f + 2
    · -- the restart window
      have he := hedge f hft hfl
      rcases (show t = f + 1 ∨ t = f + 2 by omega) with rfl | rfl
      · obtain ⟨hv, -, -⟩ := edge_survives_flushK P win usb sreq _ _
          (runBK P win usb sreq fl k f X0) y hfl he
        rw [← runBK_succ' P win usb sreq fl k f X0] at hv
        exact hv
      · exact (restart_head_runBK P win usb sreq hok fl k X0 hI f y
          (fun j hj => hF j (by omega)) hfl he (hlast (f + 1) (by omega) (by omega))).2
    · -- the stretch from f + 3
      obtain ⟨hT, hW, hh, -⟩ := stretch_after_flush P win usb sreq hok fl k X0 hI f t y
        (by omega) hF hfl (hedge f hft hfl) hlast
      have h := head_of_cert P win usb sreq hok y hy _ (t - (f + 3)) B _ _ _ hT hW
        (Or.inl hh) (hCf f (by omega) hfl hlast)
      have e : (runBK P win usb sreq fl k (f + 3 + (t - (f + 3))) X0)
          = runBK P win usb sreq fl k t X0 := by
        rw [show f + 3 + (t - (f + 3)) = t by omega]
      simp only [e, base_e] at h
      exact h

/-! ### L4: `hR` on a stretch

`CertT.hR` (a retirement within `Rr + 2` of its release) from `RespWinB.wb_bound_winBK_fl` with
`Rr = K - 1`. Its "not flushed at or after the current release" is the stretch's: the release at
the stretch's start is at most 2 before its first cycle (`hstart`; the restart's release is
`f + 1` = `s - 2`, `hstart_after_flush`) and only moves forward along the trajectory, and `y` is
unflushed from `s - 2` on. What stays a premise: `hfree` (the release after the lane's earlier
writebacks -- a lateness condition, not a stretch fact) and the window budgets `hM` / `hS`
(owed: the window chain, `rtl_contracts.COMPOSITION`). -/

/-- **`hR` on a stretch from `s`.** -/
theorem hR_stretch (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK)
    (h0 : X0.x.e.st = .idle) (h0ts : ∀ l, X0.x.e.now ≤ X0.x.e.ts l) (y : Lane)
    (hy : P.live y = true) (M S K : Nat) (hK : 3 * M + S + 3 ≤ K) (s T : Nat)
    (hT : TrajY P win usb sreq y (fun n => (runBK P win usb sreq fl k (s + n) X0).base) T)
    (hlastS : ∀ j, s ≤ j + 2 → j < s + T → fl (runBK P win usb sreq fl k j X0).x.e.now y = false)
    (hstart : X0.x.e.now + s ≤ (runBK P win usb sreq fl k s X0).x.e.ts y + 2)
    (hfree : ∀ t, s ≤ t → t < s + T → IsWB y (runBK P win usb sreq fl k t X0).x.e →
      ∀ w, w + 2 < t → IsWB y (runBK P win usb sreq fl k w X0).x.e →
      (runBK P win usb sreq fl k w X0).x.e.now < (runBK P win usb sreq fl k t X0).x.e.ts y)
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
  have hm := ts_monoT P win usb sreq y _ T hT 0 x (by omega)
  simp only [base_e, Nat.add_zero, Nat.zero_add] at hm
  have hb := wb_bound_winBK_fl P win usb sreq fl k X0 h0 h0ts y hy M S K hK (s + x)
    (isWB_of_ret P y _ hret)
    (fun n hn hle => hlastS n (by
      have hn2 := now_runBK P win usb sreq fl k n X0
      omega) (by omega))
    (fun w hw hwb => hfree (s + x) (by omega) (by omega) (isWB_of_ret P y _ hret) w hw hwb)
    (fun c hc => hM c (by omega)) (fun c hc => hS c (by omega))
  omega

/-- **The restart's release meets `hstart`**: after a flush at `f`, the stretch from `f + 3`
starts with its release at `f + 1` (`restart_runBK`). -/
theorem hstart_after_flush (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (f : Nat) (y : Lane)
    (hF : ∀ j, j < f + 2 → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hfl : fl (runBK P win usb sreq fl k f X0).x.e.now y = true)
    (hedge : (runBK P win usb sreq fl k f X0).base.hasEdge y
      (k (runBK P win usb sreq fl k f X0).x.e.now y) = true)
    (h1 : fl (runBK P win usb sreq fl k (f + 1) X0).x.e.now y = false)
    (h2 : fl (runBK P win usb sreq fl k (f + 2) X0).x.e.now y = false) :
    X0.x.e.now + (f + 3) ≤ (runBK P win usb sreq fl k (f + 3) X0).x.e.ts y + 2 := by
  obtain ⟨-, -, -, hts, -⟩ := restart_runBK P win usb sreq hok fl k X0 hI f y hF hfl hedge h1 h2
  rw [base_e] at hts
  have hn := now_runBK P win usb sreq fl k f X0
  omega

end

/-! ### K8 proof (b), on the armed engine: no second flush within two cycles

On `FlushHeld.runBA` a flush is a hit (`armed ∧ now = armE`). The hit clears `armed` in its own
step, and a lane is armed again only at an ARM's retiring writeback -- which `y` cannot have the
cycle after its flush (`no_wb_after_flush`: an armed lane is not dispatched, `flushOk_hit`). So
`y` is unarmed at `f + 1` and `f + 2`, and cannot hit there. Premises: the armed invariant
(`ArmInvB`, kept by `armInvB_step` given `hedge`: an edge at least one cycle after its arming
writeback) and the scan fix (`ScanOk`). Not yet carried to `runBK` (the composition): `runBA`'s
dispatcher masks armed lanes, `runBK`'s is fixed (`rtl_contracts.COMPOSITION`). -/

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)

/-- **Two cycles after a hit, no hit.** -/
theorem no_rehit_two (k0 k1 : Lane → Nat) (A : EngBA) (y : Lane) (hA : ArmInvB A)
    (hscan : ScanOk P win usb sreq A) (hh : A.hit y = true) :
    (stepBA P win usb sreq isArm edge k0 A).hit y = false ∧
    (stepBA P win usb sreq isArm edge k1 (stepBA P win usb sreq isArm edge k0 A)).hit y = false
    := by
  have ha1 : (stepBA P win usb sreq isArm edge k0 A).armed y = false := by
    show (if A.hit y = true then false
      else if A.arms P isArm y = true then true else A.armed y) = false
    rw [if_pos hh]
  have hh1 : (stepBA P win usb sreq isArm edge k0 A).hit y = false := by
    unfold EngBA.hit; rw [ha1]; rfl
  refine ⟨hh1, ?_⟩
  -- no arming writeback of y the cycle after its flush
  have hF := flushOk_hit P win usb sreq A hA hscan
  have hnw := no_wb_after_flush P (winA win A.armed) usb sreq A.hit k0 A.X y hF hh
  have har : (stepBA P win usb sreq isArm edge k0 A).arms P isArm y = false := by
    unfold EngBA.arms
    cases hw : decide ((stepBA P win usb sreq isArm edge k0 A).X.x.e.st = .wb)
    · rfl
    · cases hc : decide (y = (stepBA P win usb sreq isArm edge k0 A).X.x.e.cur)
      · simp
      · simp only [decide_eq_true_eq] at hw hc
        exact absurd ⟨hw, hc.symm⟩ hnw
  have ha2 : (stepBA P win usb sreq isArm edge k1
      (stepBA P win usb sreq isArm edge k0 A)).armed y = false := by
    show (if (stepBA P win usb sreq isArm edge k0 A).hit y = true then false
      else if (stepBA P win usb sreq isArm edge k0 A).arms P isArm y = true then true
      else (stepBA P win usb sreq isArm edge k0 A).armed y) = false
    rw [hh1, har, ha1]; rfl
  unfold EngBA.hit; rw [ha2]; rfl

/-- The armed invariant along a run (`armInvB_step`). -/
theorem armInvB_runBA (hedge : ∀ t l, t + 1 ≤ edge t l) (kt : Nat → Lane → Nat) (A0 : EngBA)
    (hA : ArmInvB A0) : ∀ n, ArmInvB (runBA P win usb sreq isArm edge kt n A0)
  | 0 => hA
  | n + 1 => armInvB_step P win usb sreq isArm edge _ hedge _ (armInvB_runBA hedge kt A0 hA n)

/-- **K8 on the armed engine** (proof (b), Wilson 11-19): a lane flushed (hit) at cycle `n` of
`runBA` is not flushed at `n + 1` or `n + 2`. -/
theorem flush_spacing_runBA (hedge : ∀ t l, t + 1 ≤ edge t l) (kt : Nat → Lane → Nat)
    (A0 : EngBA) (hA : ArmInvB A0) (y : Lane) (n : Nat)
    (hscan : ScanOk P win usb sreq (runBA P win usb sreq isArm edge kt n A0))
    (hh : (runBA P win usb sreq isArm edge kt n A0).hit y = true) :
    (runBA P win usb sreq isArm edge kt (n + 1) A0).hit y = false ∧
    (runBA P win usb sreq isArm edge kt (n + 2) A0).hit y = false :=
  no_rehit_two P win usb sreq isArm edge _ _ (runBA P win usb sreq isArm edge kt n A0) y
    (armInvB_runBA P win usb sreq isArm edge hedge kt A0 hA n) hscan hh

end

/-! ### The bridge: the armed engine IS a `runBK` run

`runBA` steps `stepBKK` with the dispatcher `winA win armed` (armed lanes masked) and the flushes
`hit`, both read off the arm registers that cycle. `step` reads its dispatcher only on the current
engine (`dispNext`, `winqNext`), whose clock is `now₀ + n` at cycle `n`. So one fixed dispatcher
`winS` -- `winA win` with the arm registers of the cycle the engine's clock names -- and one
flush input `flS` by time make `runBA`'s engine exactly `runBK P winS usb sreq flS kt`
(`runBA_proj`). L1-L4 are stated for any `win` / `fl`, so they hold on the armed run with these;
`FlushOk` there comes from `flushOk_hit` (`flushOk_runBA`), and K8 from
`flush_spacing_runBA` (`flush_spacing_runBK`). -/

/-- `step` reads its dispatcher only on the engine it steps. -/
theorem step_win_eq (P : Program) (w1 w2 : Engine → Option Lane) (e : Engine)
    (h : w1 e = w2 e) : step P w1 e = step P w2 e := by
  rw [step_win_congr P w1 e, step_win_congr P w2 e, h]

section
variable (P : Program) (usb : Option Lane) (sreq : EngB → Option Lane)

theorem stepB_win_congr (w1 w2 : Engine → Option Lane) (x : EngB) (h : w1 x.e = w2 x.e) :
    stepB P w1 usb sreq x = stepB P w2 usb sreq x := by
  have hs := step_win_eq P w1 w2 x.e h
  simp only [stepB, hs]

theorem stepBKK_win_congr (w1 w2 : Engine → Option Lane) (fl : Lane → Bool) (k : Lane → Nat)
    (X : EngBK) (h : w1 X.x.e = w2 X.x.e) :
    stepBKK P w1 usb sreq fl k X = stepBKK P w2 usb sreq fl k X := by
  have hb := stepB_win_congr P usb sreq w1 w2 X.base (by rw [base_e]; exact h)
  simp only [stepBKK, hb]

theorem flushOk_win_congr (w1 w2 : Engine → Option Lane) (fl : Lane → Bool) (X : EngBK)
    (h : w1 X.x.e = w2 X.x.e) (hF : FlushOk P w2 usb sreq fl X) : FlushOk P w1 usb sreq fl X := by
  have hb := stepB_win_congr P usb sreq w1 w2 X.base (by rw [base_e]; exact h)
  unfold FlushOk at hF ⊢
  rw [hb]
  exact hF

end

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)
  (kt : Nat → Lane → Nat) (A0 : EngBA)

/-- The armed run's dispatcher, as one function of the engine: `winA win` with the arm registers
of the cycle the engine's clock names. -/
def winS : Engine → Option Lane := fun e =>
  winA win (runBA P win usb sreq isArm edge kt (e.now - A0.X.x.e.now) A0).armed e

/-- The armed run's flushes by time: the hits of that cycle. -/
def flS : Nat → Lane → Bool := fun t l =>
  (runBA P win usb sreq isArm edge kt (t - A0.X.x.e.now) A0).hit l

theorem now_runBA : ∀ n,
    (runBA P win usb sreq isArm edge kt n A0).X.x.e.now = A0.X.x.e.now + n
  | 0 => rfl
  | n + 1 => by
    show (stepBA P win usb sreq isArm edge _ (runBA P win usb sreq isArm edge kt n A0)).X.x.e.now
      = _
    rw [stepBA_now, now_runBA n]
    omega

/-- **The bridge**: the armed run's engine is `runBK` with `winS` / `flS`. -/
theorem runBA_proj : ∀ n, (runBA P win usb sreq isArm edge kt n A0).X =
    runBK P (winS P win usb sreq isArm edge kt A0) usb sreq (flS P win usb sreq isArm edge kt A0)
      kt n A0.X
  | 0 => rfl
  | n + 1 => by
    rw [runBK_succ', ← runBA_proj n]
    have hn := now_runBA P win usb sreq isArm edge kt A0 n
    have hfl : flS P win usb sreq isArm edge kt A0 (runBA P win usb sreq isArm edge kt n A0).X.x.e.now
        = (runBA P win usb sreq isArm edge kt n A0).hit := by
      funext l
      simp only [flS, hn, Nat.add_sub_cancel_left]
    have hw : winS P win usb sreq isArm edge kt A0 (runBA P win usb sreq isArm edge kt n A0).X.x.e
        = winA win (runBA P win usb sreq isArm edge kt n A0).armed
          (runBA P win usb sreq isArm edge kt n A0).X.x.e := by
      simp only [winS, hn, Nat.add_sub_cancel_left]
    rw [hfl, stepBKK_win_congr P usb sreq _ _ _ _ _ hw]
    rfl

/-- **`FlushOk` on the bridged run**, from the armed invariant and the scan fix. -/
theorem flushOk_runBA (hedge : ∀ t l, t + 1 ≤ edge t l) (hA : ArmInvB A0) (n : Nat)
    (hscan : ScanOk P win usb sreq (runBA P win usb sreq isArm edge kt n A0)) :
    FlushOk P (winS P win usb sreq isArm edge kt A0) usb sreq
      (flS P win usb sreq isArm edge kt A0
        (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt n A0.X).x.e.now)
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt n A0.X) := by
  rw [← runBA_proj P win usb sreq isArm edge kt A0 n]
  have hn := now_runBA P win usb sreq isArm edge kt A0 n
  have hfl : flS P win usb sreq isArm edge kt A0 (runBA P win usb sreq isArm edge kt n A0).X.x.e.now
      = (runBA P win usb sreq isArm edge kt n A0).hit := by
    funext l
    simp only [flS, hn, Nat.add_sub_cancel_left]
  rw [hfl]
  apply flushOk_win_congr P usb sreq _ (winA win (runBA P win usb sreq isArm edge kt n A0).armed)
  · simp only [winS, hn, Nat.add_sub_cancel_left]
  · exact flushOk_hit P win usb sreq _ (armInvB_runBA P win usb sreq isArm edge hedge kt A0 hA n)
      hscan

/-- **K8 on the bridged run** (proof (b) reaching the composition): `y` flushed at cycle `f` of
`runBK P winS usb sreq flS kt` is not flushed at `f + 1` or `f + 2`. -/
theorem flush_spacing_runBK (hedge : ∀ t l, t + 1 ≤ edge t l) (hA : ArmInvB A0) (y : Lane)
    (f : Nat) (hscan : ScanOk P win usb sreq (runBA P win usb sreq isArm edge kt f A0))
    (hfl : flS P win usb sreq isArm edge kt A0
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt f A0.X).x.e.now y = true) :
    flS P win usb sreq isArm edge kt A0
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt (f + 1) A0.X).x.e.now y = false ∧
    flS P win usb sreq isArm edge kt A0
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt (f + 2) A0.X).x.e.now y = false := by
  simp only [← runBA_proj P win usb sreq isArm edge kt A0, flS,
    now_runBA P win usb sreq isArm edge kt A0, Nat.add_sub_cancel_left] at hfl ⊢
  exact flush_spacing_runBA P win usb sreq isArm edge hedge kt A0 hA y f hscan hfl

/-! ### `hedge` on the bridged run: the edge word present at every flush

A hit of `y` at `f` has an arming: the last arming writeback `t₀ < f` (from an unarmed start; a
lane armed is never dispatched, so never re-armed before its hit), with `armE = edge t₀`. From
`t₀`, `FlushHeld.edge_held_at_edge` holds the edge word to the edge cycle `f`. What stays a
premise, per arming (`hword`): at the arming writeback the word with the edge's fetch index is
held or arriving unkilled, and is not the ARM itself -- K1's content (the edge word fetched in
time, `FlushHeld`). -/

theorem runBA_add (m : Nat) : ∀ n, runBA P win usb sreq isArm edge kt (m + n) A0 =
    runBA P win usb sreq isArm edge kt n (runBA P win usb sreq isArm edge kt m A0)
  | 0 => rfl
  | n + 1 => by
    show stepBA P win usb sreq isArm edge
        (kt (runBA P win usb sreq isArm edge kt (m + n) A0).X.x.e.now)
        (runBA P win usb sreq isArm edge kt (m + n) A0) =
      stepBA P win usb sreq isArm edge
        (kt (runBA P win usb sreq isArm edge kt n
          (runBA P win usb sreq isArm edge kt m A0)).X.x.e.now)
        (runBA P win usb sreq isArm edge kt n (runBA P win usb sreq isArm edge kt m A0))
    rw [runBA_add m n]

/-- BufEng's invariant with the kill, along the armed run. -/
theorem wfBK_runBA (hok : SReqB P sreq) (hedge : ∀ t l, t + 1 ≤ edge t l) (hI : WfBK A0.X)
    (hA : ArmInvB A0) (hscan : ∀ n, ScanOk P win usb sreq (runBA P win usb sreq isArm edge kt n A0)) :
    ∀ n, WfBK (runBA P win usb sreq isArm edge kt n A0).X
  | 0 => hI
  | n + 1 => wfBK_step P (winA win _) usb sreq _ _ hok _ (wfBK_runBA hok hedge hI hA hscan n)
      (flushOk_hit P win usb sreq _ (armInvB_runBA P win usb sreq isArm edge hedge kt A0 hA n)
        (hscan n))

/-- **Where an armed lane was armed.** From an unarmed start, a lane armed at cycle `n` was armed
at a writeback `t₀ < n`, and its edge register still holds that arming's edge. -/
theorem armed_origin (h0 : ∀ l, A0.armed l = false) (y : Lane) : ∀ n,
    (runBA P win usb sreq isArm edge kt n A0).armed y = true →
    ∃ t0, t0 < n ∧ (runBA P win usb sreq isArm edge kt t0 A0).arms P isArm y = true ∧
      (runBA P win usb sreq isArm edge kt n A0).armE y =
        edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y
  | 0, ha => by
    have : A0.armed y = true := ha
    rw [h0 y] at this
    cases this
  | n + 1, ha => by
    have ha' : (if (runBA P win usb sreq isArm edge kt n A0).hit y = true then false
        else if (runBA P win usb sreq isArm edge kt n A0).arms P isArm y = true then true
        else (runBA P win usb sreq isArm edge kt n A0).armed y) = true := ha
    by_cases hh : (runBA P win usb sreq isArm edge kt n A0).hit y = true
    · rw [if_pos hh] at ha'; cases ha'
    · rw [if_neg hh] at ha'
      by_cases har : (runBA P win usb sreq isArm edge kt n A0).arms P isArm y = true
      · refine ⟨n, by omega, har, ?_⟩
        show (if (runBA P win usb sreq isArm edge kt n A0).arms P isArm y = true
          then edge (runBA P win usb sreq isArm edge kt n A0).X.x.e.now y
          else (runBA P win usb sreq isArm edge kt n A0).armE y) = _
        rw [if_pos har]
      · rw [if_neg har] at ha'
        obtain ⟨t0, ht, hat, hae⟩ := armed_origin h0 y n ha'
        refine ⟨t0, by omega, hat, ?_⟩
        show (if (runBA P win usb sreq isArm edge kt n A0).arms P isArm y = true
          then edge (runBA P win usb sreq isArm edge kt n A0).X.x.e.now y
          else (runBA P win usb sreq isArm edge kt n A0).armE y) = _
        rw [if_neg har, hae]

/-- **`hedge` on the bridged run.** From an unarmed, well-formed start, under the scan fix and
the edge timing: at every flush of `y` on `runBK P winS usb sreq flS kt`, `y` holds its edge word
-- ComposeB's `hedge` -- given `hword` at each arming of `y`. -/
theorem hedge_runBK (hok : SReqB P sreq) (hedge : ∀ t l, t + 1 ≤ edge t l) (hI : WfBK A0.X)
    (hA : ArmInvB A0) (h0 : ∀ l, A0.armed l = false)
    (hscan : ∀ n, ScanOk P win usb sreq (runBA P win usb sreq isArm edge kt n A0)) (y : Lane)
    (hword : ∀ t0, (runBA P win usb sreq isArm edge kt t0 A0).arms P isArm y = true →
      ((runBA P win usb sreq isArm edge kt t0 A0).X.base.holds y
          (kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y) = true ∨
        ((runBA P win usb sreq isArm edge kt t0 A0).X.base.inCap y
            (kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y) = true ∧
          (runBA P win usb sreq isArm edge kt t0 A0).X.pkill = false)) ∧
      (runBA P win usb sreq isArm edge kt t0 A0).X.base.inSlot y
          (kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y)
          ((runBA P win usb sreq isArm edge kt t0 A0).X.base.e.sel y) = false)
    (f : Nat)
    (hfl : flS P win usb sreq isArm edge kt A0
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt f A0.X).x.e.now y = true) :
    (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt f A0.X).base.hasEdge y
      (kt (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt f A0.X).x.e.now y) = true := by
  have hp := runBA_proj P win usb sreq isArm edge kt A0 f
  have hn := now_runBA P win usb sreq isArm edge kt A0 f
  rw [← hp]
  rw [← hp] at hfl
  simp only [flS, hn, Nat.add_sub_cancel_left] at hfl
  -- the hit: armed, at its edge
  have hfl' := hfl
  unfold EngBA.hit at hfl'
  simp only [Bool.and_eq_true, decide_eq_true_eq] at hfl'
  obtain ⟨ha, hnow⟩ := hfl'
  obtain ⟨t0, ht0, harm, hae⟩ := armed_origin P win usb sreq isArm edge kt A0 h0 y f ha
  have hn0 := now_runBA P win usb sreq isArm edge kt A0 t0
  have hef : edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y = A0.X.x.e.now + f := by
    rw [← hae, ← hnow, hn]
  obtain ⟨hh, hnh⟩ := hword t0 harm
  have hscan' : ∀ n, ScanOk P win usb sreq
      (runBA P win usb sreq isArm edge kt n (runBA P win usb sreq isArm edge kt t0 A0)) := by
    intro n
    rw [← runBA_add]
    exact hscan (t0 + n)
  obtain ⟨-, -, hheld, -⟩ := edge_held_at_edge P win usb sreq isArm edge hok hedge kt
    (runBA P win usb sreq isArm edge kt t0 A0) y _
    (wfBK_runBA P win usb sreq isArm edge kt A0 hok hedge hI hA hscan t0)
    (armInvB_runBA P win usb sreq isArm edge hedge kt A0 hA t0) harm hh hnh hscan' (f - t0)
    (by omega) (by rw [hef, hn0]; omega)
  rw [← runBA_add, show t0 + (f - t0) = f by omega, hef] at hheld
  rw [hn]
  exact holds_hasEdge _ y _ hheld

end

#print axioms last_true
#print axioms flush_cut
#print axioms restart_head_12
#print axioms restart_head_runBK
#print axioms stretch_after_flush
#print axioms no_kill_one
#print axioms stretch_first
#print axioms head_of_cert
#print axioms head_valid_runBK
#print axioms hR_stretch
#print axioms hstart_after_flush
#print axioms no_rehit_two
#print axioms armInvB_runBA
#print axioms flush_spacing_runBA
#print axioms step_win_eq
#print axioms stepB_win_congr
#print axioms stepBKK_win_congr
#print axioms flushOk_win_congr
#print axioms now_runBA
#print axioms runBA_proj
#print axioms flushOk_runBA
#print axioms flush_spacing_runBK
#print axioms runBA_add
#print axioms wfBK_runBA
#print axioms armed_origin
#print axioms hedge_runBK

end JLane
