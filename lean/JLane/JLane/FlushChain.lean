import JLane.PrioRespF
/-!
# Brick F10 — the release chain across flushes (the flush lemma for `hspan`, `runF` half)

On `run`, `PrioResp.ts_chain` is exact: a lane's release after `n` cycles is its release at `a`
plus the gaps its writebacks opened in between (`gsum`), and `span_min ⇒ hspan` is that chain
plus the per-word gap facts the span checker establishes (Wilson 11-21: "a premise the span
checker establishes"). A flush is a new way for a release to move. Wilson asked for the flush
argument as a lemma (11-21, hspan ruling); on the flush run it is:

* **`ts_chainF_ge`** — along `runF`, the release at `a + n` is **at least** the release at `a`
  plus the gaps the writebacks opened (`gsumF`), for a lane whose flushes never lower its release
  (`hfl`) and never land on its own writeback (`hnfwb`): a flush can only add;
* **`ts_chainT_ge`** — on the FALLTHROUGH engine both are discharged: a flush is an armed lane's
  hit, whose view release is at most `now + 1` (`relT_le_fl`), and an armed lane is never the
  one being dispatched (`InvT`), so never written back.

So on the flush run `span_min ⇒ hspan` stands exactly as on `run`: the chain's per-writeback gaps
against the checker's per-word gaps. (On `runBK`, with no view, an FT ARM's writeback moves the
release to its deadline and its edge can move it back to `edge + 1` -- the other half.)
-/
namespace JLane

/-- The gaps lane `y`'s writebacks open in `[a, a + n)` along `runF`. -/
def gsumF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool) (y : Lane)
    (X0 : EngineF) (a : Nat) : Nat → Nat
  | 0 => 0
  | n + 1 => gsumF P win fl y X0 a n +
      (if IsWB y (runF P win fl (a + n) X0).e then
        tsNext P (runF P win fl (a + n) X0).e y - (runF P win fl (a + n) X0).e.ts y else 0)

/-- **The release chain across flushes**: flushes only add. -/
theorem ts_chainF_ge (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (y : Lane) (X0 : EngineF) (a : Nat)
    (hfl : ∀ n, fl (runF P win fl n X0).e.now y = true →
      (runF P win fl n X0).e.ts y ≤ (runF P win fl n X0).e.now + 1)
    (hnfwb : ∀ n, fl (runF P win fl n X0).e.now y = true → ¬IsWB y (runF P win fl n X0).e) :
    ∀ n, (runF P win fl a X0).e.ts y + gsumF P win fl y X0 a n ≤ (runF P win fl (a + n) X0).e.ts y
  | 0 => by simp [gsumF]
  | n + 1 => by
    have ih := ts_chainF_ge P win fl y X0 a hfl hnfwb n
    show (runF P win fl a X0).e.ts y + (gsumF P win fl y X0 a n +
        (if IsWB y (runF P win fl (a + n) X0).e then
          tsNext P (runF P win fl (a + n) X0).e y - (runF P win fl (a + n) X0).e.ts y else 0))
      ≤ (runF P win fl (a + n + 1) X0).e.ts y
    cases hf : fl (runF P win fl (a + n) X0).e.now y with
    | true =>
      have hw := hnfwb (a + n) hf
      rw [if_neg hw, ts_flushF P win fl y X0 (a + n) hf]
      have := hfl (a + n) hf
      omega
    | false =>
      by_cases hw : IsWB y (runF P win fl (a + n) X0).e
      · rw [if_pos hw, runF_succ' P win fl (a + n), stepF_ts_y P win _ _ y hf]
        have := tsNext_ge P (runF P win fl (a + n) X0).e y
        omega
      · rw [if_neg hw, ts_flatF1 P win fl y X0 (a + n) hf hw]
        omega

section
variable (P2 : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
  (hedge : ∀ t l, t + 1 ≤ edge t l) (sched : EngineT → Option Lane) (X0 : EngineT)
  (hX0 : InvT Wn X0) (hf : ∀ y, ArmFragT Wn (fw y)) (hsw : SchedT sched)

include hedge hX0 hf hsw in
/-- **The release chain on the FALLTHROUGH engine**: the view release after `n` cycles is at least
the release at `a` plus the gaps the writebacks opened, every lane, flushes included. -/
theorem ts_chainT_ge (y : Lane) (a : Nat) :
    ∀ n, relT (run3T P2 fw edge sched a X0) y
        + gsumF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0) (flR P2 fw edge sched X0)
            y (πF X0) a n
      ≤ relT (run3T P2 fw edge sched (a + n) X0) y := by
  have hE := runF_e P2 Wn fw edge hedge sched X0 hX0 hf hsw
  intro n
  have key := ts_chainF_ge (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0)
    (flR P2 fw edge sched X0) y (πF X0) a
    (fun k h => by
      rw [hE] at h ⊢
      change flR P2 fw edge sched X0 (run3T P2 fw edge sched k X0).x.e.now y = true at h
      rw [flR_at] at h
      exact relT_le_fl _ y h)
    (fun k h hw => by
      rw [hE] at h hw
      change flR P2 fw edge sched X0 (run3T P2 fw edge sched k X0).x.e.now y = true at h
      rw [flR_at] at h
      have ha : (run3T P2 fw edge sched k X0).armed y = true := by
        unfold EngineT.fl EngineT.hit at h
        cases h1 : (run3T P2 fw edge sched k X0).armed y <;> simp_all
      obtain ⟨h1, h2⟩ := hw
      change (run3T P2 fw edge sched k X0).x.e.st = .wb at h1
      change (run3T P2 fw edge sched k X0).x.e.cur = y at h2
      have hI := invT_run P2 Wn fw edge hedge sched hf hsw k X0 hX0
      exact hI.2.2.2.1 y ha ⟨by rw [h1]; decide, h2⟩)
    n
  rw [hE, hE] at key
  exact key

end

end JLane
