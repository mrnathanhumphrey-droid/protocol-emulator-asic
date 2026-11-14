import JLane.EdfB
/-!
# Brick N — branch-1 refills go only to empty heads, one per retirement (stage 5, B)

The branch-1 budget `B` counts port cycles another lane's urgent head refills take. Under the
shipped port that refill serves the winner's empty head; under the ruled scheduler (b′) the
winner never has an empty head, and agent 1's batch retargets the urgent refill to the
earliest-deadline released lane with an empty head (`pf_q`). Both rules share the two facts the
budget rests on, proved here for the modelled rule and stated so the retargeted one only has to
meet `br1_empty`:

* `br1_empty` — a branch-1 grant goes to a lane whose head is empty;
* `head_keep` / `head_valid_no_ret` — a valid head stays valid until its lane retires;
* so between two branch-1 refills to a lane there is a retirement of it: at most one refill per
  late word. `lane_cert.br1_window_count` counts the late words per `23 + B` window (B = 8 on
  usbdev today: two refills per 31 cycles).
-/
namespace JLane

/-- A branch-1 grant (the modelled rule) goes to a lane with an empty head. -/
theorem br1_empty (P : Program) (e : Engine) (w : Lane) (h : br1 P e = some w) :
    e.headValid w = false := by
  unfold br1 at h
  cases hq : e.winq with
  | none => rw [hq] at h; cases h
  | some v =>
    rw [hq] at h
    simp only at h
    split at h
    · rename_i hc
      cases h
      simp only [Bool.and_eq_true, Bool.not_eq_true'] at hc
      exact hc.2
    · cases h

/-- One cycle: a valid head stays valid unless its lane retires. -/
theorem head_keep (P : Program) (win : Engine → Option Lane) (e : Engine) (u : Lane)
    (hv : e.headValid u = true) (hn : ¬IsRet P u e) : (step P win e).headValid u = true := by
  have hn' : ¬(e.st = .wb ∧ u = e.cur ∧ P.ret e.now e.cur = true) := not_ret_form P u e hn
  show actvNext P e u (selNext P e u) = true
  have hs : selNext P e u = e.sel u := by
    unfold selNext
    rw [if_neg hn']
  rw [hs]
  exact actvNext_keep_true P e u (e.sel u) hn' hv

/-- **A valid head stays valid until its lane retires.** With no retirement of `u` in
`[a, a + n)`, `u`'s head valid at `a` is still valid at `a + n` -- so an empty head later means
a retirement in between (one branch-1 refill per late word). -/
theorem head_valid_no_ret (P : Program) (win : Engine → Option Lane) (e0 : Engine) (u : Lane)
    (a : Nat) (hv : (run P win a e0).headValid u = true) :
    ∀ n, (∀ x, a ≤ x → x < a + n → ¬IsRet P u (run P win x e0)) →
      (run P win (a + n) e0).headValid u = true
  | 0, _ => by rw [Nat.add_zero]; exact hv
  | n + 1, h => by
    have ih := head_valid_no_ret P win e0 u a hv n (fun x h1 h2 => h x h1 (by omega))
    have hk := head_keep P win (run P win (a + n) e0) u ih (h (a + n) (by omega) (by omega))
    rw [← run_succ'] at hk
    rw [← Nat.add_assoc]
    exact hk

#print axioms br1_empty
#print axioms head_valid_no_ret

end JLane
