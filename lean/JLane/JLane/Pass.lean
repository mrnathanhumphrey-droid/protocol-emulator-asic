import JLane.Port
/-!
# Brick 4 — the pass bound
With no branch-1 refill in flight, `phi ≤ K·L_REFILL − 1 = 19`. Right after a
capture the port is scanning, so a lane that still owes is served again within
`D* = K·L_REFILL = 20` cycles, plus `L_REFILL` per branch-1 refill for another lane.
-/
namespace JLane

/-- No branch-1 refill in flight ⇒ the ranking function is at most 19. -/
theorem phi_le_19 (y : Lane) (p : Port) (h : p.pst = .scan ∨ p.pbr1 = false) :
    phi y p ≤ 19 := by
  by_cases hs : p.pst = .scan
  · have hd := dist_le p.prr y
    have hptr : ptr p = p.prr := by simp [ptr, hs]
    have hphi : phi y p = L_REFILL * dist p.prr y + 3 := by
      simp [phi, hs, rem, hptr]
    rw [hphi]
    show 4 * dist p.prr y + 3 ≤ 19
    omega
  · have hb : p.pbr1 = false := by
      cases h with
      | inl h => exact absurd h hs
      | inr h => exact h
    by_cases hl : p.pl = y
    · have hphi : phi y p = rem p.pst - 1 := by simp [phi, hs, hl]
      have := rem_le p.pst
      omega
    · have hptr : ptr p = nextLane p.pl := by simp [ptr, hs, hb]
      have hd := dist_next p.pl y hl
      have hd4 := dist_le p.pl y
      have hr := rem_le p.pst
      have hphi : phi y p = rem p.pst + L_REFILL * dist (nextLane p.pl) y + 3 := by
        simp [phi, hs, hl, hptr]
      rw [hphi]
      show rem p.pst + 4 * dist (nextLane p.pl) y + 3 ≤ 19
      omega

/-- The wait bound when no branch-1 refill is in flight at the start. -/
theorem port_wait_bound_19 (P : Program) (win : Engine → Option Lane) (y : Lane)
    (hy : P.live y = true) (n : Nat) (e : Engine) (hw : e.wantFetch y = true)
    (hq : e.pst = .scan ∨ e.pbr1 = false)
    (hnh : ∀ i, i < n → ¬Hit y (run P win i e)) :
    n ≤ 19 + chargeSum P win y n e := by
  have h := port_wait P win y hy n e hw hnh
  have h2 := phi_le_19 y (portOf e) hq
  omega

/-- A writeback leaves the dispatched lane owing a slot. -/
theorem wb_owes (P : Program) (win : Engine → Option Lane) (e : Engine) (hw : e.st = .wb) :
    (step P win e).wantFetch e.cur = true := by
  rw [Engine.wantFetch_iff]
  apply owed_pos_of (step P win e) e.cur (e.sel e.cur)
  show actvNext e e.cur (e.sel e.cur) = false
  unfold actvNext
  rw [if_pos ⟨hw, rfl, rfl⟩]

/-- A hit fills the latched slot. -/
theorem hit_fills (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (h : Struct e) (hh : Hit y e) : (step P win e).actv y e.pslot = true := by
  obtain ⟨hc, hl⟩ := hh
  have := step_cap_fills_struct P win e h hc
  rw [hl] at this
  exact this

/-- After a hit the port is scanning. -/
theorem hit_then_scan (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (hh : Hit y e) : (step P win e).pst = .scan := by
  obtain ⟨hc, _⟩ := hh
  show (portNext P e).pst = .scan
  simp [portNext_cap P e hc]

/-- **The pass bound.** After a hit for `y`, if `y` still owes, its next hit comes within
`D*` cycles of this one, plus `L_REFILL` per branch-1 refill for another lane. -/
theorem next_pass (P : Program) (win : Engine → Option Lane) (y : Lane)
    (hy : P.live y = true) (e : Engine) (hh : Hit y e) (n : Nat)
    (hw : (step P win e).wantFetch y = true)
    (hnh : ∀ i, i < n → ¬Hit y (run P win i (step P win e))) :
    n + 1 ≤ DSTAR + chargeSum P win y n (step P win e) := by
  have h := port_wait_bound_19 P win y hy n (step P win e) hw
    (Or.inl (hit_then_scan P win y e hh)) hnh
  have hd : DSTAR = 20 := dstar_val
  omega

end JLane
