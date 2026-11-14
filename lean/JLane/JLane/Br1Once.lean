import JLane.Br1Sep
/-!
# Brick B1 — at most one branch-1 refill per late word (Wilson 11-14, the k-lane budget, step 1)

The branch-1 budget `B` of an image is certified per image (Wilson 11-14, option 1): the checker
counts, per window of `23 + B` cycles, the branch-1 refills the branch lanes' late words can
take. What it counts rests on one fact, proved here for **both prefetch rules** (it uses only
`br1`'s own test, the scan's re-check `live & !l_actv[hix]`, l.3264):

* `br1_once` — **between two branch-1 refills of the same lane, that lane retires.** The first
  refill is issued into the lane's head slot (`pslot := sel`); the port runs REQ → WAIT → CAP, so
  the next scan is four cycles on; with no retirement the select does not move, the capture fills
  exactly the head (`hit_fills`), the head stays valid (`head_valid_no_ret`), and a second
  branch-1 refill needs an empty head (`br1_empty`).

So a lane takes at most one branch-1 refill per late word (per retirement), whatever the
scheduler or the prefetch target -- the per-window count is then a matter of the lane's
release gaps and lateness, which the certificate evaluates per image.
-/
namespace JLane

/-- A branch-1 refill for lane `u` is issued this cycle. -/
def Br1To (P : Program) (u : Lane) (e : Engine) : Prop :=
  e.pst = .scan ∧ br1 P e = some u

instance (P : Program) (u : Lane) (e : Engine) : Decidable (Br1To P u e) :=
  inferInstanceAs (Decidable (e.pst = .scan ∧ br1 P e = some u))

section
variable (P : Program) (win : Engine → Option Lane) (e0 : Engine) (u : Lane)

/-- With no retirement of `u` over `[a, a + n)`, its select is unchanged. -/
theorem sel_keep_run (a : Nat) :
    ∀ n, (∀ x, a ≤ x → x < a + n → ¬IsRet P u (run P win x e0)) →
      (run P win (a + n) e0).sel u = (run P win a e0).sel u
  | 0, _ => by rw [Nat.add_zero]
  | n + 1, h => by
    have ih := sel_keep_run a n (fun x h1 h2 => h x h1 (by omega))
    have hn := not_ret_form P u _ (h (a + n) (by omega) (by omega))
    rw [← Nat.add_assoc, run_succ']
    show selNext P (run P win (a + n) e0) u = _
    unfold selNext
    rw [if_neg hn]
    exact ih

/-- The port after a branch-1 issue for `u` at `a`: REQ, WAIT, CAP, still serving `u`'s slot
`sel u` (as it was at `a`). -/
theorem br1_port (a : Nat) (ha : Br1To P u (run P win a e0)) :
    (run P win (a + 1) e0).pst = .req ∧ (run P win (a + 2) e0).pst = .wait ∧
    (run P win (a + 3) e0).pst = .cap ∧ (run P win (a + 3) e0).pl = u ∧
    (run P win (a + 3) e0).pslot = (run P win a e0).sel u := by
  obtain ⟨hsc, hb⟩ := ha
  have h1 : (run P win (a + 1) e0).pst = .req ∧ (run P win (a + 1) e0).pl = u ∧
      (run P win (a + 1) e0).pslot = (run P win a e0).sel u := by
    rw [run_succ']
    show (portNext P (run P win a e0)).pst = .req ∧ (portNext P (run P win a e0)).pl = u ∧
      (portNext P (run P win a e0)).pslot = _
    simp [portNext, hsc, hb]
  have h2 : (run P win (a + 2) e0).pst = .wait ∧ (run P win (a + 2) e0).pl = u ∧
      (run P win (a + 2) e0).pslot = (run P win a e0).sel u := by
    show (run P win (a + 1 + 1) e0).pst = .wait ∧ (run P win (a + 1 + 1) e0).pl = u ∧
      (run P win (a + 1 + 1) e0).pslot = _
    rw [run_succ']
    show (portNext P (run P win (a + 1) e0)).pst = .wait ∧
      (portNext P (run P win (a + 1) e0)).pl = u ∧ (portNext P (run P win (a + 1) e0)).pslot = _
    simp [portNext, h1.1, h1.2.1, h1.2.2]
  have h3 : (run P win (a + 3) e0).pst = .cap ∧ (run P win (a + 3) e0).pl = u ∧
      (run P win (a + 3) e0).pslot = (run P win a e0).sel u := by
    show (run P win (a + 2 + 1) e0).pst = .cap ∧ (run P win (a + 2 + 1) e0).pl = u ∧
      (run P win (a + 2 + 1) e0).pslot = _
    rw [run_succ']
    show (portNext P (run P win (a + 2) e0)).pst = .cap ∧
      (portNext P (run P win (a + 2) e0)).pl = u ∧ (portNext P (run P win (a + 2) e0)).pslot = _
    simp [portNext, h2.1, h2.2.1, h2.2.2]
  exact ⟨h1.1, h2.1, h3.1, h3.2.1, h3.2.2⟩

/-- **At most one branch-1 refill per late word.** Two branch-1 refills of `u` (at `a < b`)
have a retirement of `u` between them: it is not the case that `u` never retires in `[a, b)`. -/
theorem br1_once (hS : Struct e0) (a b : Nat) (hab : a < b)
    (ha : Br1To P u (run P win a e0)) (hb : Br1To P u (run P win b e0)) :
    ¬(∀ x, a ≤ x → x < b → ¬IsRet P u (run P win x e0)) := by
  intro hno
  obtain ⟨hp1, hp2, hp3, hpl, hps⟩ := br1_port P win e0 u a ha
  -- the next scan is four cycles on
  have hb4 : a + 4 ≤ b := by
    have hbs := hb.1
    rcases Nat.lt_or_ge b (a + 4) with hlt | hge
    · exfalso
      have : b = a + 1 ∨ b = a + 2 ∨ b = a + 3 := by omega
      rcases this with h | h | h <;> rw [h] at hbs
      · rw [hp1] at hbs; cases hbs
      · rw [hp2] at hbs; cases hbs
      · rw [hp3] at hbs; cases hbs
    · exact hge
  -- the capture at a + 3 fills u's head
  have hsel3 : (run P win (a + 3) e0).sel u = (run P win a e0).sel u :=
    sel_keep_run P win e0 u a 3 (fun x h1 h2 => hno x h1 (by omega))
  have hsel4 : (run P win (a + 4) e0).sel u = (run P win a e0).sel u :=
    sel_keep_run P win e0 u a 4 (fun x h1 h2 => hno x h1 (by omega))
  have hfill : (run P win (a + 4) e0).actv u ((run P win a e0).sel u) = true := by
    have hS3 := struct_run P win (a + 3) e0 hS
    have := hit_fills P win u (run P win (a + 3) e0) hS3 ⟨hp3, hpl⟩
    rw [hps] at this
    show (run P win (a + 3 + 1) e0).actv u _ = true
    rw [run_succ']
    exact this
  have hv4 : (run P win (a + 4) e0).headValid u = true := by
    show (run P win (a + 4) e0).actv u ((run P win (a + 4) e0).sel u) = true
    rw [hsel4]
    exact hfill
  -- valid until b, yet the refill at b needs it empty
  obtain ⟨n, rfl⟩ : ∃ n, b = a + 4 + n := ⟨b - (a + 4), by omega⟩
  have hvb := head_valid_no_ret P win e0 u (a + 4) hv4 n
    (fun x h1 h2 => hno x (by omega) h2)
  have hempty := br1_empty P _ u hb.2
  rw [hvb] at hempty
  cases hempty

/-- An occurrence inside a window counts. -/
theorem cnt_pos_of (Q : Engine → Prop) [DecidablePred Q] (e : Engine) (s t : Nat) (hst : s < t)
    (hq : Q (run P win s e)) : 1 ≤ cnt P win Q t e := by
  obtain ⟨j, rfl⟩ : ∃ j, t = s + (j + 1) := ⟨t - s - 1, by omega⟩
  rw [cnt_add P win Q s (j + 1) e]
  have h1 : cnt P win Q (j + 1) (run P win s e)
      = (if Q (run P win s e) then 1 else 0) + cnt P win Q j (step P win (run P win s e)) := rfl
  rw [h1, if_pos hq]
  omega

/-- **The count: in any window, a lane's branch-1 refills are at most its retirements plus one**
(both prefetch rules). The certificate bounds the retirements of each branch lane per window
from its gaps; this turns that into the branch-1 budget `B`. -/
theorem br1_count (hS : Struct e0) :
    ∀ m a, cnt P win (Br1To P u) m (run P win a e0) ≤ cnt P win (IsRet P u) m (run P win a e0) + 1 := by
  suffices H : ∀ N m a, m ≤ N →
      cnt P win (Br1To P u) m (run P win a e0) ≤ cnt P win (IsRet P u) m (run P win a e0) + 1 from
    fun m a => H m m a (Nat.le_refl m)
  intro N
  induction N with
  | zero =>
    intro m a hm
    have : m = 0 := by omega
    subst this
    simp [cnt]
  | succ N ih =>
    intro m a hm
    cases m with
    | zero => simp [cnt]
    | succ k =>
      have eB : cnt P win (Br1To P u) (k + 1) (run P win a e0)
          = (if Br1To P u (run P win a e0) then 1 else 0)
            + cnt P win (Br1To P u) k (run P win (a + 1) e0) := by
        rw [run_succ']
        rfl
      have eR : cnt P win (IsRet P u) (k + 1) (run P win a e0)
          = (if IsRet P u (run P win a e0) then 1 else 0)
            + cnt P win (IsRet P u) k (run P win (a + 1) e0) := by
        rw [run_succ']
        rfl
      rw [eB, eR]
      by_cases hba : Br1To P u (run P win a e0)
      · rw [if_pos hba]
        -- the first refill after a
        rcases Nat.eq_zero_or_pos (cnt P win (Br1To P u) k (run P win (a + 1) e0)) with h0 | hpos
        · rw [h0]
          omega
        · obtain ⟨s0, hs0k, hc0, hq0⟩ := cnt_reach P win (Br1To P u) k (run P win (a + 1) e0) 0 hpos
          rw [← run_add] at hq0
          -- a retirement in [a, a + 1 + s0)
          have hret : 1 ≤ cnt P win (IsRet P u) (s0 + 1) (run P win a e0) := by
            rcases Nat.eq_zero_or_pos (cnt P win (IsRet P u) (s0 + 1) (run P win a e0)) with hz | hp
            · exfalso
              apply br1_once P win e0 u hS a (a + 1 + s0) (by omega) hba hq0
              intro x hx1 hx2 hr
              have := cnt_pos_of P win (IsRet P u) (run P win a e0) (x - a) (s0 + 1) (by omega)
                (by rw [← run_add]; rw [show a + (x - a) = x by omega]; exact hr)
              omega
            · exact hp
          -- split both counts at a + 1 + s0
          have hsplitB := cnt_add P win (Br1To P u) s0 (k - s0) (run P win (a + 1) e0)
          rw [show s0 + (k - s0) = k by omega, hc0, ← run_add] at hsplitB
          have hsplitR := cnt_add P win (IsRet P u) (s0 + 1) (k - s0) (run P win a e0)
          rw [show s0 + 1 + (k - s0) = k + 1 by omega, ← run_add,
            show a + (s0 + 1) = a + 1 + s0 by omega] at hsplitR
          have hih := ih (k - s0) (a + 1 + s0) (by omega)
          have eR1 : cnt P win (IsRet P u) (k + 1) (run P win a e0)
              = (if IsRet P u (run P win a e0) then 1 else 0)
                + cnt P win (IsRet P u) k (run P win (a + 1) e0) := by
            rw [run_succ']
            rfl
          omega
      · rw [if_neg hba]
        have hih := ih k (a + 1) (by omega)
        split <;> omega

end

#print axioms br1_port
#print axioms br1_once
#print axioms br1_count

end JLane
