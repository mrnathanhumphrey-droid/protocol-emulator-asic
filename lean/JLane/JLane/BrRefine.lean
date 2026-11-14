import JLane.OptRun
import JLane.SelfTimed
/-!
# Brick C — branch words in the v2 engine (branch brick, stage 3)

The V4b model of option A (`Engine.npf`, `Program.fnpf`) is abstract: some captured words are
"no-prefetch" and some retirements push the release by at least `Wn`. Here those two facts
come from the v2 engine, where a word is a timed branch (`Op.br`):

* the flag is the branch class of the slot's word (`BrFrag`: `npf l s = (word l s is a branch)`),
  set at the capture from the fetched word (`npf2`), as the RTL decodes `l_cls[..][C_BR]` when
  the word lands; `want_fetch`'s branch clause (l.2800) is then exactly V4b's option A;
* a branch's writeback adds its wait `W` (`a_dly_wb = br_wait`, l.1997), and the RTL refuses
  `W < BR_W_MIN` (l.2382, l.3598), so `Wn` is the least branch wait (33 on the 5-lane chip).

`step2_proj_br` / `run2_proj_br`: on the branch fragment (ordinary, looping re-arm,
self-timed and branch words, each delay at least the lane's minimum), the projected v2 run is a
V4b run of `brP`, whose `fnpf` reads the fetched word. `brP_wn` discharges `hWn`, and
`head_late_br` is `head_late_optA` for v2 runs with branches.
-/
namespace JLane

/-- A word on lane `l` in the branch fragment: ordinary, looping re-arm, self-timed or
branch, with a delay of at least the lane's minimum, and a branch's wait at least `Wn`. -/
def BrFragW (dly : Lane → Nat) (Wn : Nat) (l : Lane) (w : Word) : Prop :=
  (w.op = .ord ∨ w.op = .loopRe ∨ w.op = .st ∨ w.op = .br) ∧ dly l ≤ w.dly ∧
    (w.op = .br → Wn ≤ w.dly)

/-- Every slot holds a fragment word, and its no-prefetch flag is its branch class. -/
def BrFrag (dly : Lane → Nat) (Wn : Nat) (x : Engine2) : Prop :=
  (∀ l s, BrFragW dly Wn l (x.word l s)) ∧ (∀ l s, x.e.npf l s = decide ((x.word l s).op = .br))

namespace Engine2

theorem op_not_chain_br {dly : Lane → Nat} {Wn : Nat} {l : Lane} {w : Word}
    (h : BrFragW dly Wn l w) : w.op ≠ .chainRe := by
  rcases h.1 with h1 | h1 | h1 | h1 <;> rw [h1] <;> decide

theorem isClk_br (dly : Lane → Nat) (Wn : Nat) (x : Engine2) (h : BrFrag dly Wn x) :
    x.isClk = false := by
  unfold isClk head
  rcases (h.1 x.e.cur (x.e.sel x.e.cur)).1 with h1 | h1 | h1 | h1 <;> rw [h1]

/-- In the fragment the writeback adds the head word's whole delay (a branch's: its wait). -/
theorem wbDly_br (P : Program2) (dly : Lane → Nat) (Wn : Nat) (x : Engine2)
    (h : BrFrag dly Wn x) : x.wbDly P = (x.head x.e.cur).dly := by
  unfold wbDly
  rw [if_neg (fun h' => by rw [isClk_br dly Wn x h] at h'; exact Bool.noConfusion h'.1)]

/-- **Option A, refined.** The RTL `want_fetch` (head empty → 1; chaining → 0; branch head → 0;
else the spare) is V4b's `wantFetch` with the flag = the head word's branch class. -/
theorem wantFetch_br (dly : Lane → Nat) (Wn : Nat) (x : Engine2) (h : BrFrag dly Wn x)
    (l : Lane) : x.wantFetch l = x.e.wantFetch l := by
  have hc : (x.word l (x.e.sel l)).op ≠ .chainRe := op_not_chain_br (h.1 l (x.e.sel l))
  unfold wantFetch Engine.wantFetch head
  rw [h.2 l (x.e.sel l)]
  cases hv : x.e.headValid l <;>
    by_cases hb : (x.word l (x.e.sel l)).op = .br <;> simp [hb, hc]

end Engine2

/-! ### One cycle -/

/-- **Refinement, branches.** On fragment words, one v2 cycle is one V4b cycle of any
program `Q` with the same liveness and minimum delays whose retire flag is the v2 `retire`,
whose extra is the head word's delay above the minimum, and whose no-prefetch decode reads the
fetched word. -/
theorem step2_proj_br (P : Program2) (Q : Program) (dly : Lane → Nat) (Wn : Nat)
    (fw : Engine2 → Word) (w : Option Lane) (x : Engine2) (h : BrFrag dly Wn x)
    (hl : Q.live = P.live) (hd : Q.dly = dly)
    (hr : Q.ret x.e.now x.e.cur = x.retire P)
    (he : Q.ext x.e.now x.e.cur = (x.head x.e.cur).dly - dly x.e.cur)
    (hq : Q.fnpf x.e = decide ((fw x).op = .br)) :
    proj (step2 P fw w x) = step Q (fun _ => w) (proj x) := by
  have hn : npf2 fw x = npfNext Q x.e := npf2_eq fw x Q hq
  have hp : portNextW (P.toP (fun _ => 0)) x.wantFetch x.e = portNext Q x.e := by
    rw [portNextW_congr _ _ _ _ (Engine2.wantFetch_br dly Wn x h), ← portNextW_v1]
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
    · rw [if_pos hc, if_pos hc, hc.2, Engine2.wbDly_br P dly Wn x h, hd, he]
      have hle := (h.1 x.e.cur (x.e.sel x.e.cur)).2.1
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

/-- The fragment, flags included, is preserved when every fetched word is in it. -/
theorem br_step (P : Program2) (dly : Lane → Nat) (Wn : Nat) (fw : Engine2 → Word)
    (w : Option Lane) (x : Engine2) (h : BrFrag dly Wn x)
    (hf : ∀ y, BrFragW dly Wn y.e.pl (fw y)) :
    BrFrag dly Wn (step2 P fw w x) := by
  refine ⟨fun l s => ?_, fun l s => ?_⟩
  · show BrFragW dly Wn l (x.wordNext fw l s)
    unfold Engine2.wordNext
    by_cases hc : x.e.pst = .cap ∧ l = x.e.pl ∧ s = x.e.pslot
    · rw [if_pos hc, hc.2.1]
      exact hf x
    · rw [if_neg hc]
      exact h.1 l s
  · show npf2 fw x l s = decide ((x.wordNext fw l s).op = .br)
    unfold npf2 Engine2.wordNext
    by_cases hc : x.e.pst = .cap ∧ l = x.e.pl ∧ s = x.e.pslot
    · rw [if_pos hc, if_pos hc]
    · rw [if_neg hc, if_neg hc]
      exact h.2 l s

theorem br_run2 (P : Program2) (dly : Lane → Nat) (Wn : Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (hf : ∀ y, BrFragW dly Wn y.e.pl (fw y)) :
    ∀ (n : Nat) (x : Engine2), BrFrag dly Wn x → BrFrag dly Wn (run2 P fw sched n x)
  | 0, _, h => h
  | n + 1, x, h => br_run2 P dly Wn fw sched hf n _ (br_step P dly Wn fw _ x h hf)

/-! ### The run -/

/-- The V4b program of a v2 run from `x0` with branches: as `stP`, plus the no-prefetch decode
of the word fetched at cycle `t`. -/
def brP (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2) : Program :=
  { live := P2.live
    dly := dly
    ext := fun t l =>
      ((run2 P2 fw sched (t - x0.e.now) x0).head (run2 P2 fw sched (t - x0.e.now) x0).e.cur).dly
        - dly l
    ret := fun t _ => (run2 P2 fw sched (t - x0.e.now) x0).retire P2
    fnpf := fun e => decide ((fw (run2 P2 fw sched (e.now - x0.e.now) x0)).op = .br) }

/-- **Run refinement, branches.** On fragment programs the projected v2 run is a V4b run of
`brP`. -/
theorem run2_proj_br (P2 : Program2) (dly : Lane → Nat) (Wn : Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2)
    (hx0 : BrFrag dly Wn x0) (hf : ∀ y, BrFragW dly Wn y.e.pl (fw y))
    (hsw : ∀ x w, sched x = some w →
      (brP P2 dly fw sched x0).live w = true ∧ x.e.ts w ≤ x.e.now)
    (hss : ∀ y x, Ready (brP P2 dly fw sched x0) y x.e → sched x ≠ none) :
    ∀ n, (run2 P2 fw sched n x0).e =
      run (brP P2 dly fw sched x0) (win1 (brP P2 dly fw sched x0) P2 fw sched x0) n x0.e
  | 0 => rfl
  | n + 1 => by
    have hk : (run2 P2 fw sched n x0).e.now - x0.e.now = n := by
      rw [now_run2]
      omega
    rw [run2_succ', run_succ', ← run2_proj_br P2 dly Wn fw sched x0 hx0 hf hsw hss n]
    rw [step_win_congr (brP P2 dly fw sched x0) (win1 (brP P2 dly fw sched x0) P2 fw sched x0),
      win1_on (brP P2 dly fw sched x0) P2 fw sched x0 hsw hss n]
    refine step2_proj_br P2 (brP P2 dly fw sched x0) dly Wn fw _ _
      (br_run2 P2 dly Wn fw sched hf n x0 hx0) rfl rfl ?_ ?_ ?_
    · show (run2 P2 fw sched ((run2 P2 fw sched n x0).e.now - x0.e.now) x0).retire P2 = _
      rw [hk]
    · show ((run2 P2 fw sched ((run2 P2 fw sched n x0).e.now - x0.e.now) x0).head
          (run2 P2 fw sched ((run2 P2 fw sched n x0).e.now - x0.e.now) x0).e.cur).dly
          - dly (run2 P2 fw sched n x0).e.cur = _
      rw [hk]
    · show decide ((fw (run2 P2 fw sched ((run2 P2 fw sched n x0).e.now - x0.e.now) x0)).op
          = .br) = _
      rw [hk]

/-- **`hWn` from the words.** A retirement of a no-prefetch head on the projected run is a
branch's writeback, so it pushes the release by the branch's wait, at least `Wn`. -/
theorem brP_wn (P2 : Program2) (dly : Lane → Nat) (Wn : Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2)
    (hx0 : BrFrag dly Wn x0) (hf : ∀ y, BrFragW dly Wn y.e.pl (fw y))
    (hsw : ∀ x w, sched x = some w →
      (brP P2 dly fw sched x0).live w = true ∧ x.e.ts w ≤ x.e.now)
    (hss : ∀ y x, Ready (brP P2 dly fw sched x0) y x.e → sched x ≠ none) (y : Lane) :
    ∀ x, IsRet (brP P2 dly fw sched x0) y
        (run (brP P2 dly fw sched x0) (win1 (brP P2 dly fw sched x0) P2 fw sched x0) x x0.e) →
      NpfAt y
        (run (brP P2 dly fw sched x0) (win1 (brP P2 dly fw sched x0) P2 fw sched x0) x x0.e) →
      (run (brP P2 dly fw sched x0) (win1 (brP P2 dly fw sched x0) P2 fw sched x0) x x0.e).ts y
          + Wn ≤
        (run (brP P2 dly fw sched x0) (win1 (brP P2 dly fw sched x0) P2 fw sched x0) (x + 1)
          x0.e).ts y := by
  intro x hret hnpf
  have hpr := run2_proj_br P2 dly Wn fw sched x0 hx0 hf hsw hss x
  have hfr := br_run2 P2 dly Wn fw sched hf x x0 hx0
  rw [← hpr] at hret hnpf
  have hwb := ts_after_wb (brP P2 dly fw sched x0)
    (win1 (brP P2 dly fw sched x0) P2 fw sched x0) y x0.e x (isWB_of_ret _ y _ (by rw [← hpr]; exact hret))
  rw [hwb, ← hpr]
  have hk : (run2 P2 fw sched x x0).e.now - x0.e.now = x := by
    rw [now_run2]
    omega
  -- the head of `y` is a branch word
  have hcur : (run2 P2 fw sched x x0).e.cur = y := hret.2.1
  have hbr : (Engine2.head (run2 P2 fw sched x x0) y).op = .br := by
    have h2 := hfr.2 y ((run2 P2 fw sched x x0).e.sel y)
    unfold NpfAt at hnpf
    rw [hnpf] at h2
    exact of_decide_eq_true h2.symm
  have hw := hfr.1 y ((run2 P2 fw sched x x0).e.sel y)
  have hwn := hw.2.2 hbr
  have hle := hw.2.1
  show (run2 P2 fw sched x x0).e.ts y + Wn ≤ (run2 P2 fw sched x x0).e.ts y + dly y +
    (((run2 P2 fw sched ((run2 P2 fw sched x x0).e.now - x0.e.now) x0).head
      (run2 P2 fw sched ((run2 P2 fw sched x x0).e.now - x0.e.now) x0).e.cur).dly - dly y)
  rw [hk, hcur]
  unfold Engine2.head at hbr hwn hle ⊢
  omega

/-- **Head valid when ready, for v2 runs with branches.** `head_late_optA` on the projected run:
`Wn` is now the least branch wait in the stream (the RTL's `BR_W_MIN` floor), not an assumption.
Still hypotheses (stage 5): the response bounds `R` (all writebacks) and `Rn` (branch
retirements) and the branch-1 budget `B`, all on the projected run `run2_proj_br` equates. -/
theorem head_late_br (P2 : Program2) (dly : Lane → Nat) (Wn : Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2)
    (hx0 : BrFrag dly Wn x0) (hf : ∀ y, BrFragW dly Wn y.e.pl (fw y))
    (hsw : ∀ x w, sched x = some w → P2.live w = true ∧ x.e.ts w ≤ x.e.now)
    (hss : ∀ y x, Ready (P2.toP dly) y x.e → sched x ≠ none)
    (y : Lane) (R B T Rn d Y LD : Nat) (hW : Wf x0.e) (hfull : ∀ s, x0.e.actv y s = true)
    (hy : P2.live y = true) (hdly : dly y = d) (hd : DSTAR + B ≤ d)
    (hY : 40 + 2 * B ≤ Wn + Y) (hRR : Rn ≤ R)
    (hDc : Rn + HEAD_SLACK + B ≤ Wn + LD) (hFc : Rn + HEAD_SLACK + DSTAR + 2 * B ≤ Wn + d)
    (hNc : R + HEAD_SLACK + B + Y ≤ 2 * d)
    (hR : ∀ t, t < T → IsWB y (run2 P2 fw sched t x0).e →
      (run2 P2 fw sched t x0).e.now ≤ (run2 P2 fw sched t x0).e.ts y + R + 2)
    (hRn : ∀ t, t < T → IsRet (brP P2 dly fw sched x0) y (run2 P2 fw sched t x0).e →
      NpfAt y (run2 P2 fw sched t x0).e →
      (run2 P2 fw sched t x0).e.now ≤ (run2 P2 fw sched t x0).e.ts y + Rn + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B →
      chargeSum (brP P2 dly fw sched x0) (win1 (brP P2 dly fw sched x0) P2 fw sched x0) y m
        (run2 P2 fw sched a x0).e ≤ B)
    (t : Nat) (htT : t ≤ T)
    (hrdy : (run2 P2 fw sched t x0).e.ts y ≤ (run2 P2 fw sched t x0).e.now)
    (hlate : ∀ x, x < t → IsRet (brP P2 dly fw sched x0) y (run2 P2 fw sched x x0).e →
      NpfAt y (run2 P2 fw sched x x0).e →
      cnt (brP P2 dly fw sched x0) (win1 (brP P2 dly fw sched x0) P2 fw sched x0)
          (IsRet (brP P2 dly fw sched x0) y) (x + 1) x0.e =
        cnt (brP P2 dly fw sched x0) (win1 (brP P2 dly fw sched x0) P2 fw sched x0)
          (IsRet (brP P2 dly fw sched x0) y) t x0.e →
      (run2 P2 fw sched t x0).e.ts y + LD ≤ (run2 P2 fw sched t x0).e.now) :
    (run2 P2 fw sched t x0).e.headValid y = true := by
  have hsw' : ∀ x w, sched x = some w →
      (brP P2 dly fw sched x0).live w = true ∧ x.e.ts w ≤ x.e.now := hsw
  have hss' : ∀ y x, Ready (brP P2 dly fw sched x0) y x.e → sched x ≠ none :=
    fun y x h => hss y x h
  have hpr := run2_proj_br P2 dly Wn fw sched x0 hx0 hf hsw' hss'
  rw [hpr]
  refine head_late_optA (brP P2 dly fw sched x0) (win1 (brP P2 dly fw sched x0) P2 fw sched x0)
    y x0.e R B T Rn d Wn Y LD hW hfull hy hdly hd hY hRR hDc hFc hNc ?_ ?_ ?_
    (fun x _ hr hn => brP_wn P2 dly Wn fw sched x0 hx0 hf hsw' hss' y x hr hn)
    t htT ?_ ?_
  · intro t ht h
    rw [← hpr] at h ⊢
    exact hR t ht h
  · intro t ht h1 h2
    rw [← hpr] at h1 h2 ⊢
    exact hRn t ht h1 h2
  · intro a m ham hm
    rw [← hpr]
    exact hB a m ham hm
  · rw [← hpr]
    exact hrdy
  · intro x hx hr hn hc
    rw [← hpr] at hr hn ⊢
    exact hlate x hx hr hn hc

#print axioms step2_proj_br
#print axioms run2_proj_br
#print axioms brP_wn
#print axioms head_late_br

end JLane
