import JLane.Refine
/-!
# Brick V4b-ST — the self-timed byte is a V4b run (Wilson 11-08 condition 3, ruled 11-12)

v2 bundle 2: an unclocked SHIFT / SHIFTIN with `mod[1]`, or a SHIFTI, is HELD on every
dispatch until its last bit (`ck_hold`'s `st_act` arm, `pe_engine.v` l.2200), each bit a
dispatch paced by the lane timestamp. In V4b terms that is **a sequence of non-retiring
writebacks ending in a retire**: V4b's `Program.ret` is false on the held bits, true on the
last.

`step2_proj_st`: on words that are ordinary, looping re-arm or self-timed, each with a delay
at least the lane's minimum `dly`, one v2 cycle is one V4b cycle of a program whose `ret`
is the v2 `retire` and whose `ext` is the word's delay above `dly`. `run2_proj_st` makes that
one program for the whole run, time-indexed along the trajectory (as `win1` is in
`Refine.lean`). `dstar39_st`: the hypothesis-free `d ≥ 39` theorem for v2 runs with
self-timed bytes, **for every last-bit and stuff-slot pattern** (`Program2.stl`, `.stuff`)
and every per-word delay `≥ dly`.

Scope: the model has no USB re-anchor (declared exclusion, `State.lean`, Wilson 11-12): these
theorems are for runs without it. Branch opcodes, clocked actions and chaining re-arms are
outside the fragment.
-/
namespace JLane

/-! ### The fragment -/

/-- A word on lane `l` in the self-timed fragment: ordinary, looping re-arm or self-timed,
with a delay of at least the lane's minimum. -/
def StFragW (dly : Lane → Nat) (l : Lane) (w : Word) : Prop :=
  (w.op = .ord ∨ w.op = .loopRe ∨ w.op = .st) ∧ dly l ≤ w.dly

/-- Every slot holds a fragment word. -/
def StFrag (dly : Lane → Nat) (x : Engine2) : Prop :=
  (∀ l s, StFragW dly l (x.word l s)) ∧ x.e.NoNpf

/-- Plain words are in the fragment. -/
theorem stFragW_of_plain {dly : Lane → Nat} {l : Lane} {w : Word} (h : PlainW dly l w) :
    StFragW dly l w := by
  refine ⟨?_, by rw [h.2]; exact Nat.le_refl _⟩
  rcases h.1 with h1 | h1
  · exact Or.inl h1
  · exact Or.inr (Or.inl h1)

namespace Engine2

theorem op_not_chain_st {dly : Lane → Nat} {l : Lane} {w : Word} (h : StFragW dly l w) :
    w.op ≠ .chainRe := by
  rcases h.1 with h1 | h1 | h1 <;> rw [h1] <;> decide

theorem op_not_br_st {dly : Lane → Nat} {l : Lane} {w : Word} (h : StFragW dly l w) :
    w.op ≠ .br := by
  rcases h.1 with h1 | h1 | h1 <;> rw [h1] <;> decide

theorem isClk_frag (dly : Lane → Nat) (x : Engine2) (h : StFrag dly x) : x.isClk = false := by
  unfold isClk head
  rcases (h.1 x.e.cur (x.e.sel x.e.cur)).1 with h1 | h1 | h1 <;> rw [h1]

/-- In the fragment the writeback adds the head word's whole delay. -/
theorem wbDly_frag (P : Program2) (dly : Lane → Nat) (x : Engine2) (h : StFrag dly x) :
    x.wbDly P = (x.head x.e.cur).dly := by
  unfold wbDly
  rw [if_neg (fun h' => by rw [isClk_frag dly x h] at h'; exact Bool.noConfusion h'.1)]

theorem wantFetch_frag (dly : Lane → Nat) (x : Engine2) (h : StFrag dly x) (l : Lane) :
    x.wantFetch l = x.e.wantFetch l := by
  unfold wantFetch Engine.wantFetch
  have hc : (x.head l).op ≠ .chainRe := op_not_chain_st (h.1 l (x.e.sel l))
  have hb : (x.head l).op ≠ .br := op_not_br_st (h.1 l (x.e.sel l))
  rw [h.2 l (x.e.sel l)]
  cases hv : x.e.headValid l
  · simp
  · rw [if_neg (by simp), if_neg hc, if_neg hb]
    simp

end Engine2

/-- The prefetch FSM reads its program only through `live`. -/
theorem portNextW_live (Q Q' : Program) (h : Q.live = Q'.live) (want : Lane → Bool)
    (e : Engine) : portNextW Q want e = portNextW Q' want e := by
  unfold portNextW br1
  rw [h]

/-! ### One cycle -/

/-- **Refinement, self-timed.** On fragment words, one v2 cycle is one V4b cycle of any
program `Q` with the same liveness and minimum delays whose retire flag is the v2 `retire`
and whose extra is the word's delay above the minimum, at this cycle. -/
theorem step2_proj_st (P : Program2) (Q : Program) (dly : Lane → Nat) (fw : Engine2 → Word)
    (w : Option Lane) (x : Engine2) (h : StFrag dly x)
    (hl : Q.live = P.live) (hd : Q.dly = dly)
    (hr : Q.ret x.e.now x.e.cur = x.retire P)
    (he : Q.ext x.e.now x.e.cur = (x.head x.e.cur).dly - dly x.e.cur)
    (hq : Q.fnpf x.e = decide ((fw x).op = .br)) :
    proj (step2 P fw w x) = step Q (fun _ => w) (proj x) := by
  have hn : npf2 fw x = npfNext Q x.e := npf2_eq fw x Q hq
  have hp : portNextW (P.toP (fun _ => 0)) x.wantFetch x.e = portNext Q x.e := by
    rw [portNextW_congr _ _ _ _ (Engine2.wantFetch_frag dly x h), ← portNextW_v1]
    exact portNextW_live _ _ (by rw [hl]; rfl) _ _
  have ha : x.actvNext P = actvNext Q x.e := by
    funext l s
    unfold Engine2.actvNext actvNext
    rw [hr]
    by_cases h1 : x.e.st = .wb <;> by_cases h2 : x.retire P = true <;>
      by_cases h3 : l = x.e.cur <;> by_cases h4 : s = x.e.sel x.e.cur <;> simp [h1, h2, h3, h4]
  have hs : x.selNext P = selNext Q x.e := by
    funext l
    unfold Engine2.selNext selNext
    rw [hr]
    by_cases h1 : x.e.st = .wb <;> by_cases h2 : x.retire P = true <;>
      by_cases h3 : l = x.e.cur <;> simp [h1, h2, h3]
  have ht : x.tsNext P = tsNext Q x.e := by
    funext l
    unfold Engine2.tsNext tsNext
    by_cases hc : x.e.st = .wb ∧ l = x.e.cur
    · rw [if_pos hc, if_pos hc, hc.2, Engine2.wbDly_frag P dly x h, hd, he]
      have hle := (h.1 x.e.cur (x.e.sel x.e.cur)).2
      unfold Engine2.head
      omega
    · rw [if_neg hc, if_neg hc]
  show ({ now := x.e.now + 1, actv := x.actvNext P, sel := x.selNext P, ts := x.tsNext P,
          pst := (portNextW (P.toP (fun _ => 0)) x.wantFetch x.e).pst,
          pl := (portNextW (P.toP (fun _ => 0)) x.wantFetch x.e).pl,
          prr := (portNextW (P.toP (fun _ => 0)) x.wantFetch x.e).prr,
          pbr1 := (portNextW (P.toP (fun _ => 0)) x.wantFetch x.e).pbr1,
          pslot := (portNextW (P.toP (fun _ => 0)) x.wantFetch x.e).pslot,
          winq := w, st := (dispNext (fun _ => w) x.e).st,
          cur := (dispNext (fun _ => w) x.e).cur,
          npf := npf2 fw x } : Engine) = step Q (fun _ => w) x.e
  rw [hp, ha, hs, ht, hn]
  rfl

/-- The fragment is preserved when every fetched word is in it. -/
theorem frag_step (P : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (w : Option Lane) (x : Engine2) (h : StFrag dly x)
    (hf : ∀ y, StFragW dly y.e.pl (fw y)) :
    StFrag dly (step2 P fw w x) := by
  refine ⟨fun l s => ?_, fun l s => ?_⟩
  · show StFragW dly l (x.wordNext fw l s)
    unfold Engine2.wordNext
    by_cases hc : x.e.pst = .cap ∧ l = x.e.pl ∧ s = x.e.pslot
    · rw [if_pos hc, hc.2.1]
      exact hf x
    · rw [if_neg hc]
      exact h.1 l s
  · show npf2 fw x l s = false
    unfold npf2
    split
    · simp [Engine2.op_not_br_st (hf x)]
    · exact h.2 l s

theorem frag_run2 (P : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (hf : ∀ y, StFragW dly y.e.pl (fw y)) :
    ∀ (n : Nat) (x : Engine2), StFrag dly x → StFrag dly (run2 P fw sched n x)
  | 0, _, h => h
  | n + 1, x, h => frag_run2 P dly fw sched hf n _ (frag_step P dly fw _ x h hf)

/-! ### The run: one V4b program, time-indexed along the trajectory -/

/-- The V4b program of a v2 run from `x0`: `ret` at cycle `t` is the v2 `retire` of the
state at `t`, `ext` the head word's delay above the minimum. Both are read only at the
dispatched lane during a writeback. -/
def stP (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2) : Program :=
  { live := P2.live
    dly := dly
    ext := fun t l =>
      ((run2 P2 fw sched (t - x0.e.now) x0).head (run2 P2 fw sched (t - x0.e.now) x0).e.cur).dly
        - dly l
    ret := fun t _ => (run2 P2 fw sched (t - x0.e.now) x0).retire P2 }

/-- **Run refinement, self-timed.** On fragment programs the projected v2 run is a V4b run
of `stP`. -/
theorem run2_proj_st (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2)
    (hx0 : StFrag dly x0) (hf : ∀ y, StFragW dly y.e.pl (fw y))
    (hsw : ∀ x w, sched x = some w →
      (stP P2 dly fw sched x0).live w = true ∧ x.e.ts w ≤ x.e.now)
    (hss : ∀ y x, Ready (stP P2 dly fw sched x0) y x.e → sched x ≠ none) :
    ∀ n, (run2 P2 fw sched n x0).e =
      run (stP P2 dly fw sched x0) (win1 (stP P2 dly fw sched x0) P2 fw sched x0) n x0.e
  | 0 => rfl
  | n + 1 => by
    have hk : (run2 P2 fw sched n x0).e.now - x0.e.now = n := by
      rw [now_run2]
      omega
    rw [run2_succ', run_succ', ← run2_proj_st P2 dly fw sched x0 hx0 hf hsw hss n]
    rw [step_win_congr (stP P2 dly fw sched x0) (win1 (stP P2 dly fw sched x0) P2 fw sched x0),
      win1_on (stP P2 dly fw sched x0) P2 fw sched x0 hsw hss n]
    refine step2_proj_st P2 (stP P2 dly fw sched x0) dly fw _ _
      (frag_run2 P2 dly fw sched hf n x0 hx0) rfl rfl ?_ ?_
      (by simp [stP, Engine2.op_not_br_st (hf (run2 P2 fw sched n x0))])
    · show (run2 P2 fw sched ((run2 P2 fw sched n x0).e.now - x0.e.now) x0).retire P2 = _
      rw [hk]
    · show ((run2 P2 fw sched ((run2 P2 fw sched n x0).e.now - x0.e.now) x0).head
          (run2 P2 fw sched ((run2 P2 fw sched n x0).e.now - x0.e.now) x0).e.cur).dly
          - dly (run2 P2 fw sched n x0).e.cur = _
      rw [hk]

/-- **D\* for the v2 engine with self-timed bytes, d ≥ 39, no external hypotheses.**
For every fragment program stream `fw` (ordinary, looping re-arm and self-timed words, each
delay at least the lane's minimum), **every last-bit and stuff-slot pattern** (`P2.stl`,
`P2.stuff` arbitrary), and every work-conserving v2 scheduler that picks a ready lane: no
dispatch decision ever stalls, and branch 1 never issues. Runs without the USB re-anchor
(declared exclusion). -/
theorem dstar39_st (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2)
    (hx0 : StFrag dly x0) (hf : ∀ y, StFragW dly y.e.pl (fw y))
    (hW : Wf x0.e) (hfull : ∀ l s, P2.live l = true → x0.e.actv l s = true)
    (h0 : x0.e.st = .idle) (h0ts : ∀ l, x0.e.now ≤ x0.e.ts l)
    (hsw : ∀ x w, sched x = some w → P2.live w = true ∧ x.e.ts w ≤ x.e.now)
    (hss : ∀ y x, Ready (P2.toP dly) y x.e → sched x ≠ none)
    (hd : ∀ l, P2.live l = true → 39 ≤ dly l) :
    ∀ T, ((run2 P2 fw sched T x0).e.st = .idle →
            ∀ w, sched (run2 P2 fw sched T x0) = some w →
              (run2 P2 fw sched T x0).e.headValid w = true) ∧
         NoBr1 (stP P2 dly fw sched x0) (run2 P2 fw sched T x0).e := by
  intro T
  have hsw' : ∀ x w, sched x = some w →
      (stP P2 dly fw sched x0).live w = true ∧ x.e.ts w ≤ x.e.now := hsw
  have hss' : ∀ y x, Ready (stP P2 dly fw sched x0) y x.e → sched x ≠ none :=
    fun y x h => hss y x h
  have key := dstar39 (stP P2 dly fw sched x0) (win1 (stP P2 dly fw sched x0) P2 fw sched x0)
    x0.e hW hfull (fun _ => rfl) hx0.2 h0 h0ts (win1_ready _ P2 fw sched x0)
    (fun y e _ hy => win1_wc _ P2 fw sched x0 y e hy) hd T
  have hr := run2_proj_st P2 dly fw sched x0 hx0 hf hsw' hss' T
  rw [← hr] at key
  refine ⟨fun hi w hw => key.1 hi w ?_, key.2⟩
  rw [win1_on (stP P2 dly fw sched x0) P2 fw sched x0 hsw' hss' T]
  exact hw

#print axioms step2_proj_st
#print axioms dstar39_st

end JLane
