import JLane.RespWinN
import JLane.EdfB
/-!
# Brick Y — the response bound counting only EDF-earlier decisions (Wilson 11-15, RespWinN item 4)

`RespWinN.wb_bound_win_n` charges lane `y`'s wait with EVERY other lane's decision in a
`K`-window. A lane spaced at D* = 20 whose own response is up to 14 can be decided twice in a
15-cycle window, so `M` doubles, `K = 3M + S + 3` goes from 15 to 27 and the certificate's
fixpoint diverges: the 14 images with no R (8 left after the drain table, b7d0466).

The RTL's scheduler is EDF on the absolute deadline `ts + D_sched` (`EdfB.EdfBeatsB`): another
lane beats a released, head-valid `y` only with a strictly EARLIER deadline. Past `y`'s release
plus its lateness `L`, `y`'s head is valid (GapRun's certificate, hypothesis `hv`), so every other
decision in that stretch is EDF-earlier than `y`'s current word. Here:

* `decEdf` — another lane is decided with a deadline strictly earlier than `y`'s;
* `cnt_mono_run` — a count along a run is monotone under pointwise implication;
* `wb_bound_edf` — `wb_bound_win_n` with the window placed after release + `L` and `M`
  counting only `decEdf`: every writeback of `y` lands within `L + K + 1` of its release,
  `K ≥ 3M + S + 3`.

Each other lane `z` has only so many words whose deadline beats `y`'s current one: their
timestamps lie below `ts y + ds y - ds z`, and a word decided in the window was released no more
than `z`'s own response before it. That count does not grow with `K` -- the doubling is gone.
The counting side is evaluated by the certificate (`model/branch_budget.py`), as `hM` is for
`wb_bound_win_n`.
-/
namespace JLane

/-- Another lane is decided this cycle with an absolute deadline strictly earlier than `y`'s. -/
def decEdf (ds : Lane → Nat) (win : Engine → Option Lane) (y : Lane) (e : Engine) : Bool :=
  match win e with
  | some w => decide (e.st = .idle) && decide (w ≠ y) && e.headValid w &&
      decide (e.ts w + ds w < e.ts y + ds y)
  | none   => false

/-- A count along a run is monotone under pointwise implication on the run's states. -/
theorem cnt_mono_run (P : Program) (win : Engine → Option Lane) (Q Q' : Engine → Prop)
    [DecidablePred Q] [DecidablePred Q'] :
    ∀ (n : Nat) (e : Engine), (∀ s, s < n → Q (run P win s e) → Q' (run P win s e)) →
      cnt P win Q n e ≤ cnt P win Q' n e
  | 0, _, _ => Nat.le_refl 0
  | n + 1, e, h => by
    have ih := cnt_mono_run P win Q Q' n (step P win e)
      (fun s hs hq => h (s + 1) (by omega) hq)
    have h0 : Q e → Q' e := h 0 (by omega)
    show (if Q e then 1 else 0) + cnt P win Q n (step P win e)
        ≤ (if Q' e then 1 else 0) + cnt P win Q' n (step P win e)
    by_cases hq : Q e
    · rw [if_pos hq, if_pos (h0 hq)]
      omega
    · rw [if_neg hq]
      split <;> omega

/-- **Response bound, EDF-earlier decisions only.** -/
theorem wb_bound_edf (P : Program) (win : Engine → Option Lane) (e0 : Engine)
    (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l) (y : Lane) (hy : P.live y = true)
    (ds : Lane → Nat) (hedf : EdfBeatsB P ds win y)
    (L M S K : Nat) (hK : 3 * M + S + 3 ≤ K)
    (t : Nat) (hwb : IsWB y (run P win t e0))
    (hfree : ∀ w, w + 2 < t → IsWB y (run P win w e0) →
      (run P win w e0).now < (run P win t e0).ts y)
    (hv : ∀ x, x + 2 ≤ t → (run P win x e0).ts y + L ≤ (run P win x e0).now →
      (run P win x e0).headValid y = true)
    (hM : ∀ c, c + K + 2 ≤ t → (run P win (c + K) e0).ts y + L ≤ (run P win c e0).now →
      cnt P win (fun e => decEdf ds win y e = true) K (run P win c e0) ≤ M)
    (hS : ∀ c, c + K + 2 ≤ t → cnt P win (fun e => noDecB win e = true) K (run P win c e0) ≤ S) :
    (run P win t e0).now ≤ (run P win t e0).ts y + L + K + 1 := by
  obtain ⟨D, rfl, hdec⟩ := wb_back P win e0 h0 t y hwb
  obtain ⟨hts2, hnow2⟩ := dec_ts P win e0 D y hdec
  rw [hts2, hnow2]
  rw [hts2] at hfree
  by_cases hfit : (run P win D e0).now + 1 ≤ (run P win D e0).ts y + L + K
  · omega
  · exfalso
    have hnD := now_run P win D e0
    have hts0 := ts_mono P win y e0 0 D (Nat.zero_le D)
    have h00 : (run P win 0 e0).ts y = e0.ts y := rfl
    have h0y := h0ts y
    obtain ⟨c, rfl⟩ : ∃ c, D = c + K := ⟨D - K, by omega⟩
    have hnc := now_run P win c e0
    have noWB : ∀ w, c ≤ w → w < c + K → ¬IsWB y (run P win w e0) := by
      intro w hcw hwD hw
      have h1 := hfree w (by omega) hw
      have h2 := now_run P win w e0
      omega
    -- every cycle of the window is past y's release plus its lateness
    have hpast : ∀ x, c ≤ x → x ≤ c + K →
        (run P win x e0).ts y + L ≤ (run P win x e0).now := by
      intro x hcx hxD
      have h1 := ts_mono P win y e0 x (c + K) hxD
      have h2 := now_run P win x e0
      omega
    have hrdy : Ready P y (run P win c e0) := by
      refine ⟨hy, ?_⟩
      have := hpast c (Nat.le_refl c) (by omega)
      omega
    have hmid : NotMid y (run P win c e0) := by
      unfold NotMid
      rintro ⟨hne, hcur⟩
      cases hs : (run P win c e0).st with
      | idle => exact hne hs
      | wb => exact noWB c (Nat.le_refl c) (by omega) ⟨hs, hcur⟩
      | drive =>
        have h1 := step_drive P win (run P win c e0) hs
        apply noWB (c + 1) (by omega) (by omega)
        rw [run_succ']
        exact ⟨h1.1, h1.2.trans hcur⟩
    have hnd : ∀ s, s < K → ¬Dec win y (run P win s (run P win c e0)) := by
      intro s hs hds
      rw [← run_add] at hds
      have hw2 := dec_wb P win e0 (c + s) y hds
      rcases Nat.lt_or_ge (c + s + 2) (c + K) with hlt | hge
      · exact noWB (c + s + 2) (by omega) hlt hw2
      · have hidle : (run P win (c + K) e0).st = .idle := by
          obtain ⟨h1, -, -⟩ := hdec
          exact h1
        have hst1 : (run P win (c + s + 1) e0).st = .drive := by
          rw [run_succ']
          exact (step_of_dec P win _ y hds).1
        have hst2 : (run P win (c + s + 2) e0).st = .wb := by
          obtain ⟨h, -⟩ := hw2
          exact h
        have : c + K = c + s + 1 ∨ c + K = c + s + 2 := by omega
        rcases this with h | h
        · rw [h, hst1] at hidle
          cases hidle
        · rw [h, hst2] at hidle
          cases hidle
    -- in the window every other decision is EDF-earlier than y's current word
    have hsub : cnt P win (fun e => decOther win y e = true) K (run P win c e0)
        ≤ cnt P win (fun e => decEdf ds win y e = true) K (run P win c e0) := by
      apply cnt_mono_run
      intro s hs hq
      rw [← run_add] at hq ⊢
      have hp := hpast (c + s) (by omega) (by omega)
      have hrd : Ready P y (run P win (c + s) e0) := ⟨hy, by omega⟩
      have hvy := hv (c + s) (by omega) hp
      unfold decOther at hq
      unfold decEdf
      cases hw : win (run P win (c + s) e0) with
      | none => rw [hw] at hq; cases hq
      | some w =>
        rw [hw] at hq
        simp only [Bool.and_eq_true, decide_eq_true_eq] at hq ⊢
        obtain ⟨⟨hid, hne⟩, hvw⟩ := hq
        exact ⟨⟨⟨hid, hne⟩, hvw⟩, hedf _ w hw hne hrd hvy⟩
    have hA := lemmaA_n P win y K (run P win c e0) hrdy hmid hnd
    have hm := hM c (by omega) (by
      have := hpast c (Nat.le_refl c) (by omega)
      have h1 := ts_mono P win y e0 c (c + K) (by omega)
      omega)
    have hs := hS c (by omega)
    omega

#print axioms cnt_mono_run
#print axioms wb_bound_edf

end JLane
