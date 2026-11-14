import JLane.RespClose
/-!
# Brick I — `wb_close`'s program facts from the words (stage 5, step 4)

`wb_close` needs, for each lane, decision spacing (`hsep`) and "the next release comes after
the writeback" (`hrel`), each given the earlier writeback met its response bound. On the
V4b view of a run with ARMs and branches (`run3_proj`) both follow from the words:

* at an ARM's writeback the next release is one past its edge (`arm_release`), and the edge
  is after the writeback: the release is at least `now + 2` — outright;
* at any other writeback the release gap is the word's delay, less one if the lane was just
  rebased (`ext3`).

So with a per-lane spacing `σ`, the word condition is: `σ l ≤ 4` at an ARM, and
`σ l + R l + 1 ≤ dly` at any other word (`SepW`). It is a property of the program's words —
the stage 6 checker evaluates it per lane.
-/
namespace JLane

/-- A word on lane `l` meets the spacing `σ l` under the response bound `R l`. -/
def SepW (σ R : Lane → Nat) (l : Lane) (w : Word) : Prop :=
  (w.op = .arm → σ l ≤ 4) ∧ (w.op ≠ .arm → σ l + R l + 1 ≤ w.dly)

/-- A property of slot words that every fetched word has holds along the run. -/
theorem words_run3 (P2 : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : Engine3 → Option Lane) (Qw : Lane → Word → Prop) :
    ∀ (n : Nat) (X : Engine3), (∀ l s, Qw l (X.x.word l s)) → (∀ y, Qw y.e.pl (fw y)) →
      ∀ l s, Qw l ((run3 P2 fw edge sched n X).x.word l s)
  | 0, _, h0, _ => h0
  | n + 1, X, h0, hfw => by
    refine words_run3 P2 fw edge sched Qw n (step3 P2 fw edge (sched X) X) ?_ hfw
    intro l s
    show Qw l (X.x.wordNext fw l s)
    unfold Engine2.wordNext
    split
    · rename_i hc
      rw [hc.2.1]
      exact hfw X.x
    · exact h0 l s

section
variable (P2 : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
  (hedge : ∀ t l, t + 1 ≤ edge t l) (sched : Engine3 → Option Lane) (X0 : Engine3)
  (hX0 : ArmInv Wn X0) (hf : ∀ y, ArmFragW Wn (fw y))
  (hsw : ∀ X v, sched X = some v → P2.live v = true ∧ X.x.e.ts v ≤ X.x.e.now ∧ X.armed v = false)
  (hss : ∀ y X, ArmInv Wn X → P2.live y = true → X.x.e.ts y ≤ X.x.e.now → X.armed y = false →
    sched X ≠ none)

/-- The release gap of a writeback on the V4b view is `ext3` of the engine at that cycle. -/
theorem gp_armP (y : Lane) (x : Nat) :
    gp (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) y
      (πE X0) x = ext3 P2 edge (run3 P2 fw edge sched x X0) := by
  unfold gp
  have hn := now_run (armP P2 fw edge sched X0)
    (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) x (πE X0)
  show 0 + ext3 P2 edge (run3 P2 fw edge sched
    ((run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) x
      (πE X0)).now - X0.x.e.now) X0) = _
  rw [hn]
  have : (πE X0).now + x - X0.x.e.now = x := by
    show X0.x.e.now + x - X0.x.e.now = x
    omega
  rw [this, Nat.zero_add]

include hedge hX0 hf hsw hss

/-- **The gap at a writeback, from the word.** At a writeback of `y` at `x` on the V4b view:
an ARM's release lands at least two past the writeback; another word's gap is at least its
delay less one. -/
theorem wb_gap_words (σ R : Lane → Nat)
    (hw0 : ∀ l s, SepW σ R l (X0.x.word l s)) (hwf : ∀ y, SepW σ R y.e.pl (fw y))
    (y : Lane) (x : Nat)
    (hwb : IsWB y (run (armP P2 fw edge sched X0)
      (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) x (πE X0))) :
    ((run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) x
        (πE X0)).now + 2 ≤
      (run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) x
        (πE X0)).ts y + gp (armP P2 fw edge sched X0)
          (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) y (πE X0) x ∧
      σ y ≤ 4) ∨
    σ y + R y ≤ gp (armP P2 fw edge sched X0)
      (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) y (πE X0) x := by
  have hpr := run3_proj P2 Wn fw edge hedge sched X0 hX0 hf hsw hss x
  have hI := arm_run3 P2 Wn fw edge hedge sched hf hsw x X0 hX0
  have hW := words_run3 P2 fw edge sched (SepW σ R) x X0 hw0 hwf
  rw [gp_armP, ← hpr]
  rw [← hpr] at hwb
  obtain ⟨hst, hcur⟩ := hwb
  change (run3 P2 fw edge sched x X0).x.e.st = .wb at hst
  change (run3 P2 fw edge sched x X0).x.e.cur = y at hcur
  have hsep := hW y ((run3 P2 fw edge sched x X0).x.e.sel y)
  by_cases harw : (run3 P2 fw edge sched x X0).armWB P2 = true
  · left
    have hop : ((run3 P2 fw edge sched x X0).x.head (run3 P2 fw edge sched x X0).x.e.cur).op
        = .arm := by
      unfold Engine3.armWB at harw
      simp only [Bool.and_eq_true, decide_eq_true_eq] at harw
      exact harw.1.2
    rw [hcur] at hop
    have hdl := hI.2.2.2.2.2 (by rw [hst]; decide)
    have hed := hedge (run3 P2 fw edge sched x X0).x.e.now (run3 P2 fw edge sched x X0).x.e.cur
    refine ⟨?_, hsep.1 hop⟩
    unfold ext3
    rw [if_pos harw]
    show (run3 P2 fw edge sched x X0).x.e.now + 2 ≤ (πE (run3 P2 fw edge sched x X0)).ts y + _
    rw [hcur] at hdl hed ⊢
    omega
  · right
    have hop : ((run3 P2 fw edge sched x X0).x.head y).op ≠ .arm := by
      intro hop
      apply harw
      unfold Engine3.armWB
      rw [← hcur] at hop
      simp [hst, hop, Engine2.retire_arm P2 _ hop]
    have hd := hsep.2 hop
    unfold ext3
    rw [if_neg harw, hcur]
    unfold Engine2.head at hop hd ⊢
    split <;> omega

/-- **`hrel` from the words.** -/
theorem hrel_words (σ R : Lane → Nat) (hσ3 : ∀ l, 3 ≤ σ l)
    (hw0 : ∀ l s, SepW σ R l (X0.x.word l s)) (hwf : ∀ y, SepW σ R y.e.pl (fw y)) :
    ∀ y x, IsWB y (run (armP P2 fw edge sched X0)
        (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) x (πE X0)) →
      (run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) x
        (πE X0)).now ≤
        (run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) x
          (πE X0)).ts y + R y + 2 →
      (run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) x
        (πE X0)).now <
        (run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0)
          (x + 1) (πE X0)).ts y := by
  intro y x hwb hr
  have hts := ts_gap (armP P2 fw edge sched X0)
    (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) y (πE X0) x (x + 1) hwb
    (Nat.lt_succ_self x)
  rcases wb_gap_words P2 Wn fw edge hedge sched X0 hX0 hf hsw hss σ R hw0 hwf y x hwb with
    ⟨h, -⟩ | h
  · omega
  · have := hσ3 y
    omega

/-- **`hsep` from the words.** Two decisions of `z` are at least `σ z` apart, given the first
one's writeback met its bound. -/
theorem hsep_words (σ R : Lane → Nat)
    (hw0 : ∀ l s, SepW σ R l (X0.x.word l s)) (hwf : ∀ y, SepW σ R y.e.pl (fw y)) :
    ∀ z a b, a < b →
      Dec (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) z
        (run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) a
          (πE X0)) →
      Dec (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) z
        (run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) b
          (πE X0)) →
      (run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0)
          (a + 2) (πE X0)).now ≤
        (run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0)
          (a + 2) (πE X0)).ts z + R z + 2 →
      a + σ z ≤ b := by
  intro z a b hab ha hb hr
  have h3 := dec_sep (armP P2 fw edge sched X0)
    (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) (πE X0) z a b hab ha hb
  have hwb := dec_wb (armP P2 fw edge sched X0)
    (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) (πE X0) a z ha
  have hts := ts_gap (armP P2 fw edge sched X0)
    (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) z (πE X0) (a + 2) b hwb (by omega)
  -- z is released at b: it is the winner there
  have hrb := (win3_ready (armP P2 fw edge sched X0) P2 fw edge sched X0 _ z hb.2.1).2
  have hna := now_run (armP P2 fw edge sched X0)
    (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) (a + 2) (πE X0)
  have hnb := now_run (armP P2 fw edge sched X0)
    (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) b (πE X0)
  rcases wb_gap_words P2 Wn fw edge hedge sched X0 hX0 hf hsw hss σ R hw0 hwf z (a + 2) hwb with
    ⟨h, h4⟩ | h
  · omega
  · omega

/-- **Per-lane response bounds for runs with ARMs and branches.** `wb_close` on the V4b view
with `hsep` and `hrel` discharged from the words (`SepW`). Left: the stall budget `S` per
window (0 under (b′), the proved bound under (c)), the multiplicities `m`, and the window
arithmetic `hmul` / `hK` — numbers the stage 6 checker evaluates. -/
theorem wb_close_arm (σ R m : Lane → Nat) (T S : Nat)
    (h0 : X0.x.e.st = .idle) (h0ts : ∀ l, X0.x.e.now ≤ (πE X0).ts l)
    (hσ3 : ∀ l, 3 ≤ σ l)
    (hw0 : ∀ l s, SepW σ R l (X0.x.word l s)) (hwf : ∀ y, SepW σ R y.e.pl (fw y))
    (hS : ∀ y c, P2.live y = true → c + (R y + 1) ≤ T →
      cnt (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0)
        (fun e => stallB (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) e = true) (R y + 1)
        (run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) c
          (πE X0)) ≤ S)
    (hmul : ∀ y z, z ≠ y → R y + 1 ≤ σ z * m z)
    (hK : ∀ y, 3 * (m L0 + m L1 + m L2 + m L3 + m L4 - m y) + S + 3 ≤ R y + 1) :
    ∀ t, t < T → ∀ y, P2.live y = true →
      IsWB y (run (armP P2 fw edge sched X0)
        (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) t (πE X0)) →
      (run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) t
        (πE X0)).now ≤
        (run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) t
          (πE X0)).ts y + R y + 2 :=
  wb_close (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0)
    (πE X0) T S R m σ h0 h0ts (win3_ready _ P2 fw edge sched X0)
    (fun y e _ h => win3_wc _ P2 fw edge sched X0 y e h)
    (fun z => Nat.le_trans (by decide) (hσ3 z)) hS
    (hsep_words P2 Wn fw edge hedge sched X0 hX0 hf hsw hss σ R hw0 hwf)
    (hrel_words P2 Wn fw edge hedge sched X0 hX0 hf hsw hss σ R hσ3 hw0 hwf) hmul hK

end

#print axioms wb_close_arm
#print axioms wb_gap_words
#print axioms hrel_words
#print axioms hsep_words

end JLane
