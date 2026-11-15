import JLane.RespEdf
import JLane.RespSpan
import JLane.UsbLane
import JLane.Pigeon
/-!
# Brick Y2 — the per-lane response bounds under EDF, closed (Wilson 11-15, RespWinN item 4)

`RespSpan.wb_close_span` closes every lane's response bound at once, charging lane `y` with each
other lane `z`'s decisions in `y`'s window `R y + 1`, as long as `R y + 1 + R z ≤ G z`. That
condition grows with the WINDOW, and a lane spaced at D* beside fast lanes cannot meet it.

Here `y` is charged only with `z`'s decisions whose absolute deadline beats `y`'s
(`RespEdf.wb_bound_edf`, from the RTL's EDF contract `EdfB.EdfBeatsB`). Those decisions of `z`
have timestamps below `ts y + ds y - ds z` and, being decided after `y`'s release plus its
lateness, at least that minus `z`'s own response: an interval whose length does NOT depend on the
window. So `z` is decided at most `m y z` such times as long as

    ds y + (L z + R z) ≤ ds z + L y + G y z            (`hG`)

`G y z` the least advance of `z`'s release over `m y z` consecutive writebacks (`hspan`, the gap
sequence, as in `wb_close_span`). The conclusion: every writeback of `y` lands within
`L y + R y + 2` of its release, `3 · Σ_{z ≠ y} m y z + S + 3 ≤ R y + 1`.

Premises, as hypotheses the certificate evaluates (`model/branch_budget.py`):
* `hedf` — the RTL's EDF contract (`EdfBeatsB`), per lane;
* `hv` — `y`'s head is valid from its release plus `L y` (GapRun's lateness certificate);
* `hspan`, `hS`, `hrel`, `hwin` — as in `wb_close_span`.
-/
namespace JLane

/-- A count is at most the sum of five counts when every counted state satisfies one of them. -/
theorem cnt_le_sum5 (P : Program) (win : Engine → Option Lane) (Q Q0 Q1 Q2 Q3 Q4 : Engine → Prop)
    [DecidablePred Q] [DecidablePred Q0] [DecidablePred Q1] [DecidablePred Q2]
    [DecidablePred Q3] [DecidablePred Q4] :
    ∀ (n : Nat) (e : Engine),
      (∀ s, s < n → Q (run P win s e) →
        Q0 (run P win s e) ∨ Q1 (run P win s e) ∨ Q2 (run P win s e) ∨
        Q3 (run P win s e) ∨ Q4 (run P win s e)) →
      cnt P win Q n e ≤ cnt P win Q0 n e + cnt P win Q1 n e + cnt P win Q2 n e
        + cnt P win Q3 n e + cnt P win Q4 n e
  | 0, _, _ => Nat.zero_le _
  | n + 1, e, h => by
    have ih := cnt_le_sum5 P win Q Q0 Q1 Q2 Q3 Q4 n (step P win e)
      (fun s hs hq => h (s + 1) (by omega) hq)
    have h0 : Q e → Q0 e ∨ Q1 e ∨ Q2 e ∨ Q3 e ∨ Q4 e := h 0 (by omega)
    show (if Q e then 1 else 0) + cnt P win Q n (step P win e)
        ≤ ((if Q0 e then 1 else 0) + cnt P win Q0 n (step P win e))
          + ((if Q1 e then 1 else 0) + cnt P win Q1 n (step P win e))
          + ((if Q2 e then 1 else 0) + cnt P win Q2 n (step P win e))
          + ((if Q3 e then 1 else 0) + cnt P win Q3 n (step P win e))
          + ((if Q4 e then 1 else 0) + cnt P win Q4 n (step P win e))
    by_cases hq : Q e
    · rw [if_pos hq]
      rcases h0 hq with h' | h' | h' | h' | h'
      · rw [if_pos h']; split <;> split <;> split <;> split <;> omega
      · rw [if_pos h']; split <;> split <;> split <;> split <;> omega
      · rw [if_pos h']; split <;> split <;> split <;> split <;> omega
      · rw [if_pos h']; split <;> split <;> split <;> split <;> omega
      · rw [if_pos h']; split <;> split <;> split <;> split <;> omega
    · rw [if_neg hq]
      split <;> split <;> split <;> split <;> split <;> omega

/-- `z` decided, `z ≠ y`, with an absolute deadline below the bound `B0`. -/
def DecBelow (ds : Lane → Nat) (win : Engine → Option Lane) (y z : Lane) (B0 : Nat)
    (e : Engine) : Prop :=
  z ≠ y ∧ Dec win z e ∧ e.ts z + ds z < B0

instance (ds : Lane → Nat) (win : Engine → Option Lane) (y z : Lane) (B0 : Nat) :
    DecidablePred (DecBelow ds win y z B0) := by
  intro e
  unfold DecBelow Dec
  exact inferInstance

/-- **The per-lane response bounds under EDF.** -/
theorem wb_close_edf (P : Program) (win : Engine → Option Lane) (e0 : Engine) (T S : Nat)
    (ds L R : Lane → Nat) (m G : Lane → Lane → Nat)
    (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hedf : ∀ y, EdfBeatsB P ds win y)
    (hv : ∀ y x, x < T → (run P win x e0).ts y + L y ≤ (run P win x e0).now →
      (run P win x e0).headValid y = true)
    (hm1 : ∀ y z, 1 ≤ m y z)
    (hS : ∀ y c, P.live y = true → c + (R y + 1) ≤ T →
      cnt P win (fun e => noDecB win e = true) (R y + 1) (run P win c e0) ≤ S)
    (hspan : ∀ y z x1 n, cnt P win (IsWB z) n (run P win x1 e0) = m y z →
      (∀ x, x1 ≤ x → x < x1 + n → IsWB z (run P win x e0) →
        (run P win x e0).now ≤ (run P win x e0).ts z + (L z + R z) + 2) →
      (run P win x1 e0).ts z + G y z ≤ (run P win (x1 + n) e0).ts z)
    (hrel : ∀ y x, IsWB y (run P win x e0) →
      (run P win x e0).now ≤ (run P win x e0).ts y + (L y + R y) + 2 →
      (run P win x e0).now < (run P win (x + 1) e0).ts y)
    (hG : ∀ y z, z ≠ y → ds y + (L z + R z) ≤ ds z + L y + G y z)
    (hK : ∀ y, 3 * (m y L0 + m y L1 + m y L2 + m y L3 + m y L4 - m y y) + S + 3 ≤ R y + 1) :
    ∀ t, t < T → ∀ y, P.live y = true → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + (L y + R y) + 2 := by
  have key : ∀ n, ∀ t, t < n → t < T → ∀ y, P.live y = true → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + (L y + R y) + 2 := by
    intro n
    induction n with
    | zero => intro t ht; exact absurd ht (Nat.not_lt_zero t)
    | succ n ih =>
      intro t ht htT y hy hwb
      rcases Nat.lt_or_ge t n with htn | htn
      · exact ih t htn htT y hy hwb
      · have IH : ∀ t', t' < t → ∀ z, P.live z = true → IsWB z (run P win t' e0) →
            (run P win t' e0).now ≤ (run P win t' e0).ts z + (L z + R z) + 2 :=
          fun t' h' => ih t' (by omega) (by omega)
        have hw := wb_bound_edf P win e0 h0 h0ts y hy ds (hedf y) (L y)
          (m y L0 + m y L1 + m y L2 + m y L3 + m y L4 - m y y) S (R y + 1) (hK y) t hwb
          (fun w hw hwbw => by
            have hr := IH w (by omega) y hy hwbw
            have h1 := hrel y w hwbw hr
            have h2 := ts_mono P win y e0 (w + 1) t (by omega)
            omega)
          (fun x hx hp => hv y x (by omega) hp)
          (fun c hc hpast => by
            -- the bound every counted deadline is below: y's timestamp at the window's end
            have hz : ∀ z, cnt P win (DecBelow ds win y z
                ((run P win (c + (R y + 1)) e0).ts y + ds y)) (R y + 1) (run P win c e0)
                ≤ (if z = y then 0 else m y z) := by
              intro z
              by_cases hzy : z = y
              · rw [if_pos hzy]
                have := cnt_zero_of P win (DecBelow ds win y z
                  ((run P win (c + (R y + 1)) e0).ts y + ds y)) (R y + 1) (run P win c e0)
                  (fun s _ hd => hd.1 hzy)
                omega
              rw [if_neg hzy]
              rcases Nat.lt_or_ge (cnt P win (DecBelow ds win y z
                  ((run P win (c + (R y + 1)) e0).ts y + ds y)) (R y + 1) (run P win c e0))
                  (m y z + 1) with hlt | hge
              · omega
              · exfalso
                obtain ⟨i, hi, hci, hdi⟩ := cnt_reach P win (DecBelow ds win y z ((run P win (c + (R y + 1)) e0).ts y + ds y)) (R y + 1) (run P win c e0) 0 (by omega)
                obtain ⟨j, hj, hcj, hdj⟩ :=
                  cnt_reach P win (DecBelow ds win y z ((run P win (c + (R y + 1)) e0).ts y + ds y)) (R y + 1) (run P win c e0) (m y z) (by omega)
                rw [← run_add] at hdi hdj
                have hij : i < j := by
                  rcases Nat.lt_or_ge i j with h' | h'
                  · exact h'
                  · have := cnt_mono P win (DecBelow ds win y z ((run P win (c + (R y + 1)) e0).ts y + ds y)) (run P win c e0) j i h'
                    have := hm1 y z
                    omega
                have h3 := dec_sep P win e0 z (c + i) (c + j) (by omega) hdi.2.1 hdj.2.1
                -- every decision of z in [c+i, c+j] is below the bound (timestamps only grow)
                have hbelow : ∀ s, s < j - i → Dec win z (run P win s (run P win (c + i) e0)) →
                    DecBelow ds win y z ((run P win (c + (R y + 1)) e0).ts y + ds y)
                      (run P win s (run P win (c + i) e0)) := by
                  intro s hs hd
                  have e1 : run P win s (run P win (c + i) e0) = run P win (c + i + s) e0 :=
                    (run_add P win (c + i) s e0).symm
                  rw [e1] at hd ⊢
                  refine ⟨hzy, hd, ?_⟩
                  have h1 := ts_mono P win z e0 (c + i + s) (c + j) (by omega)
                  have h2 := hdj.2.2
                  omega
                -- the decisions in [c+i, c+j): exactly m y z of z, none in the last two cycles
                have hsplit := cnt_add P win (DecBelow ds win y z ((run P win (c + (R y + 1)) e0).ts y + ds y)) i (j - i) (run P win c e0)
                rw [show i + (j - i) = j by omega, ← run_add] at hsplit
                have hsplit2 := cnt_add P win (Dec win z) (j - i - 2) 2 (run P win (c + i) e0)
                rw [show j - i - 2 + 2 = j - i by omega, ← run_add] at hsplit2
                have hlast : cnt P win (Dec win z) 2 (run P win (c + i + (j - i - 2)) e0) = 0 :=
                  cnt_zero_of P win (Dec win z) 2 _ (fun s hs hds => by
                    rw [← run_add] at hds
                    have := dec_sep P win e0 z (c + i + (j - i - 2) + s) (c + j) (by omega)
                      hds hdj.2.1
                    omega)
                have hle1 := cnt_mono_run P win (Dec win z) (DecBelow ds win y z ((run P win (c + (R y + 1)) e0).ts y + ds y)) (j - i) (run P win (c + i) e0) hbelow
                have hle2 := cnt_mono_run P win (DecBelow ds win y z ((run P win (c + (R y + 1)) e0).ts y + ds y)) (Dec win z) (j - i) (run P win (c + i) e0)
                  (fun s _ hd => hd.2.1)
                have hshift := cnt_wb_shift P win e0 h0 z (j - i - 2) (c + i)
                have hlz := (hwin _ z hdi.2.1.2.1).1
                have hsp := hspan y z (c + i + 2) (j - i - 2) (by omega) (fun x hx1 hx2 hxw =>
                  IH x (by omega) z hlz hxw)
                rw [show c + i + 2 + (j - i - 2) = c + j by omega] at hsp
                obtain ⟨hts2, hnow2⟩ := dec_ts P win e0 (c + i) z hdi.2.1
                have hr := IH (c + i + 2) (by omega) z hlz (dec_wb P win e0 (c + i) z hdi.2.1)
                have hni := now_run P win (c + i) e0
                have hnc := now_run P win c e0
                have hg := hG y z hzy
                have hdj3 := hdj.2.2
                omega
            -- every EDF-earlier decision in the window is some z's decision below the bound
            have hsum := cnt_le_sum5 P win (fun e => decEdf ds win y e = true)
              (DecBelow ds win y L0 ((run P win (c + (R y + 1)) e0).ts y + ds y))
              (DecBelow ds win y L1 ((run P win (c + (R y + 1)) e0).ts y + ds y))
              (DecBelow ds win y L2 ((run P win (c + (R y + 1)) e0).ts y + ds y))
              (DecBelow ds win y L3 ((run P win (c + (R y + 1)) e0).ts y + ds y))
              (DecBelow ds win y L4 ((run P win (c + (R y + 1)) e0).ts y + ds y))
              (R y + 1) (run P win c e0) (fun s hs hq => by
                rw [← run_add] at hq ⊢
                have hty := ts_mono P win y e0 (c + s) (c + (R y + 1)) (by omega)
                unfold decEdf at hq
                cases hw : win (run P win (c + s) e0) with
                | none => rw [hw] at hq; cases hq
                | some w =>
                  rw [hw] at hq
                  simp only [Bool.and_eq_true, decide_eq_true_eq] at hq
                  obtain ⟨⟨⟨hid, hne⟩, hvw⟩, hlt⟩ := hq
                  have hd : DecBelow ds win y w ((run P win (c + (R y + 1)) e0).ts y + ds y)
                      (run P win (c + s) e0) := ⟨hne, ⟨hid, hw, hvw⟩, by omega⟩
                  rcases lane_cases w with rfl | rfl | rfl | rfl | rfl
                  · exact Or.inl hd
                  · exact Or.inr (Or.inl hd)
                  · exact Or.inr (Or.inr (Or.inl hd))
                  · exact Or.inr (Or.inr (Or.inr (Or.inl hd)))
                  · exact Or.inr (Or.inr (Or.inr (Or.inr hd))))
            have a := hz L0; have b := hz L1; have c' := hz L2; have d := hz L3; have f := hz L4
            rcases lane_cases y with rfl | rfl | rfl | rfl | rfl <;>
              simp only [if_true, if_false, show L0 ≠ L1 from by decide, show L0 ≠ L2 from by decide,
                show L0 ≠ L3 from by decide, show L0 ≠ L4 from by decide,
                show L1 ≠ L0 from by decide, show L1 ≠ L2 from by decide,
                show L1 ≠ L3 from by decide, show L1 ≠ L4 from by decide,
                show L2 ≠ L0 from by decide, show L2 ≠ L1 from by decide,
                show L2 ≠ L3 from by decide, show L2 ≠ L4 from by decide,
                show L3 ≠ L0 from by decide, show L3 ≠ L1 from by decide,
                show L3 ≠ L2 from by decide, show L3 ≠ L4 from by decide,
                show L4 ≠ L0 from by decide, show L4 ≠ L1 from by decide,
                show L4 ≠ L2 from by decide, show L4 ≠ L3 from by decide] at a b c' d f <;>
              omega)
          (fun c hc => hS y c hy (by omega))
        omega
  intro t ht
  exact key (t + 1) t (Nat.lt_succ_self t) ht

#print axioms cnt_le_sum5
#print axioms wb_close_edf

end JLane
