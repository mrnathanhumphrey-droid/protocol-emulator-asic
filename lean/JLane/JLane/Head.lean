import JLane.Count
/-!
# Brick 7 — the head fills first
HeadFirst: an empty head implies an empty spare. With SpareFill (the port fills a
spare only while that lane's head is valid), both are preserved by every step.
So the head is valid exactly when the lane owes ≤ 1 slot, i.e. when its
writebacks are at most its hits + 1.
-/
namespace JLane

def HeadFirst (e : Engine) : Prop :=
  ∀ l, e.headValid l = false → e.spareValid l = false

def SpareFill (e : Engine) : Prop :=
  e.pst ≠ .scan → e.pslot ≠ e.sel e.pl → e.headValid e.pl = true

/-- A valid slot stays valid unless its lane retires this cycle. -/
theorem actvNext_keep_true (P : Program) (e : Engine) (l : Lane) (s : Slot)
    (hn : ¬(e.st = .wb ∧ l = e.cur ∧ P.ret e.now e.cur = true)) (h : e.actv l s = true) :
    actvNext P e l s = true := by
  unfold actvNext
  rw [if_neg (fun h' => hn ⟨h'.1, h'.2.1, h'.2.2.2⟩)]
  by_cases hc : e.pst = .cap ∧ l = e.pl ∧ s = e.pslot
  · rw [if_pos hc]
  · rw [if_neg hc, h]

theorem headFirst_step (P : Program) (win : Engine → Option Lane) (e : Engine)
    (hH : HeadFirst e) (hF : SpareFill e) : HeadFirst (step P win e) := by
  unfold HeadFirst
  intro l hl
  change actvNext P e l (selNext P e l) = false at hl
  show actvNext P e l (!selNext P e l) = false
  by_cases hw : e.st = .wb ∧ l = e.cur ∧ P.ret e.now e.cur = true
  · -- `l` retires: the new spare is the head just invalidated
    have hs : selNext P e l = !e.sel l := by
      unfold selNext
      rw [if_pos hw]
    rw [hs, Bool.not_not]
    unfold actvNext
    rw [if_pos ⟨hw.1, hw.2.1, congrArg e.sel hw.2.1, hw.2.2⟩]
  · have hs : selNext P e l = e.sel l := by
      unfold selNext
      rw [if_neg hw]
    have hA : ∀ s, actvNext P e l s
        = if e.pst = .cap ∧ l = e.pl ∧ s = e.pslot then true else e.actv l s := by
      intro s
      unfold actvNext
      rw [if_neg (fun h => hw ⟨h.1, h.2.1, h.2.2.2⟩)]
    rw [hs, hA] at hl
    rw [hs, hA]
    by_cases hc : e.pst = .cap ∧ l = e.pl
    · obtain ⟨hpc, hlp⟩ := hc
      by_cases hp : e.sel l = e.pslot
      · -- capture into the head: it is valid after all
        rw [if_pos ⟨hpc, hlp, hp⟩] at hl
        cases hl
      · -- capture into the spare: SpareFill says the head was valid
        have hsf := hF (by rw [hpc]; decide) (by rw [← hlp]; exact fun h => hp h.symm)
        unfold Engine.headValid at hsf
        rw [← hlp] at hsf
        rw [if_neg (fun h => hp h.2.2)] at hl
        rw [hl] at hsf
        cases hsf
    · rw [if_neg (fun h => hc ⟨h.1, h.2.1⟩)] at hl
      rw [if_neg (fun h => hc ⟨h.1, h.2.1⟩)]
      exact hH l hl

/-- SpareFill survives a cycle where the in-flight refill is unchanged. -/
theorem spare_keep (P : Program) (e : Engine) (h1 : InFlightEmpty e) (h2 : DispHeadValid e)
    (hF : SpareFill e) (hne : e.pst ≠ .scan) (hsp : e.pslot ≠ selNext P e e.pl) :
    actvNext P e e.pl (selNext P e e.pl) = true := by
  by_cases hw : e.st = .wb ∧ e.pl = e.cur ∧ P.ret e.now e.cur = true
  · -- the lane retires mid-refill: the slot being filled would be the old head,
    -- which is both valid (dispatched) and empty (in flight) — impossible
    exfalso
    have hsel : selNext P e e.pl = !e.sel e.pl := by
      unfold selNext
      rw [if_pos hw]
    rw [hsel] at hsp
    have hps : e.pslot = e.sel e.pl := by
      revert hsp
      cases e.pslot <;> cases e.sel e.pl <;> decide
    have a := h1 hne
    have b := h2 (by rw [hw.1]; decide)
    unfold Engine.headValid at b
    rw [← hw.2.1] at b
    rw [hps, b] at a
    cases a
  · have hsel : selNext P e e.pl = e.sel e.pl := by
      unfold selNext
      rw [if_neg hw]
    rw [hsel] at hsp ⊢
    exact actvNext_keep_true P e e.pl _ hw (hF hne hsp)

theorem spareFill_step (P : Program) (win : Engine → Option Lane) (e : Engine)
    (hS : Struct e) (hF : SpareFill e) : SpareFill (step P win e) := by
  obtain ⟨h1, h2⟩ := hS
  unfold SpareFill at hF ⊢
  intro hne hsp
  change (portNext P e).pst ≠ .scan at hne
  change (portNext P e).pslot ≠ selNext P e (portNext P e).pl at hsp
  show actvNext P e (portNext P e).pl (selNext P e (portNext P e).pl) = true
  cases hp : e.pst with
  | cap =>
    have : (portNext P e).pst = .scan := by simp [portNext, hp]
    exact absurd this hne
  | req =>
    have hne' : e.pst ≠ .scan := by rw [hp]; decide
    obtain ⟨hl, hs⟩ := portNext_keeps P e hne'
    rw [hl, hs] at hsp
    rw [hl]
    exact spare_keep P e h1 h2 hF hne' hsp
  | wait =>
    have hne' : e.pst ≠ .scan := by rw [hp]; decide
    obtain ⟨hl, hs⟩ := portNext_keeps P e hne'
    rw [hl, hs] at hsp
    rw [hl]
    exact spare_keep P e h1 h2 hF hne' hsp
  | scan =>
    cases hb : br1 P e with
    | some w =>
      -- branch 1 fills the head of a lane that is not retiring
      exfalso
      have hsp' : e.sel w ≠ selNext P e w := by
        rw [portNext_br1 P e hp hb] at hsp
        exact hsp
      have hv := (br1_spec P e w hb).2
      unfold Engine.headValid at hv
      by_cases hw : e.st = .wb ∧ w = e.cur ∧ P.ret e.now e.cur = true
      · have b := h2 (by rw [hw.1]; decide)
        unfold Engine.headValid at b
        rw [← hw.2.1, hv] at b
        cases b
      · have hsel : selNext P e w = e.sel w := by
          unfold selNext
          rw [if_neg hw]
        exact hsp' hsel.symm
    | none =>
      by_cases hc : (P.live e.prr && e.wantFetch e.prr) = true
      · have hsp' : e.fetchSlot e.prr ≠ selNext P e e.prr := by
          rw [portNext_br2 P e hp hb hc] at hsp
          exact hsp
        rw [portNext_br2 P e hp hb hc]
        show actvNext P e e.prr (selNext P e e.prr) = true
        by_cases hw : e.st = .wb ∧ e.prr = e.cur ∧ P.ret e.now e.cur = true
        · exfalso
          have b := h2 (by rw [hw.1]; decide)
          unfold Engine.headValid at b
          rw [← hw.2.1] at b
          have hf : e.fetchSlot e.prr = !e.sel e.prr := by
            simp [Engine.fetchSlot, Engine.headValid, b]
          have hsel : selNext P e e.prr = !e.sel e.prr := by
            unfold selNext
            rw [if_pos hw]
          exact hsp' (hf.trans hsel.symm)
        · have hsel : selNext P e e.prr = e.sel e.prr := by
            unfold selNext
            rw [if_neg hw]
          rw [hsel] at hsp' ⊢
          have hv : e.actv e.prr (e.sel e.prr) = true := by
            cases hh : e.actv e.prr (e.sel e.prr)
            · exfalso
              apply hsp'
              simp [Engine.fetchSlot, Engine.headValid, hh]
            · rfl
          exact actvNext_keep_true P e e.prr _ hw hv
      · have : (portNext P e).pst = .scan := by simp [portNext_skip P e hp hb hc]
        exact absurd this hne

/-! ### The bundle -/

def Wf (e : Engine) : Prop := Struct e ∧ HeadFirst e ∧ SpareFill e

theorem wf_step (P : Program) (win : Engine → Option Lane) (e : Engine) (h : Wf e) :
    Wf (step P win e) := by
  unfold Wf at h ⊢
  obtain ⟨hS, hH, hF⟩ := h
  exact ⟨struct_step P win e hS, headFirst_step P win e hH hF, spareFill_step P win e hS hF⟩

theorem wf_run (P : Program) (win : Engine → Option Lane) (n : Nat) :
    ∀ (e : Engine), Wf e → Wf (run P win n e) := by
  induction n with
  | zero => intro e h; exact h
  | succ n ih => intro e h; exact ih (step P win e) (wf_step P win e h)

/-- Primed start: scanning, idle, every slot full. -/
theorem wf_init (e : Engine) (hp : e.pst = .scan) (hs : e.st = .idle)
    (hfull : ∀ l s, e.actv l s = true) : Wf e := by
  unfold Wf HeadFirst SpareFill
  refine ⟨struct_init e hp hs, ?_, ?_⟩
  · intro l h
    unfold Engine.headValid at h
    rw [hfull] at h
    cases h
  · intro h
    exact absurd hp h
  /-- Primed start as the RTL leaves it: live lanes full, dead lanes empty. -/
  theorem wf_init_live (P : Program) (e : Engine) (hp : e.pst = .scan) (hs : e.st = .idle)
      (hlive : ∀ l s, P.live l = true → e.actv l s = true)
      (hdead : ∀ l s, P.live l = false → e.actv l s = false) : Wf e := by
    unfold Wf HeadFirst SpareFill
    refine ⟨struct_init e hp hs, ?_, ?_⟩
    · intro l h
      cases hl : P.live l
      · exact hdead l _ hl
      · unfold Engine.headValid at h
        rw [hlive l _ hl] at h
        cases h
    · intro h
      exact absurd hp h

  theorem owed_full (e : Engine) (l : Lane) (hfull : ∀ s, e.actv l s = true) :
      e.owed l = 0 := by
    simp [Engine.owed, hfull]

/-- Under HeadFirst, owing at most one slot means the head is valid. -/
theorem head_of_owed_le_one (e : Engine) (l : Lane) (hH : HeadFirst e)
    (h : e.owed l ≤ 1) : e.headValid l = true := by
  cases hh : e.headValid l
  · have hs := hH l hh
    unfold Engine.headValid at hh
    unfold Engine.spareValid at hs
    unfold Engine.owed at h
    cases hsel : e.sel l
    · rw [hsel] at hh hs
      have hs' : e.actv l true = false := by simpa using hs
      rw [hh, hs'] at h
      exact absurd h (by decide)
    · rw [hsel] at hh hs
      have hs' : e.actv l false = false := by simpa using hs
      rw [hh, hs'] at h
      exact absurd h (by decide)
  · rfl

/-- **The bridge.** From a primed start, lane `y`'s head is valid whenever its
writebacks are at most its hits + 1. -/
theorem head_valid_of_counts (P : Program) (win : Engine → Option Lane) (y : Lane)
    (n : Nat) (e0 : Engine) (hW : Wf e0) (hfull : ∀ s, e0.actv y s = true)
    (h : cnt P win (IsRet P y) n e0 ≤ cnt P win (Hit y) n e0 + 1) :
    (run P win n e0).headValid y = true := by
  have hS : Struct e0 := by
    have hw := hW
    unfold Wf at hw
    exact hw.1
  have hH : HeadFirst (run P win n e0) := by
    have hw := wf_run P win n e0 hW
    unfold Wf at hw
    exact hw.2.1
  have hrun := owed_run P win y n e0 hS
  have h0 := owed_full e0 y hfull
  exact head_of_owed_le_one _ y hH (by omega)

end JLane
