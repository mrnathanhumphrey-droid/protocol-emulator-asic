import JLane.GapRunT
import JLane.RespWinB
/-!
# Brick C3f — the buffered engine with flushes, between a lane's flushes, is a trajectory
(`slot_on_composition`, step 3c)

`FlushKill.runBK` (the slot, the buffer, the FALLTHROUGH keep-flush K1–K4 and the kill K5), read
through `EngBK.base` -- the engine each cycle runs on -- agrees with `stepB` for lane `y` on every
cycle where `y` is not flushed and no killed capture lands on `y` (`agree_stepBKK`): the flush
rewrites only flushed lanes' slots, select, timestamp and buffer, and the kill only the lane the
killed capture was for. So a stretch of `runBK` between `y`'s flushes is a `TrajY` trajectory
(`trajY_runBK`), well formed by `FlushKill.wfBK_run`, and `GapRunT`'s certificate holds along it.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- **One cycle of `runBK`, as lane `y` sees it, is `stepB`'s**, when `y` is not flushed and the
cycle is not a killed capture for `y`. -/
theorem agree_stepBKK (fl : Lane → Bool) (k : Lane → Nat) (X : EngBK) (y : Lane)
    (hf : fl y = false) (hk : ¬(X.kc = true ∧ X.x.e.pl = y)) :
    AgreeY y (stepBKK P win usb sreq fl k X).base (stepB P win usb sreq X.base) := by
  have hpl : X.base.e.pl = X.x.e.pl := by rw [base_e]
  have hnk : (X.kc && decide (y = X.base.e.pl)) = false := by
    cases hkc : X.kc
    · rfl
    · have hne : ¬y = X.base.e.pl := fun h => hk ⟨hkc, by rw [h, hpl]⟩
      simp [hne]
  unfold AgreeY
  rw [base_e (stepBKK P win usb sreq fl k X), base_buf (stepBKK P win usb sreq fl k X)]
  refine ⟨rfl, rfl, rfl, rfl, ?_, ?_, ?_, fun _ => rfl, ?_⟩
  · show (if fl y = true then X.base.e.now + 1 else (stepB P win usb sreq X.base).e.ts y) = _
    rw [if_neg (by simp [hf])]
  · rw [selK]; simp [hf]
  · intro s
    rw [actvK]
    have : (X.kc && decide (y = X.base.e.pl) && capTo X.base y s) = false := by
      rw [hnk]; rfl
    simp [hf, this]
  · rw [bufK]; simp [hf, hnk]

/-- **A stretch of `runBK` is a trajectory.** From cycle `s`, over `T` cycles in which `y` is
never flushed and no killed capture lands on `y`, `runBK` read through `base` steps as `stepB`
for `y`. -/
theorem trajY_runBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (y : Lane)
    (s T : Nat)
    (hseg : ∀ n, n < T →
      fl (runBK P win usb sreq fl k (s + n) X0).x.e.now y = false ∧
      ¬((runBK P win usb sreq fl k (s + n) X0).kc = true ∧
        (runBK P win usb sreq fl k (s + n) X0).x.e.pl = y)) :
    TrajY P win usb sreq y (fun n => (runBK P win usb sreq fl k (s + n) X0).base) T := by
  intro n hn
  obtain ⟨hf, hk⟩ := hseg n hn
  show AgreeY y (runBK P win usb sreq fl k (s + (n + 1)) X0).base
    (stepB P win usb sreq (runBK P win usb sreq fl k (s + n) X0).base)
  rw [show s + (n + 1) = (s + n) + 1 by omega, runBK_succ']
  exact agree_stepBKK P win usb sreq _ _ _ y hf hk

/-- **Well formed along the stretch**: BufEng's invariant on every cycle's engine, given the
flush conditions (`FlushKill.wfBK_run`). -/
theorem wfB_runBK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (s T : Nat)
    (hF : ∀ j, j < s + T → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0)) :
    ∀ n, n ≤ T → WfB ((fun n => (runBK P win usb sreq fl k (s + n) X0).base) n) := fun n hn =>
  (wfBK_run P win usb sreq hok fl k (s + n) X0 hI (fun j hj => hF j (by omega))).wf

end

#print axioms agree_stepBKK
#print axioms trajY_runBK
#print axioms wfB_runBK

end JLane
