import JLane.UsbNoStall
/-!
# Brick A — option A: a refill deferred past a no-prefetch head (branch brick, stage 2)

The RTL does not prefetch past a branch head (`want_fetch` l.2798–2801), so a lane can owe a
slot without wanting it: its head is a valid no-prefetch word. This brick proves what happens
then:

* `want_frozen`: with no capture for the lane and no retirement of it, its want is unchanged;
* `npf_hold`: a lane that owes a slot but does not want it keeps a valid no-prefetch head and
  an empty spare, cycle after cycle, until its next retirement;
* `npf_unlock`: at that retirement the head empties, so from the next cycle the lane wants —
  the deferred refill's wait restarts there (`want_step` keeps it wanting until served).
-/
namespace JLane

/-- With no capture for `y` and no retirement of `y`, `y`'s slots, select and flags are
unchanged, so its want is unchanged. -/
theorem want_frozen (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (hn : ¬Hit y e) (hr : ¬(e.st = .wb ∧ y = e.cur ∧ P.ret e.now e.cur = true)) :
    (step P win e).wantFetch y = e.wantFetch y ∧ (step P win e).sel y = e.sel y ∧
      (∀ s, (step P win e).actv y s = e.actv y s) ∧ (∀ s, (step P win e).npf y s = e.npf y s) := by
  unfold Hit at hn
  have hn' : ¬(e.pst = .cap ∧ y = e.pl) := fun h => hn ⟨h.1, h.2.symm⟩
  have hnpf : ∀ s, npfNext P e y s = e.npf y s := fun s => by
    unfold npfNext
    rw [if_neg (fun h' => hn' ⟨h'.1, h'.2.1⟩)]
  have hcap : ∀ s, ¬(e.pst = .cap ∧ y = e.pl ∧ s = e.pslot) := fun s h' => hn' ⟨h'.1, h'.2.1⟩
  have hsel : selNext P e y = e.sel y := by
    unfold selNext
    rw [if_neg hr]
  have hact : ∀ s, actvNext P e y s = e.actv y s := fun s => by
    unfold actvNext
    rw [if_neg (fun h' => hr ⟨h'.1, h'.2.1, h'.2.2.2⟩), if_neg (hcap s)]
  refine ⟨?_, hsel, hact, hnpf⟩
  show (!actvNext P e y (selNext P e y) ||
        (!actvNext P e y (!selNext P e y) && !npfNext P e y (selNext P e y))) = e.wantFetch y
  rw [hsel, hact, hact, hnpf]
  rfl

/-- Owing but not wanting: the head is a valid no-prefetch word and the spare is empty. -/
theorem npf_state (e : Engine) (y : Lane) (ho : 1 ≤ e.owed y) (hw : e.wantFetch y = false) :
    e.headValid y = true ∧ e.spareValid y = false ∧ e.npf y (e.sel y) = true := by
  unfold Engine.wantFetch Engine.headValid Engine.spareValid at *
  unfold Engine.owed at ho
  cases hs : e.sel y <;> cases h0 : e.actv y false <;> cases h1 : e.actv y true <;>
    cases hp0 : e.npf y false <;> cases hp1 : e.npf y true <;> simp_all

/-- **The hold**: from a cycle where `y` owes but does not want, as long as there is neither a
capture for `y` nor a retirement of `y`, it keeps owing, not wanting, with the same head. -/
theorem npf_hold (P : Program) (win : Engine → Option Lane) (y : Lane) (e0 : Engine) (s : Nat)
    (ho : 1 ≤ (run P win s e0).owed y) (hw : (run P win s e0).wantFetch y = false) :
    ∀ k, (∀ i, i < k → ¬Hit y (run P win (s + i) e0) ∧
        ¬((run P win (s + i) e0).st = .wb ∧ y = (run P win (s + i) e0).cur ∧
          P.ret (run P win (s + i) e0).now (run P win (s + i) e0).cur = true)) →
      1 ≤ (run P win (s + k) e0).owed y ∧ (run P win (s + k) e0).wantFetch y = false
  | 0, _ => ⟨ho, hw⟩
  | k + 1, h => by
    obtain ⟨ihk, ihw⟩ := npf_hold P win y e0 s ho hw k (fun i hi => h i (by omega))
    obtain ⟨hnh, hnr⟩ := h k (Nat.lt_succ_self k)
    obtain ⟨hw', hsel, hact, _⟩ := want_frozen P win y _ hnh hnr
    have hrun : run P win (s + (k + 1)) e0 = step P win (run P win (s + k) e0) := by
      show run P win ((s + k) + 1) e0 = _
      exact run_succ' P win (s + k) e0
    rw [hrun]
    refine ⟨?_, by rw [hw']; exact ihw⟩
    unfold Engine.owed at ihk ⊢
    rw [hact, hact]
    exact ihk

/-- **The unlock**: a retirement of `y` from the no-prefetch hold empties its head, so the lane
wants from the next cycle on — and the word that retired was the no-prefetch head. -/
theorem npf_unlock (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (hS : Struct e) (ho : 1 ≤ e.owed y) (hw : e.wantFetch y = false) (hn : ¬Hit y e)
    (hr : e.st = .wb ∧ y = e.cur ∧ P.ret e.now e.cur = true) :
    (step P win e).wantFetch y = true ∧ e.npf y (e.sel y) = true := by
  obtain ⟨hv, hsp, hnpf⟩ := npf_state e y ho hw
  refine ⟨?_, hnpf⟩
  apply Engine.want_of_head
  unfold Hit at hn
  have hcap : ¬(e.pst = .cap ∧ y = e.pl ∧ (!e.sel y) = e.pslot) := fun h' => hn ⟨h'.1, h'.2.1.symm⟩
  show actvNext P e y (selNext P e y) = false
  have hsel : selNext P e y = !e.sel y := by
    unfold selNext
    rw [if_pos hr]
  rw [hsel]
  unfold actvNext
  rw [if_neg (fun h' => by
    have := h'.2.2.1
    rw [← hr.2.1] at this
    cases hs : e.sel y <;> rw [hs] at this <;> cases this), if_neg hcap]
  unfold Engine.spareValid at hsp
  exact hsp

#print axioms want_frozen
#print axioms npf_hold
#print axioms npf_unlock

end JLane
