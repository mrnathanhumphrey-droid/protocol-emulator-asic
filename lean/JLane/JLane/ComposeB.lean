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

end JLane
