/-!
# Spacing of refill requests

A lane's refill requests are issued at its writebacks. If consecutive requests are
at least `p` cycles apart, a window can only hold so many of them. This is the
counting step every port-queueing bound uses; `p` stays abstract until PORT_SPEC
fixes the writeback spacing.
-/

namespace JLane

/-- Consecutive entries of a request-time list are at least `p` apart. -/
def Spaced (p : Nat) : List Nat → Prop
  | [] => True
  | [_] => True
  | a :: b :: rest => a + p ≤ b ∧ Spaced p (b :: rest)

/-- In a `p`-spaced list starting at `t`, some entry lies at least `length · p` past `t`. -/
theorem spaced_reach (p : Nat) :
    ∀ (t : Nat) (ts : List Nat), Spaced p (t :: ts) →
      ∃ x ∈ t :: ts, t + ts.length * p ≤ x
  | t, [], _ => ⟨t, List.mem_cons_self .., by simp⟩
  | t, u :: us, h => by
    have ⟨htu, hrest⟩ : t + p ≤ u ∧ Spaced p (u :: us) := h
    obtain ⟨x, hx, hux⟩ := spaced_reach p u us hrest
    refine ⟨x, List.mem_cons_of_mem t hx, ?_⟩
    simp only [List.length_cons, Nat.add_mul, Nat.one_mul]
    omega

/-- A `p`-spaced run of requests inside the window `[a, a + W)` has `length · p < W`. -/
theorem spaced_window (p a W t : Nat) (ts : List Nat) (hs : Spaced p (t :: ts))
    (hw : ∀ x ∈ t :: ts, a ≤ x ∧ x < a + W) : ts.length * p < W := by
  obtain ⟨x, hx, hreach⟩ := spaced_reach p t ts hs
  have ht := hw t (List.mem_cons_self ..)
  have hxw := hw x hx
  omega

/-- If the window is no longer than the spacing, it holds at most one request. -/
theorem spaced_window_single (p a W t : Nat) (ts : List Nat) (hs : Spaced p (t :: ts))
    (hw : ∀ x ∈ t :: ts, a ≤ x ∧ x < a + W) (hWp : W ≤ p) : ts = [] := by
  have h := spaced_window p a W t ts hs hw
  cases ts with
  | nil => rfl
  | cons u us =>
    simp only [List.length_cons, Nat.add_mul, Nat.one_mul] at h
    omega

end JLane
