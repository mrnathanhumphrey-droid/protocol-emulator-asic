import JLane.CloseBK
/-!
# Brick C3f — the per-lane response bounds closed on `runBK` in span form

`CloseBK.wb_closeBK` bounds another lane `z`'s decisions in `y`'s window by a spacing `σ z`
(`hsep`, `hmul`). The certificate does not count that way: `branch_budget._decisions` takes the
least `m` with `span_min(m) ≥ K + 1 + R_z` -- `RespSpan.wb_close_span`'s `hspan` and
`R y + 1 + R z ≤ G z`, proved on `run`. Here is the same closure on the buffered engine with
flushes (Wilson 11-21, span ruling):

* `hspan` — any `m z` consecutive writebacks of `z`, **counted from a writeback of `z`**, advance
  its release by at least `G z`, given they met their response bounds. The anchor is the one
  change from `RespSpan`: there `x1` is any cycle; `wb_close_span` uses it only at a writeback,
  and on `runBK` a flush can move a timestamp down (a FALLTHROUGH ARM's deadline `D`, then its
  edge's `now + 1 < D`), so the premise is asked only where it is used;
* `hz` — then `z` is decided at most `m z` times in `y`'s window: the first and the `(m z+1)`-th
  decision would be at least `G z − R z` apart (`dec_sepBK`, `cntBK_wb_shift`);
* `hnf`, `hfree`, `hS` as in `wb_closeBK`.

`wb_closeBK_span_K11` discharges `hS` (`S = 0`, `noDec_zero_K11`), `hrel` (`hrelR_bridged`, from
the non-arming writebacks' `R + 3` gap, lane-cert check 22) and `hwin` (the mask) on the bridged
run; `hspan`, `hG` and `hK` stay the certificate's.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- Two decisions of a lane along `runBK` are a dispatch apart. -/
theorem dec_sepBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X : EngBK) (z : Lane)
    (a b : Nat) (hab : a < b) (ha : Dec win z (runBK P win usb sreq fl k a X).x.e)
    (hb : Dec win z (runBK P win usb sreq fl k b X).x.e) : a + 3 ≤ b := by
  obtain ⟨hbi, -, -⟩ := hb
  have hst1 : (runBK P win usb sreq fl k (a + 1) X).x.e.st = .drive := by
    rw [runBK_succ', stepBKK_st]
    exact (step_of_dec P win _ z ha).1
  have hst2 : (runBK P win usb sreq fl k (a + 2) X).x.e.st = .wb :=
    (dec_wbBK P win usb sreq fl k X a z ha).1
  rcases Nat.lt_or_ge b (a + 3) with hlt | hge
  · exfalso
    have : b = a + 1 ∨ b = a + 2 := by omega
    rcases this with rfl | rfl
    · rw [hst1] at hbi
      cases hbi
    · rw [hst2] at hbi
      cases hbi
  · exact hge

/-- From an idle start, a writeback at `x + 2` along `runBK` is exactly a decision at `x`. -/
theorem wb_iff_decBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK)
    (h0 : X0.x.e.st = .idle) (z : Lane) (x : Nat) :
    IsWB z (runBK P win usb sreq fl k (x + 2) X0).x.e ↔
      Dec win z (runBK P win usb sreq fl k x X0).x.e := by
  constructor
  · intro h
    obtain ⟨s, hs, hd⟩ := wb_backBK P win usb sreq fl k X0 h0 (x + 2) z h
    have : s = x := by omega
    subst this
    exact hd
  · exact dec_wbBK P win usb sreq fl k X0 x z

/-- Writebacks counted from `a + 2` are the decisions counted from `a`, along `runBK`. -/
theorem cntBK_wb_shift (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK)
    (h0 : X0.x.e.st = .idle) (z : Lane) :
    ∀ n a, cntBK P win usb sreq fl k (IsWB z) n (runBK P win usb sreq fl k (a + 2) X0)
      = cntBK P win usb sreq fl k (Dec win z) n (runBK P win usb sreq fl k a X0)
  | 0, _ => by simp [cntBK]
  | n + 1, a => by
    have s1 := runBK_succ' P win usb sreq fl k (a + 2) X0
    have s2 := runBK_succ' P win usb sreq fl k a X0
    have e1 : cntBK P win usb sreq fl k (IsWB z) (n + 1) (runBK P win usb sreq fl k (a + 2) X0)
        = (if IsWB z (runBK P win usb sreq fl k (a + 2) X0).x.e then 1 else 0)
          + cntBK P win usb sreq fl k (IsWB z) n (runBK P win usb sreq fl k (a + 1 + 2) X0) := by
      rw [show a + 1 + 2 = a + 2 + 1 by omega, s1]
      rfl
    have e2 : cntBK P win usb sreq fl k (Dec win z) (n + 1) (runBK P win usb sreq fl k a X0)
        = (if Dec win z (runBK P win usb sreq fl k a X0).x.e then 1 else 0)
          + cntBK P win usb sreq fl k (Dec win z) n (runBK P win usb sreq fl k (a + 1) X0) := by
      rw [s2]
      rfl
    rw [e1, e2, cntBK_wb_shift fl k X0 h0 z n (a + 1)]
    by_cases h : Dec win z (runBK P win usb sreq fl k a X0).x.e
    · rw [if_pos h, if_pos ((wb_iff_decBK P win usb sreq fl k X0 h0 z a).mpr h)]
    · rw [if_neg h, if_neg (fun h' => h ((wb_iff_decBK P win usb sreq fl k X0 h0 z a).mp h'))]

/-- **The per-lane response bounds, closed on `runBK` in span form.** As `wb_closeBK`, with the
spacing `σ` / `hsep` / `hmul` replaced by the span `hspan` (anchored at a writeback) and
`R y + 1 + R z ≤ G z` -- the certificate's rule (`branch_budget._decisions`). -/
theorem wb_closeBK_span (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (T S : Nat)
    (R m G : Lane → Nat)
    (h0 : X0.x.e.st = .idle) (h0ts : ∀ l, X0.x.e.now ≤ X0.x.e.ts l)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hm1 : ∀ z, 1 ≤ m z)
    (hS : ∀ y c, P.live y = true → c + (R y + 1) + 2 ≤ T →
      (∀ i, i < R y + 1 → Ready P y (runBK P win usb sreq fl k (c + i) X0).x.e ∧
        ¬Dec win y (runBK P win usb sreq fl k (c + i) X0).x.e) →
      Dec win y (runBK P win usb sreq fl k (c + (R y + 1)) X0).x.e →
      (∀ i, i ≤ R y + 1 → fl (runBK P win usb sreq fl k (c + i) X0).x.e.now y = false) →
      cntBK P win usb sreq fl k (fun e => noDecB win e = true) (R y + 1)
        (runBK P win usb sreq fl k c X0) ≤ S)
    (hspan : ∀ z x1 n, IsWB z (runBK P win usb sreq fl k x1 X0).x.e →
      cntBK P win usb sreq fl k (IsWB z) n (runBK P win usb sreq fl k x1 X0) = m z →
      (∀ x, x1 ≤ x → x < x1 + n → IsWB z (runBK P win usb sreq fl k x X0).x.e →
        (runBK P win usb sreq fl k x X0).x.e.now
          ≤ (runBK P win usb sreq fl k x X0).x.e.ts z + R z + 2) →
      (runBK P win usb sreq fl k x1 X0).x.e.ts z + G z
        ≤ (runBK P win usb sreq fl k (x1 + n) X0).x.e.ts z)
    (hrel : ∀ y, HrelR P win usb sreq fl k X0 y (R y + 1))
    (hG : ∀ y z, z ≠ y → R y + 1 + R z ≤ G z)
    (hK : ∀ y, 3 * (m L0 + m L1 + m L2 + m L3 + m L4 - m y) + S + 3 ≤ R y + 1) :
    ∀ t, t < T → ∀ y, P.live y = true → IsWB y (runBK P win usb sreq fl k t X0).x.e →
      (runBK P win usb sreq fl k t X0).x.e.now
        ≤ (runBK P win usb sreq fl k t X0).x.e.ts y + R y + 2 := by
  have key : ∀ n, ∀ t, t < n → t < T → ∀ y, P.live y = true →
      IsWB y (runBK P win usb sreq fl k t X0).x.e →
      (runBK P win usb sreq fl k t X0).x.e.now
        ≤ (runBK P win usb sreq fl k t X0).x.e.ts y + R y + 2 := by
    intro n
    induction n with
    | zero => intro t ht; exact absurd ht (Nat.not_lt_zero t)
    | succ n ih =>
      intro t ht htT y hy hwb
      rcases Nat.lt_or_ge t n with htn | htn
      · exact ih t htn htT y hy hwb
      · have IH : ∀ t', t' < t → ∀ z, P.live z = true →
            IsWB z (runBK P win usb sreq fl k t' X0).x.e →
            (runBK P win usb sreq fl k t' X0).x.e.now
              ≤ (runBK P win usb sreq fl k t' X0).x.e.ts z + R z + 2 :=
          fun t' h' => ih t' (by omega) (by omega)
        have hw := wb_bound_winBK_fl P win usb sreq fl k X0 h0 h0ts y hy
          (m L0 + m L1 + m L2 + m L3 + m L4 - m y) S (R y + 1) (hK y) t hwb
          (hnf_runBK P win usb sreq fl k X0 y t)
          (hfree_runBK P win usb sreq fl k X0 y (R y + 1) t hwb (hrel y)
            (fun w hw hwbw => by
              have := IH w hw y hy hwbw
              omega))
          (fun c hc => by
            have hz : ∀ z, z ≠ y → cntBK P win usb sreq fl k (Dec win z) (R y + 1)
                (runBK P win usb sreq fl k c X0) ≤ m z := by
              intro z hzy
              rcases Nat.lt_or_ge (cntBK P win usb sreq fl k (Dec win z) (R y + 1)
                  (runBK P win usb sreq fl k c X0)) (m z + 1) with hlt | hge
              · omega
              · exfalso
                obtain ⟨i, hi, hci, hdi⟩ := cntBK_reach P win usb sreq fl k (Dec win z) (R y + 1)
                  (runBK P win usb sreq fl k c X0) 0 (by omega)
                obtain ⟨j, hj, hcj, hdj⟩ := cntBK_reach P win usb sreq fl k (Dec win z) (R y + 1)
                  (runBK P win usb sreq fl k c X0) (m z) (by omega)
                rw [← runBK_add] at hdi hdj
                have hij : i < j := by
                  rcases Nat.lt_or_ge i j with h' | h'
                  · exact h'
                  · have := cntBK_mono P win usb sreq fl k (Dec win z)
                      (runBK P win usb sreq fl k c X0) j i h'
                    have := hm1 z
                    omega
                have h3 := dec_sepBK P win usb sreq fl k X0 z (c + i) (c + j) (by omega) hdi hdj
                -- the decisions in [c+i, c+j): exactly m z, none in its last two cycles
                have hsplit := cntBK_add P win usb sreq fl k (Dec win z) i (j - i)
                  (runBK P win usb sreq fl k c X0)
                rw [show i + (j - i) = j by omega, ← runBK_add] at hsplit
                have hsplit2 := cntBK_add P win usb sreq fl k (Dec win z) (j - i - 2) 2
                  (runBK P win usb sreq fl k (c + i) X0)
                rw [show j - i - 2 + 2 = j - i by omega, ← runBK_add] at hsplit2
                have hlast : cntBK P win usb sreq fl k (Dec win z) 2
                    (runBK P win usb sreq fl k (c + i + (j - i - 2)) X0) = 0 :=
                  cntBK_zero_of P win usb sreq fl k (Dec win z) 2 _ (fun s hs hds => by
                    rw [← runBK_add] at hds
                    have := dec_sepBK P win usb sreq fl k X0 z (c + i + (j - i - 2) + s) (c + j)
                      (by omega) hds hdj
                    omega)
                have hshift := cntBK_wb_shift P win usb sreq fl k X0 h0 z (j - i - 2) (c + i)
                have hlz := (hwin _ z hdi.2.1).1
                have hwbi := dec_wbBK P win usb sreq fl k X0 (c + i) z hdi
                -- the span over those m z writebacks, from the first one's writeback
                have hsp := hspan z (c + i + 2) (j - i - 2) hwbi (by omega)
                  (fun x hx1 hx2 hxw => IH x (by omega) z hlz hxw)
                rw [show c + i + 2 + (j - i - 2) = c + j by omega] at hsp
                have hr := IH (c + i + 2) (by omega) z hlz hwbi
                have hrdy := (hwin _ z hdj.2.1).2
                have hni := now_runBK P win usb sreq fl k (c + i + 2) X0
                have hnj := now_runBK P win usb sreq fl k (c + j) X0
                have hg := hG y z hzy
                omega
            have hs := cntBK_decOther_split P win usb sreq fl k y (R y + 1)
              (runBK P win usb sreq fl k c X0)
            have ha := cntBK_decAny_split P win usb sreq fl k (R y + 1)
              (runBK P win usb sreq fl k c X0)
            rcases lane_cases y with rfl | rfl | rfl | rfl | rfl
            · have a := hz L1 (by decide); have b := hz L2 (by decide)
              have c' := hz L3 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L2 (by decide)
              have c' := hz L3 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L1 (by decide)
              have c' := hz L3 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L1 (by decide)
              have c' := hz L2 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L1 (by decide)
              have c' := hz L2 (by decide); have d := hz L3 (by decide); omega)
          (fun c hc hrd hd hf => hS y c hy (by omega) hrd hd hf)
        omega
  intro t ht
  exact key (t + 1) t (Nat.lt_succ_self t) ht

end

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)
  (kt : Nat → Lane → Nat) (A0 : EngBA)

/-- **The per-lane bounds closed on the bridged run, in span form** (`slot_on_composition` L4
hM/hS): `hS = 0` (`noDec_zero_K11`), `hrel` (`hrelR_bridged`, from the non-arming writebacks'
`R + 3` gap) and `hwin` through the mask discharged; the span `hspan`, `hG` and `hK` are the
certificate's (`branch_budget._decisions`, `lane_cert.span_min`). -/
theorem wb_closeBK_span_K11 (hedge : ∀ t l, t + 1 ≤ edge t l) (hA : ArmInvB A0)
    (h0 : A0.X.x.e.st = .idle)
    (h0ts : ∀ l, A0.X.x.e.now ≤ A0.X.x.e.ts l)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hb : BPrimeWin win) (hws : ∀ y e, e.st = .idle → Ready P y e → win e ≠ none)
    (hK11 : ∀ n, K11At P win (runBA P win usb sreq isArm edge kt n A0).armed
      (runBA P win usb sreq isArm edge kt n A0).X.x.e)
    (T : Nat) (R m G : Lane → Nat) (hm1 : ∀ z, 1 ≤ m z)
    (hgap : ∀ z x, IsWB z (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt x A0.X).x.e →
      (runBA P win usb sreq isArm edge kt x A0).arms P isArm z = false →
      R z + 3 ≤ P.dly z + P.ext (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt x A0.X).x.e.now z)
    (hspan : ∀ z x1 n, IsWB z (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt x1 A0.X).x.e →
      cntBK P (winS P win usb sreq isArm edge kt A0) usb sreq (flS P win usb sreq isArm edge kt A0)
        kt (IsWB z) n (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt x1 A0.X) = m z →
      (∀ x, x1 ≤ x → x < x1 + n → IsWB z (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt x A0.X).x.e →
        (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
            (flS P win usb sreq isArm edge kt A0) kt x A0.X).x.e.now
          ≤ (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
            (flS P win usb sreq isArm edge kt A0) kt x A0.X).x.e.ts z + R z + 2) →
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt x1 A0.X).x.e.ts z + G z
        ≤ (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt (x1 + n) A0.X).x.e.ts z)
    (hG : ∀ y z, z ≠ y → R y + 1 + R z ≤ G z)
    (hK : ∀ y, 3 * (m L0 + m L1 + m L2 + m L3 + m L4 - m y) + 0 + 3 ≤ R y + 1) :
    ∀ t, t < T → ∀ y, P.live y = true →
      IsWB y (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt t A0.X).x.e →
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt t A0.X).x.e.now
        ≤ (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt t A0.X).x.e.ts y + R y + 2 :=
  wb_closeBK_span P (winS P win usb sreq isArm edge kt A0) usb sreq
    (flS P win usb sreq isArm edge kt A0) kt A0.X T 0 R m G h0 h0ts
    (fun e w h => hwin e w (winA_some win _ e w h)) hm1
    (fun y c _ _ hrd hd hf => Nat.le_of_eq
      (noDec_zero_K11 P win usb sreq isArm edge kt A0 hb hws hK11 y c (R y + 1) hrd hd hf))
    hspan
    (fun y => hrelR_bridged P win usb sreq isArm edge kt A0 hedge hA h0 y (R y + 1)
      (fun x hx ha => by
        have := hgap y x hx ha
        omega))
    hG hK

end

end JLane
