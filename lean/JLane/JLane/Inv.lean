import JLane.Step
/-!
# Brick 2 — structural invariants
Two facts preserved by every `step`, from which the capture/WB collision in
`actvNext` is unreachable (so Step's write-order choice is immaterial).
-/
namespace JLane

/-- While a refill is in flight, the slot it targets is empty. -/
def InFlightEmpty (e : Engine) : Prop :=
  e.pst ≠ .scan → e.actv e.pl e.pslot = false

/-- During DRIVE and WB, the dispatched lane's head is valid. -/
def DispHeadValid (e : Engine) : Prop :=
  e.st ≠ .idle → e.headValid e.cur = true

/-! ### Small facts about the update functions -/

theorem actvNext_false (e : Engine) (l : Lane) (s : Slot) (hc : e.pst ≠ .cap)
    (h : e.actv l s = false) : actvNext e l s = false := by
  unfold actvNext
  by_cases hw : e.st = .wb ∧ l = e.cur ∧ s = e.sel e.cur
  · rw [if_pos hw]
  · rw [if_neg hw, if_neg (fun h' => hc h'.1), h]

theorem actvNext_true (e : Engine) (l : Lane) (s : Slot) (hw : e.st ≠ .wb)
    (h : e.actv l s = true) : actvNext e l s = true := by
  unfold actvNext
  rw [if_neg (fun h' => hw h'.1)]
  by_cases hc : e.pst = .cap ∧ l = e.pl ∧ s = e.pslot
  · rw [if_pos hc]
  · rw [if_neg hc, h]

theorem selNext_of_not_wb (e : Engine) (l : Lane) (hw : e.st ≠ .wb) :
    selNext e l = e.sel l := by
  unfold selNext
  rw [if_neg (fun h' => hw h'.1)]

/-- Branch 1 fires only on a live lane with an empty head. -/
theorem br1_spec (P : Program) (e : Engine) (w : Lane) (h : br1 P e = some w) :
    P.live w = true ∧ e.headValid w = false := by
  unfold br1 at h
  cases hq : e.winq with
  | none =>
    rw [hq] at h
    dsimp only at h
    cases h
  | some v =>
    rw [hq] at h
    dsimp only at h
    by_cases hc : (P.live v && !e.headValid v) = true
    · rw [if_pos hc] at h
      cases h
      simpa using hc
    · rw [if_neg hc] at h
      cases h

/-- Outside `P_SCAN`, the FSM keeps its latched lane and slot. -/
theorem portNext_keeps (P : Program) (e : Engine) (h : e.pst ≠ .scan) :
    (portNext P e).pl = e.pl ∧ (portNext P e).pslot = e.pslot := by
  cases hp : e.pst with
  | scan => exact absurd hp h
  | req  => simp [portNext, hp]
  | wait => simp [portNext, hp]
  | cap  => simp [portNext, hp]

/-- A scan that issues a refill targets an empty slot. -/
theorem scan_issue_empty (P : Program) (e : Engine) (hp : e.pst = .scan)
    (hne : (portNext P e).pst ≠ .scan) :
    e.actv (portNext P e).pl (portNext P e).pslot = false := by
  revert hne
  unfold portNext
  rw [hp]
  dsimp only
  cases hb : br1 P e with
  | some w =>
    dsimp only
    intro _hne
    exact (br1_spec P e w hb).2
  | none =>
    dsimp only
    by_cases hc : (P.live e.prr && e.wantFetch e.prr) = true
    · rw [if_pos hc]
      intro _hne
      exact fetchSlot_invalid e e.prr (by simp at hc; exact hc.2)
    · rw [if_neg hc]
      intro h
      exact (h (by simp)).elim

/-! ### Preservation -/

theorem inFlightEmpty_step (P : Program) (win : Engine → Option Lane) (e : Engine)
    (h1 : InFlightEmpty e) : InFlightEmpty (step P win e) := by
  unfold InFlightEmpty at h1 ⊢
  intro hne
  change (portNext P e).pst ≠ .scan at hne
  show actvNext e (portNext P e).pl (portNext P e).pslot = false
  cases hp : e.pst with
  | scan =>
    exact actvNext_false e _ _ (by rw [hp]; decide) (scan_issue_empty P e hp hne)
  | req =>
    have hne' : e.pst ≠ .scan := by rw [hp]; decide
    obtain ⟨hl, hs⟩ := portNext_keeps P e hne'
    rw [hl, hs]
    exact actvNext_false e _ _ (by rw [hp]; decide) (h1 hne')
  | wait =>
    have hne' : e.pst ≠ .scan := by rw [hp]; decide
    obtain ⟨hl, hs⟩ := portNext_keeps P e hne'
    rw [hl, hs]
    exact actvNext_false e _ _ (by rw [hp]; decide) (h1 hne')
  | cap =>
    have : (portNext P e).pst = .scan := by simp [portNext, hp]
    exact absurd this hne

theorem dispHeadValid_step (P : Program) (win : Engine → Option Lane) (e : Engine)
    (h2 : DispHeadValid e) : DispHeadValid (step P win e) := by
  unfold DispHeadValid at h2 ⊢
  intro hne
  change (dispNext win e).st ≠ .idle at hne
  show actvNext e (dispNext win e).cur (selNext e (dispNext win e).cur) = true
  cases hs : e.st with
  | wb =>
    have : (dispNext win e).st = .idle := by simp [dispNext, hs]
    exact absurd this hne
  | drive =>
    have hd : (dispNext win e).cur = e.cur := by simp [dispNext, hs]
    have hw : e.st ≠ .wb := by rw [hs]; decide
    rw [hd, selNext_of_not_wb e e.cur hw]
    exact actvNext_true e _ _ hw (h2 (by rw [hs]; decide))
  | idle =>
    have hw : e.st ≠ .wb := by rw [hs]; decide
    revert hne
    unfold dispNext
    rw [hs]
    dsimp only
    cases hwin : win e with
    | none =>
      dsimp only
      intro h
      exact (h (by simp)).elim
    | some w =>
      dsimp only
      by_cases hv : e.headValid w = true
      · rw [if_pos hv]
        intro _hne
        show actvNext e w (selNext e w) = true
        rw [selNext_of_not_wb e w hw]
        exact actvNext_true e w (e.sel w) hw hv
      · rw [if_neg hv]
        intro h
        exact (h (by simp)).elim

/-! ### The bundle, its run, and the collision -/

def Struct (e : Engine) : Prop := InFlightEmpty e ∧ DispHeadValid e

theorem struct_step (P : Program) (win : Engine → Option Lane) (e : Engine)
    (h : Struct e) : Struct (step P win e) := by
  obtain ⟨h1, h2⟩ := h
  exact ⟨inFlightEmpty_step P win e h1, dispHeadValid_step P win e h2⟩

/-- Primed start: port scanning, dispatch idle. Both invariants hold vacuously. -/
theorem struct_init (e : Engine) (hp : e.pst = .scan) (hs : e.st = .idle) : Struct e :=
  ⟨fun h => absurd hp h, fun h => absurd hs h⟩

/-- `n` cycles. -/
def run (P : Program) (win : Engine → Option Lane) : Nat → Engine → Engine
  | 0, e => e
  | n + 1, e => run P win n (step P win e)

theorem struct_run (P : Program) (win : Engine → Option Lane) :
    ∀ (n : Nat) (e : Engine), Struct e → Struct (run P win n e)
  | 0, _, h => h
  | n + 1, e, h => struct_run P win n (step P win e) (struct_step P win e h)

/-- A capture and a WB invalidation never hit the same slot. -/
theorem no_collision (e : Engine) (h1 : InFlightEmpty e) (h2 : DispHeadValid e)
    (hw : e.st = .wb) (hc : e.pst = .cap) :
    ¬(e.st = .wb ∧ e.pl = e.cur ∧ e.pslot = e.sel e.cur) := by
  rintro ⟨_, hl, hs⟩
  have a : e.actv e.pl e.pslot = false := h1 (by rw [hc]; decide)
  have b : e.headValid e.cur = true := h2 (by rw [hw]; decide)
  unfold Engine.headValid at b
  rw [hl, hs, b] at a
  cases a

/-- Every capture lands, unconditionally, on any state satisfying the invariants. -/
theorem step_cap_fills_struct (P : Program) (win : Engine → Option Lane) (e : Engine)
    (h : Struct e) (hc : e.pst = .cap) :
    (step P win e).actv e.pl e.pslot = true := by
  obtain ⟨h1, h2⟩ := h
  by_cases hw : e.st = .wb
  · exact step_cap_fills P win e hc (no_collision e h1 h2 hw hc)
  · exact step_cap_fills P win e hc (fun h' => hw h'.1)

end JLane
