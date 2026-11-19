import JLane.TrajB
/-!
# Brick C3e — the per-retirement certificate along a trajectory, from any start
(`slot_on_composition`, step 3b)

`GapRunB.pending_bound_gapB` / `head_late_gapB` along an abstract trajectory `τ` (`TrajB.TrajY`),
from a start holding `H0` words: `H0 = 2` is BufEng's start (both slots full); `H0 = 1` is the
restart after a FALLTHROUGH flush (Wilson 11-18): the lane holds its edge word and owes a refill
**from the start cycle**.

The start is a retirement at cycle `now₀ - 3` in GapRun's terms: its refill, if wanted, is captured
by `now₀ + 22 + B` (`window_leT`); behind a no-prefetch edge word it is deferred to the first
retirement (`pb_defer_gT`). Two certificate conditions carry it, for the first retirement `w₀`
when `H0 = 1` -- they are GapRun's `hZC` and `hHN` with `ts + Z = now₀ - 3` at the start:
* `hZS0`: `now₀ + D* + B ≤ ts w₀ + Z w₀ + 3`;
* `hHS0`: `now₀ + 26 + B ≤ ts w₀ + gp w₀ + L w₀ + 3`.
Every other condition is GapRun's (`hZ0`, `hZF`, `hZC`, `hHD`, `hHN`), read along `τ`.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (y : Lane) (τ : Nat → EngB)

/-- The release gap a writeback of `y` at cycle `x` of `τ` opens. -/
def gpT (x : Nat) : Nat := P.dly y + P.ext (τ x).e.now y

/-- How far `y`'s release moved from `x` to `x2` along `τ`. -/
def rdT (x x2 : Nat) : Nat := (τ x2).e.ts y - (τ x).e.ts y

/-- Consecutive retirements of `y` along `τ`. -/
def ConsecT (x x2 : Nat) : Prop :=
  x < x2 ∧ IsRet P y (τ x).e ∧ IsRet P y (τ x2).e ∧
    cntT τ (fun z => IsRet P y z.e) x2 = cntT τ (fun z => IsRet P y z.e) x + 1

theorem rdT_eq (T : Nat) (hT : TrajY P win usb sreq y τ T) (x x2 : Nat) (h : x ≤ x2) (h2 : x2 ≤ T) :
    (τ x).e.ts y + rdT y τ x x2 = (τ x2).e.ts y := by
  have := ts_monoT P win usb sreq y τ T hT x (x2 - x) (by omega)
  rw [show x + (x2 - x) = x2 by omega] at this
  unfold rdT
  omega

theorem ts_gapT (T : Nat) (hT : TrajY P win usb sreq y τ T) (x z : Nat) (hw : IsWB y (τ x).e)
    (hxz : x < z) (hz : z ≤ T) :
    (τ x).e.ts y + gpT P y τ x ≤ (τ z).e.ts y := by
  have h1 := ts_after_wbT P win usb sreq y τ T hT x (by omega) hw
  have h2 := ts_monoT P win usb sreq y τ T hT (x + 1) (z - (x + 1)) (by omega)
  rw [show x + 1 + (z - (x + 1)) = z by omega] at h2
  unfold gpT
  omega

/-! ### The deferred case -/

theorem pb_defer_gT (hok : SReqB P sreq) (hy : P.live y = true) (T : Nat)
    (hT : TrajY P win usb sreq y τ T) (hWf : ∀ n, n ≤ T → WfB (τ n)) (B : Nat) (Rr : Nat → Nat)
    (s w2 t : Nat)
    (hRw : (τ w2).e.now ≤ (τ w2).e.ts y + Rr w2 + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSumT P usb sreq y τ a m ≤ B)
    (hs : s ≤ w2) (hw2t : w2 < t) (htT : t ≤ T)
    (ho : 1 ≤ (τ s).e.owed y) (hw : (τ s).e.wantFetch y = false) (hb : (τ s).buf y = false)
    (hr2 : IsRet P y (τ w2).e)
    (hnr : cntT τ (fun z => IsRet P y z.e) s = cntT τ (fun z => IsRet P y z.e) w2)
    (hnh : cntT τ (fun z => Hit y z.e) s = cntT τ (fun z => Hit y z.e) t) :
    NpfAt y (τ w2).e ∧ (τ 0).e.now + t ≤ (τ w2).e.ts y + Rr w2 + PENDING_SLACK + B := by
  have hPS : PENDING_SLACK = 25 := pending_slack_val
  have hold := npf_holdT P win usb sreq y τ T hT s ho hw hb (w2 - s) (by omega) (fun i hi =>
    ⟨no_event_betweenT τ (fun z => Hit y z.e) s t (s + i) (by omega) (by omega) hnh,
     no_event_betweenT τ (fun z => IsRet P y z.e) s w2 (s + i) (by omega) (by omega) hnr⟩)
  rw [show s + (w2 - s) = w2 by omega] at hold
  obtain ⟨hho, hhw, hhb⟩ := hold
  have hnh2 : ¬Hit y (τ w2).e := no_event_betweenT τ (fun z => Hit y z.e) s t w2 hs hw2t hnh
  obtain ⟨hwant, hbuf, hnpf⟩ :=
    npf_unlockT P win usb sreq y τ T hT w2 (by omega) hho hhw hnh2 hhb hr2
  refine ⟨hnpf, ?_⟩
  have hm1 := cntT_mono τ (fun z => Hit y z.e) s (w2 + 1) (by omega)
  have hm2 := cntT_mono τ (fun z => Hit y z.e) (w2 + 1) t (by omega)
  have hn := window_leT P win usb sreq y τ hok hy T hT hWf (w2 + 1) B (t - (w2 + 1)) (by omega)
    hwant hbuf (fun m hm hm' => hB (w2 + 1) m (by omega) hm')
    (fun i hi => no_event_betweenT τ (fun z => Hit y z.e) (w2 + 1) t (w2 + 1 + i) (by omega)
      (by omega) (by omega))
  have hnow := now_T P win usb sreq y τ T hT w2 (by omega)
  omega

/-! ### The start's refill (`H0 = 1`) -/

/-- **The refill owed from the start.** Holding one word at the start, with no capture by `t`
and the first retirement at `w2 < t`: deferred past a no-prefetch head to `w2`, or `t` within one
port wait of the start. -/
theorem pending_startT (hok : SReqB P sreq) (hy : P.live y = true) (T : Nat)
    (hT : TrajY P win usb sreq y τ T) (hWf : ∀ n, n ≤ T → WfB (τ n)) (B : Nat) (Rr : Nat → Nat)
    (h1 : (τ 0).held y = 1)
    (hR : ∀ x, x < T → IsRet P y (τ x).e → (τ x).e.now ≤ (τ x).e.ts y + Rr x + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSumT P usb sreq y τ a m ≤ B)
    (t w2 : Nat) (htT : t ≤ T) (hw2t : w2 < t)
    (hw2k : cntT τ (fun z => IsRet P y z.e) w2 = 0) (hw2b : IsRet P y (τ w2).e)
    (hh : cntT τ (fun z => Hit y z.e) t = 0) :
    (NpfAt y (τ w2).e ∧ (τ 0).e.now + t ≤ (τ w2).e.ts y + Rr w2 + PENDING_SLACK + B) ∨
      t ≤ 22 + B := by
  obtain ⟨hb, ho⟩ := held_le_one _ (hWf 0 (by omega)) y (by omega)
  cases hwant : (τ 0).e.wantFetch y with
  | true =>
    right
    exact window_leT P win usb sreq y τ hok hy T hT hWf 0 B t (by omega) hwant hb
      (fun m hm hm' => hB 0 m (by omega) hm')
      (fun i hi => no_event_betweenT τ (fun z => Hit y z.e) 0 t (0 + i) (by omega) (by omega)
        (by simp [cntT, hh]))
  | false =>
    left
    exact pb_defer_gT P win usb sreq y τ hok hy T hT hWf B Rr 0 w2 t (hR w2 (by omega) hw2b) hB
      (by omega) hw2t htT ho hwant hb hw2b (by simp [cntT, hw2k]) (by simp [cntT, hh])

/-! ### The pending bound -/

/-- **The pending bound along a trajectory, from a start of `H0` words.** The refill owed from
retirement `#k` at `w` (capture `#(k + 2 - H0)`), still pending at `t` after retirement `#(k+1)`
at `w2`: deferred past a no-prefetch head (bound against `w2`), or within the certificate
`Z w`. -/
theorem pending_bound_gapT (hok : SReqB P sreq) (hy : P.live y = true) (T : Nat)
    (hT : TrajY P win usb sreq y τ T) (hWf : ∀ n, n ≤ T → WfB (τ n)) (B : Nat) (Rr Z : Nat → Nat)
    (hH0 : (τ 0).held y = 1 ∨ (τ 0).held y = 2)
    (hR : ∀ x, x < T → IsRet P y (τ x).e → (τ x).e.now ≤ (τ x).e.ts y + Rr x + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSumT P usb sreq y τ a m ≤ B)
    (hZ0 : ∀ x, x < T → IsRet P y (τ x).e → Rr x ≤ Z x)
    (hZF : ∀ x, x < T → IsRet P y (τ x).e → NpfAt y (τ x).e → Rr x + DSTAR + B ≤ Z x)
    (hZC : ∀ x x2, x2 < T → ConsecT P y τ x x2 → Z x + DSTAR + B ≤ rdT y τ x x2 + Z x2)
    (hZS0 : ∀ w0, w0 < T → IsRet P y (τ w0).e → cntT τ (fun z => IsRet P y z.e) w0 = 0 →
      (τ 0).held y = 1 → (τ 0).e.now + DSTAR + B ≤ (τ w0).e.ts y + Z w0 + 3) :
    ∀ (k t w w2 : Nat), t ≤ T → w < w2 → w2 < t →
      cntT τ (fun z => IsRet P y z.e) w = k → IsRet P y (τ w).e →
      cntT τ (fun z => IsRet P y z.e) w2 = k + 1 → IsRet P y (τ w2).e →
      cntT τ (fun z => Hit y z.e) t + (τ 0).held y ≤ k + 2 →
      (NpfAt y (τ w2).e ∧ (τ 0).e.now + t ≤ (τ w2).e.ts y + Rr w2 + PENDING_SLACK + B) ∨
      (τ 0).e.now + t ≤ (τ w).e.ts y + Z w + PENDING_SLACK + B := by
  have hPS : PENDING_SLACK = 25 := pending_slack_val
  have hD : DSTAR = 20 := dstar_val
  -- the fresh case: the capture owed from `w` is the next one after `w + 1`
  have fresh : ∀ (k t w w2 : Nat), t ≤ T → w < w2 → w2 < t →
      cntT τ (fun z => IsRet P y z.e) w = k → IsRet P y (τ w).e →
      cntT τ (fun z => IsRet P y z.e) w2 = k + 1 → IsRet P y (τ w2).e →
      cntT τ (fun z => Hit y z.e) t + (τ 0).held y ≤ k + 2 →
      k + 2 ≤ cntT τ (fun z => Hit y z.e) (w + 1) + (τ 0).held y →
      (NpfAt y (τ w2).e ∧ (τ 0).e.now + t ≤ (τ w2).e.ts y + Rr w2 + PENDING_SLACK + B) ∨
      (τ 0).e.now + t ≤ (τ w).e.ts y + Z w + PENDING_SLACK + B := by
    intro k t w w2 htT hww2 hw2t hwk hwb hw2k hw2b hh hfresh
    have hm := cntT_mono τ (fun z => Hit y z.e) (w + 1) t (by omega)
    have hr1 : cntT τ (fun z => IsRet P y z.e) (w + 1) = k + 1 := by
      rw [cntT_succ, if_pos hwb]; omega
    have hheld := held_runT P win usb sreq y τ T hT hWf (w + 1) (by omega)
    obtain ⟨hb, ho⟩ := held_le_one _ (hWf (w + 1) (by omega)) y (by omega)
    cases hwant : (τ (w + 1)).e.wantFetch y with
    | true =>
      right
      have hn := window_leT P win usb sreq y τ hok hy T hT hWf (w + 1) B (t - (w + 1)) (by omega)
        hwant hb (fun m hm hm' => hB (w + 1) m (by omega) hm')
        (fun i hi => no_event_betweenT τ (fun z => Hit y z.e) (w + 1) t (w + 1 + i) (by omega)
          (by omega) (by omega))
      have hRw := hR w (by omega) hwb
      have hz := hZ0 w (by omega) hwb
      have hnow := now_T P win usb sreq y τ T hT w (by omega)
      omega
    | false =>
      left
      exact pb_defer_gT P win usb sreq y τ hok hy T hT hWf B Rr (w + 1) w2 t
        (hR w2 (by omega) hw2b) hB (by omega) hw2t htT ho hwant hb hw2b (by omega) (by omega)
  -- from a capture at `c` on: wants (the 19 + B wait) or holds a no-prefetch head to `w2`
  have after : ∀ (k t w w2 c : Nat), t ≤ T → w < w2 → w2 < t → c < t → w + 1 ≤ c →
      cntT τ (fun z => IsRet P y z.e) w = k → IsRet P y (τ w).e →
      cntT τ (fun z => IsRet P y z.e) w2 = k + 1 → IsRet P y (τ w2).e →
      Hit y (τ c).e →
      cntT τ (fun z => Hit y z.e) (c + 1) = cntT τ (fun z => Hit y z.e) t →
      cntT τ (fun z => Hit y z.e) (c + 1) + (τ 0).held y = k + 2 →
      (NpfAt y (τ w2).e ∧ (τ 0).e.now + t ≤ (τ w2).e.ts y + Rr w2 + PENDING_SLACK + B) ∨
      t ≤ c + 1 + 19 + B := by
    intro k t w w2 c htT hww2 hw2t hct hwc hwk hwb hw2k hw2b hhit heq hcnt
    have hr1 : cntT τ (fun z => IsRet P y z.e) (w + 1) = k + 1 := by
      rw [cntT_succ, if_pos hwb]; omega
    have hrc := cntT_mono τ (fun z => IsRet P y z.e) (w + 1) (c + 1) (by omega)
    have hheld := held_runT P win usb sreq y τ T hT hWf (c + 1) (by omega)
    obtain ⟨hb, ho⟩ := held_le_one _ (hWf (c + 1) (by omega)) y (by omega)
    cases hwant : (τ (c + 1)).e.wantFetch y with
    | true =>
      right
      have hscan := hit_then_scanT P win usb sreq y τ T hT c (by omega) hhit
      have hn := window_le_19T P win usb sreq y τ hok hy T hT hWf (c + 1) B (t - (c + 1))
        (by omega) hwant hb (Or.inl hscan) (fun m hm hm' => hB (c + 1) m (by omega) hm')
        (fun i hi => no_event_betweenT τ (fun z => Hit y z.e) (c + 1) t (c + 1 + i) (by omega)
          (by omega) heq)
      omega
    | false =>
      left
      have hge1 : 1 ≤ (τ (c + 1)).held y := by
        obtain ⟨hv, -, -⟩ := npf_state _ y ho hwant
        rw [held_def]
        unfold Engine.headValid at hv
        cases hs : (τ (c + 1)).e.sel y <;> rw [hs] at hv <;> simp [hv] <;> omega
      have hcw2 : c + 1 ≤ w2 := by
        rcases Nat.lt_or_ge w2 (c + 1) with hlt | hge
        · exfalso
          have h2 := cntT_succ τ (fun z => IsRet P y z.e) w2
          rw [if_pos hw2b] at h2
          have h3 := cntT_mono τ (fun z => IsRet P y z.e) (w2 + 1) (c + 1) hlt
          omega
        · exact hge
      have hrw2 := cntT_mono τ (fun z => IsRet P y z.e) (c + 1) w2 hcw2
      exact pb_defer_gT P win usb sreq y τ hok hy T hT hWf B Rr (c + 1) w2 t
        (hR w2 (by omega) hw2b) hB hcw2 hw2t htT ho hwant hb hw2b (by omega) heq
  intro k
  induction k with
  | zero =>
    intro t w w2 htT hww2 hw2t hwk hwb hw2k hw2b hh
    by_cases hfr : 0 + 2 ≤ cntT τ (fun z => Hit y z.e) (w + 1) + (τ 0).held y
    · exact fresh 0 t w w2 htT hww2 hw2t hwk hwb hw2k hw2b hh hfr
    · -- H0 = 1 and nothing captured by w + 1: the start's refill is the earlier one
      have hm := cntT_mono τ (fun z => Hit y z.e) (w + 1) t (by omega)
      have h1 : (τ 0).held y = 1 := by omega
      have hzs := hZS0 w (by omega) hwb hwk h1
      have hz0 := hZ0 w (by omega) hwb
      have hzf : NpfAt y (τ w).e → Rr w + DSTAR + B ≤ Z w := hZF w (by omega) hwb
      have hnow0 := now_T P win usb sreq y τ T hT 0 (by omega)
      by_cases hlate : cntT τ (fun z => Hit y z.e) t = 0
      · right
        rcases pending_startT P win usb sreq y τ hok hy T hT hWf B Rr h1 hR hB t w htT
            (by omega) hwk hwb hlate with ⟨-, h⟩ | h
        · omega
        · omega
      · obtain ⟨c, hct, hck, hhit⟩ :=
          cntT_reach τ (fun z => Hit y z.e) t 0 (by omega)
        have hc1 : cntT τ (fun z => Hit y z.e) (c + 1) = 1 := by
          rw [cntT_succ, if_pos hhit]; omega
        have hwc : w + 1 ≤ c := by
          rcases Nat.lt_or_ge c (w + 1) with hlt | hge
          · have := cntT_mono τ (fun z => Hit y z.e) (c + 1) (w + 1) hlt
            omega
          · exact hge
        have hct1 := cntT_mono τ (fun z => Hit y z.e) (c + 1) t (by omega)
        have hs := pending_startT P win usb sreq y τ hok hy T hT hWf B Rr h1 hR hB c w (by omega)
          (by omega) hwk hwb hck
        rcases after 0 t w w2 c htT hww2 hw2t hct hwc hwk hwb hw2k hw2b hhit (by omega)
            (by omega) with h | h
        · exact Or.inl h
        · right
          rcases hs with ⟨hn', h'⟩ | h'
          · have := hzf hn'
            omega
          · omega
  | succ k ih =>
    intro t w w2 htT hww2 hw2t hwk hwb hw2k hw2b hh
    by_cases hfr : k + 1 + 2 ≤ cntT τ (fun z => Hit y z.e) (w + 1) + (τ 0).held y
    · exact fresh (k + 1) t w w2 htT hww2 hw2t hwk hwb hw2k hw2b hh hfr
    · obtain ⟨w', hw'w, hw'k, hw'b⟩ := cntT_reach τ (fun z => IsRet P y z.e) w k (by omega)
      have hgap := rdT_eq P win usb sreq y τ T hT w' w (Nat.le_of_lt hw'w) (by omega)
      have hzc := hZC w' w (by omega) ⟨hw'w, hw'b, hwb, by omega⟩
      have hz0 := hZ0 w (by omega) hwb
      have hzf : NpfAt y (τ w).e → Rr w + DSTAR + B ≤ Z w := hZF w (by omega) hwb
      have hm := cntT_mono τ (fun z => Hit y z.e) (w + 1) t (by omega)
      by_cases hlate : cntT τ (fun z => Hit y z.e) t + (τ 0).held y ≤ k + 2
      · right
        rcases ih t w' w htT hw'w (by omega) hw'k hw'b hwk hwb hlate with ⟨-, h⟩ | h
        · omega
        · omega
      · obtain ⟨c, hct, hck, hhit⟩ := cntT_reach τ (fun z => Hit y z.e) t
          (cntT τ (fun z => Hit y z.e) t - 1) (by omega)
        have hc1 : cntT τ (fun z => Hit y z.e) (c + 1) = cntT τ (fun z => Hit y z.e) t := by
          rw [cntT_succ, if_pos hhit]; omega
        have hwc : w + 1 ≤ c := by
          rcases Nat.lt_or_ge c (w + 1) with hlt | hge
          · have := cntT_mono τ (fun z => Hit y z.e) (c + 1) (w + 1) hlt
            omega
          · exact hge
        have hic := ih c w' w (by omega) hw'w (by omega) hw'k hw'b hwk hwb (by omega)
        rcases after (k + 1) t w w2 c htT hww2 hw2t hct hwc hwk hwb hw2k hw2b hhit hc1
            (by omega) with h | h
        · exact Or.inl h
        · right
          have hnowc := now_T P win usb sreq y τ T hT c (by omega)
          rcases hic with ⟨hn', h'⟩ | h'
          · have := hzf hn'
            omega
          · omega

/-! ### The head -/

/-- **Head valid along a trajectory, from a start of `H0` words.** GapRun's head theorem with
the start's refill (`H0 = 1`) carried by `hZS0` / `hHS0`. -/
theorem head_late_gapT (hok : SReqB P sreq) (hy : P.live y = true) (T : Nat)
    (hT : TrajY P win usb sreq y τ T) (hWf : ∀ n, n ≤ T → WfB (τ n)) (B : Nat) (Rr Z L : Nat → Nat)
    (hH0 : (τ 0).held y = 1 ∨ (τ 0).held y = 2)
    (hR : ∀ x, x < T → IsRet P y (τ x).e → (τ x).e.now ≤ (τ x).e.ts y + Rr x + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSumT P usb sreq y τ a m ≤ B)
    (hZ0 : ∀ x, x < T → IsRet P y (τ x).e → Rr x ≤ Z x)
    (hZF : ∀ x, x < T → IsRet P y (τ x).e → NpfAt y (τ x).e → Rr x + DSTAR + B ≤ Z x)
    (hZC : ∀ x x2, x2 < T → ConsecT P y τ x x2 → Z x + DSTAR + B ≤ rdT y τ x x2 + Z x2)
    (hZS0 : ∀ w0, w0 < T → IsRet P y (τ w0).e → cntT τ (fun z => IsRet P y z.e) w0 = 0 →
      (τ 0).held y = 1 → (τ 0).e.now + DSTAR + B ≤ (τ w0).e.ts y + Z w0 + 3)
    (hHD : ∀ x, x < T → IsRet P y (τ x).e → NpfAt y (τ x).e →
      Rr x + HEAD_SLACK + B ≤ gpT P y τ x + L x)
    (hHN : ∀ x x2, x2 < T → ConsecT P y τ x x2 →
      Z x + HEAD_SLACK + B ≤ rdT y τ x x2 + gpT P y τ x2 + L x2)
    (hHS0 : ∀ w0, w0 < T → IsRet P y (τ w0).e → cntT τ (fun z => IsRet P y z.e) w0 = 0 →
      (τ 0).held y = 1 → (τ 0).e.now + HEAD_SLACK + B ≤ (τ w0).e.ts y + gpT P y τ w0 + L w0 + 3)
    (t : Nat) (htT : t ≤ T)
    (hlate : ∀ x, x < t → IsRet P y (τ x).e →
      cntT τ (fun z => IsRet P y z.e) (x + 1) = cntT τ (fun z => IsRet P y z.e) t →
      (τ t).e.ts y + L x ≤ (τ t).e.now) :
    (τ t).e.headValid y = true := by
  have hPS : PENDING_SLACK = 25 := pending_slack_val
  have hHS : HEAD_SLACK = 26 := head_slack_val
  apply head_valid_of_countsT P win usb sreq y τ T hT hWf t htT
  by_cases hc : cntT τ (fun z => IsRet P y z.e) t + 1
      ≤ cntT τ (fun z => Hit y z.e) t + (τ 0).held y
  · exact hc
  · exfalso
    have hnow := now_T P win usb sreq y τ T hT t htT
    have hnow0 := now_T P win usb sreq y τ T hT 0 (by omega)
    obtain ⟨w2, hw2t, hw2k, hw2b⟩ := cntT_reach τ (fun z => IsRet P y z.e) t
      (cntT τ (fun z => IsRet P y z.e) t - 1) (by omega)
    have h3 : cntT τ (fun z => IsRet P y z.e) (w2 + 1) = cntT τ (fun z => IsRet P y z.e) t := by
      rw [cntT_succ, if_pos hw2b]; omega
    have hl := hlate w2 hw2t hw2b h3
    have hs2 := ts_gapT P win usb sreq y τ T hT w2 t (isWB_of_ret P y _ hw2b) hw2t htT
    by_cases hone : cntT τ (fun z => IsRet P y z.e) t = 1
    · -- one retirement: the start's refill (H0 = 1, nothing captured)
      have h1 : (τ 0).held y = 1 := by omega
      have hh0 : cntT τ (fun z => Hit y z.e) t = 0 := by omega
      have hk0 : cntT τ (fun z => IsRet P y z.e) w2 = 0 := by omega
      rcases pending_startT P win usb sreq y τ hok hy T hT hWf B Rr h1 hR hB t w2 htT hw2t hk0
          hw2b hh0 with ⟨hn, h⟩ | h
      · have := hHD w2 (by omega) hw2b hn
        omega
      · have := hHS0 w2 (by omega) hw2b hk0 h1
        omega
    · obtain ⟨w, hwt, hwk, hwb⟩ := cntT_reach τ (fun z => IsRet P y z.e) t
        (cntT τ (fun z => IsRet P y z.e) t - 2) (by omega)
      have hww2 : w < w2 := by
        rcases Nat.lt_or_ge w w2 with hlt | hge
        · exact hlt
        · have := cntT_mono τ (fun z => IsRet P y z.e) w2 w hge
          omega
      have hs1 := rdT_eq P win usb sreq y τ T hT w w2 (Nat.le_of_lt hww2) (by omega)
      rcases pending_bound_gapT P win usb sreq y τ hok hy T hT hWf B Rr Z hH0 hR hB hZ0 hZF hZC
          hZS0 (cntT τ (fun z => IsRet P y z.e) t - 2) t w w2 htT hww2 hw2t hwk hwb (by omega)
          hw2b (by omega) with ⟨hn, h⟩ | h
      · have := hHD w2 (by omega) hw2b hn
        omega
      · have := hHN w w2 (by omega) ⟨hww2, hwb, hw2b, by omega⟩
        omega

end

#print axioms pending_startT
#print axioms pending_bound_gapT
#print axioms head_late_gapT

end JLane
