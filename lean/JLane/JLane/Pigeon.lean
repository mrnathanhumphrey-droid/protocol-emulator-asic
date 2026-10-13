import JLane.LemmaA
/-!
# Brick 11 — pigeonhole over the lanes
If, during lane `i`'s wait, no other lane is decided more than once, then at most
`k − 1` other-lane decisions happen, and Lemma A bounds the wait by 14.
-/
namespace JLane

abbrev L0 : Lane := ⟨0, by decide⟩
abbrev L1 : Lane := ⟨1, by decide⟩
abbrev L2 : Lane := ⟨2, by decide⟩
abbrev L3 : Lane := ⟨3, by decide⟩
abbrev L4 : Lane := ⟨4, by decide⟩

theorem lane_cases (z : Lane) : z = L0 ∨ z = L1 ∨ z = L2 ∨ z = L3 ∨ z = L4 := by
  obtain ⟨v, hv⟩ := z
  have hK : K = 5 := rfl
  have : v = 0 ∨ v = 1 ∨ v = 2 ∨ v = 3 ∨ v = 4 := by omega
  rcases this with rfl | rfl | rfl | rfl | rfl
  · exact Or.inl rfl
  · exact Or.inr (Or.inl rfl)
  · exact Or.inr (Or.inr (Or.inl rfl))
  · exact Or.inr (Or.inr (Or.inr (Or.inl rfl)))
  · exact Or.inr (Or.inr (Or.inr (Or.inr rfl)))

instance (win : Engine → Option Lane) (z : Lane) (e : Engine) : Decidable (Dec win z e) :=
  inferInstanceAs (Decidable (e.st = .idle ∧ win e = some z ∧ e.headValid z = true))

/-- Some lane is decided this cycle. -/
def decAny (win : Engine → Option Lane) (e : Engine) : Bool :=
  match win e with
  | some w => decide (e.st = .idle) && e.headValid w
  | none   => false

/-! ### Per cycle -/

theorem dec_self (win : Engine → Option Lane) (e : Engine) {w : Lane} (hw : win e = some w) :
    Dec win w e ↔ (e.st = .idle ∧ e.headValid w = true) := by
  constructor
  · rintro ⟨h1, -, h3⟩
    exact ⟨h1, h3⟩
  · rintro ⟨h1, h3⟩
    exact ⟨h1, hw, h3⟩

theorem dec_ne (win : Engine → Option Lane) (e : Engine) {w z : Lane} (hw : win e = some w)
    (hz : z ≠ w) : ¬Dec win z e := by
  rintro ⟨-, h, -⟩
  rw [hw] at h
  exact hz (Option.some.inj h).symm

/-- Lane `z`'s indicator: nonzero only for the winner. -/
theorem dec_term (win : Engine → Option Lane) (e : Engine) {w : Lane} (hw : win e = some w)
    (z : Lane) :
    (if Dec win z e then 1 else 0)
      = if z = w then (if e.st = .idle ∧ e.headValid w = true then 1 else 0) else 0 := by
  by_cases hz : z = w
  · rw [if_pos hz, hz]
    by_cases hc : e.st = .idle ∧ e.headValid w = true
    · rw [if_pos hc, if_pos ((dec_self win e hw).2 hc)]
    · rw [if_neg hc, if_neg (fun h => hc ((dec_self win e hw).1 h))]
  · rw [if_neg hz, if_neg (dec_ne win e hw hz)]

theorem decAny_term (win : Engine → Option Lane) (e : Engine) {w : Lane}
    (hw : win e = some w) :
    (if decAny win e = true then 1 else 0)
      = if e.st = .idle ∧ e.headValid w = true then 1 else 0 := by
  have h : decAny win e = (decide (e.st = .idle) && e.headValid w) := by
    simp only [decAny, hw]
  rw [h]
  by_cases h1 : e.st = .idle <;> by_cases h2 : e.headValid w = true <;> simp [h1, h2]

/-- Exactly one of the five lanes is the winner. -/
theorem sum_ind (w : Lane) (c : Nat) :
    (if L0 = w then c else 0) + (if L1 = w then c else 0) + (if L2 = w then c else 0)
      + (if L3 = w then c else 0) + (if L4 = w then c else 0) = c := by
  rcases lane_cases w with rfl | rfl | rfl | rfl | rfl
  · rw [if_pos (show L0 = L0 from rfl), if_neg (show L1 ≠ L0 by decide),
      if_neg (show L2 ≠ L0 by decide), if_neg (show L3 ≠ L0 by decide),
      if_neg (show L4 ≠ L0 by decide)] <;> omega
  · rw [if_neg (show L0 ≠ L1 by decide), if_pos (show L1 = L1 from rfl),
      if_neg (show L2 ≠ L1 by decide), if_neg (show L3 ≠ L1 by decide),
      if_neg (show L4 ≠ L1 by decide)] <;> omega
  · rw [if_neg (show L0 ≠ L2 by decide), if_neg (show L1 ≠ L2 by decide),
      if_pos (show L2 = L2 from rfl), if_neg (show L3 ≠ L2 by decide),
      if_neg (show L4 ≠ L2 by decide)] <;> omega
  · rw [if_neg (show L0 ≠ L3 by decide), if_neg (show L1 ≠ L3 by decide),
      if_neg (show L2 ≠ L3 by decide), if_pos (show L3 = L3 from rfl),
      if_neg (show L4 ≠ L3 by decide)] <;> omega
  · rw [if_neg (show L0 ≠ L4 by decide), if_neg (show L1 ≠ L4 by decide),
      if_neg (show L2 ≠ L4 by decide), if_neg (show L3 ≠ L4 by decide),
      if_pos (show L4 = L4 from rfl)] <;> omega

theorem decAny_split (win : Engine → Option Lane) (e : Engine) :
    (if decAny win e = true then 1 else 0)
      = (if Dec win L0 e then 1 else 0) + (if Dec win L1 e then 1 else 0)
        + (if Dec win L2 e then 1 else 0) + (if Dec win L3 e then 1 else 0)
        + (if Dec win L4 e then 1 else 0) := by
  cases hw : win e with
  | none => simp [decAny, Dec, hw]
  | some w =>
    rw [decAny_term win e hw, dec_term win e hw L0, dec_term win e hw L1,
      dec_term win e hw L2, dec_term win e hw L3, dec_term win e hw L4, sum_ind]

theorem decOther_split (win : Engine → Option Lane) (i : Lane) (e : Engine) :
    (if decOther win i e = true then 1 else 0) + (if Dec win i e then 1 else 0)
      = (if decAny win e = true then 1 else 0) := by
  cases hw : win e with
  | none => simp [decOther, decAny, Dec, hw]
  | some w =>
    by_cases h3 : w = i
    · rw [h3] at hw
      by_cases h1 : e.st = .idle <;> by_cases h2 : e.headValid i = true <;>
        simp [decOther, decAny, Dec, hw, h1, h2]
    · by_cases h1 : e.st = .idle <;> by_cases h2 : e.headValid w = true <;>
        simp [decOther, decAny, Dec, hw, h1, h2, h3]

/-! ### Along a run -/

theorem cnt_decAny_split (P : Program) (win : Engine → Option Lane) :
    ∀ (n : Nat) (e : Engine),
      cnt P win (fun e => decAny win e = true) n e
        = cnt P win (Dec win L0) n e + cnt P win (Dec win L1) n e
          + cnt P win (Dec win L2) n e + cnt P win (Dec win L3) n e
          + cnt P win (Dec win L4) n e
  | 0, e => by simp [cnt]
  | n + 1, e => by
    have ih := cnt_decAny_split P win n (step P win e)
    have h := decAny_split win e
    have e0 : cnt P win (fun e => decAny win e = true) (n + 1) e
        = (if decAny win e = true then 1 else 0)
          + cnt P win (fun e => decAny win e = true) n (step P win e) := rfl
    have e1 : cnt P win (Dec win L0) (n + 1) e
        = (if Dec win L0 e then 1 else 0) + cnt P win (Dec win L0) n (step P win e) := rfl
    have e2 : cnt P win (Dec win L1) (n + 1) e
        = (if Dec win L1 e then 1 else 0) + cnt P win (Dec win L1) n (step P win e) := rfl
    have e3 : cnt P win (Dec win L2) (n + 1) e
        = (if Dec win L2 e then 1 else 0) + cnt P win (Dec win L2) n (step P win e) := rfl
    have e4 : cnt P win (Dec win L3) (n + 1) e
        = (if Dec win L3 e then 1 else 0) + cnt P win (Dec win L3) n (step P win e) := rfl
    have e5 : cnt P win (Dec win L4) (n + 1) e
        = (if Dec win L4 e then 1 else 0) + cnt P win (Dec win L4) n (step P win e) := rfl
    omega

theorem cnt_decOther_split (P : Program) (win : Engine → Option Lane) (i : Lane) :
    ∀ (n : Nat) (e : Engine),
      cnt P win (fun e => decOther win i e = true) n e + cnt P win (Dec win i) n e
        = cnt P win (fun e => decAny win e = true) n e
  | 0, e => by simp [cnt]
  | n + 1, e => by
    have ih := cnt_decOther_split P win i n (step P win e)
    have h := decOther_split win i e
    have e0 : cnt P win (fun e => decOther win i e = true) (n + 1) e
        = (if decOther win i e = true then 1 else 0)
          + cnt P win (fun e => decOther win i e = true) n (step P win e) := rfl
    have e1 : cnt P win (Dec win i) (n + 1) e
        = (if Dec win i e then 1 else 0) + cnt P win (Dec win i) n (step P win e) := rfl
    have e2 : cnt P win (fun e => decAny win e = true) (n + 1) e
        = (if decAny win e = true then 1 else 0)
          + cnt P win (fun e => decAny win e = true) n (step P win e) := rfl
    omega

theorem cnt_zero_of (P : Program) (win : Engine → Option Lane) (Q : Engine → Prop)
    [DecidablePred Q] (t : Nat) (e : Engine)
    (h : ∀ s, s < t → ¬Q (run P win s e)) : cnt P win Q t e = 0 := by
  rcases Nat.eq_zero_or_pos (cnt P win Q t e) with h0 | hpos
  · exact h0
  · obtain ⟨s, hs, _, hq⟩ := cnt_reach P win Q t e 0 hpos
    exact absurd hq (h s hs)

/-! ### The pigeonhole -/

/-- No decision of `i`, at most one of each other lane ⇒ at most `k − 1` other-lane
decisions. -/
theorem pigeon (P : Program) (win : Engine → Option Lane) (i : Lane) (n : Nat) (e : Engine)
    (hi : cnt P win (Dec win i) n e = 0)
    (h1 : ∀ z, z ≠ i → cnt P win (Dec win z) n e ≤ 1) :
    cnt P win (fun e => decOther win i e = true) n e ≤ K - 1 := by
  have hs := cnt_decAny_split P win n e
  have ho := cnt_decOther_split P win i n e
  have hK : K - 1 = 4 := rfl
  rcases lane_cases i with rfl | rfl | rfl | rfl | rfl
  · have a := h1 L1 (by decide); have b := h1 L2 (by decide)
    have c := h1 L3 (by decide); have d := h1 L4 (by decide); omega
  · have a := h1 L0 (by decide); have b := h1 L2 (by decide)
    have c := h1 L3 (by decide); have d := h1 L4 (by decide); omega
  · have a := h1 L0 (by decide); have b := h1 L1 (by decide)
    have c := h1 L3 (by decide); have d := h1 L4 (by decide); omega
  · have a := h1 L0 (by decide); have b := h1 L1 (by decide)
    have c := h1 L2 (by decide); have d := h1 L4 (by decide); omega
  · have a := h1 L0 (by decide); have b := h1 L1 (by decide)
    have c := h1 L2 (by decide); have d := h1 L3 (by decide); omega

/-- **Lemma A, single-dispatch form.** If no other lane is decided twice while lane `i`
waits, the wait is at most `3(k − 1) + 2 = 14` cycles. -/
theorem lemmaA_once (P : Program) (win : Engine → Option Lane) (i : Lane)
    (hws : ∀ e, e.st = .idle → Ready P i e → win e ≠ none) (t : Nat) (e : Engine)
    (hr : Ready P i e) (hm : NotMid i e)
    (hnd : ∀ s, s < t → ¬Dec win i (run P win s e))
    (hns : ∀ s, s < t → NoStall win (run P win s e))
    (h1 : ∀ z, z ≠ i → cnt P win (Dec win z) t e ≤ 1) :
    t ≤ 3 * (K - 1) + 2 :=
  lemmaA_14 P win i hws t e hr hm hnd hns
    (pigeon P win i t e (cnt_zero_of P win (Dec win i) t e hnd) h1)

end JLane
