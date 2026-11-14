import JLane.RespSpan
/-!
# Brick K — the priority lane's response (stage 5, step 6)

`wb_close` / `wb_close_span` give every lane a Lemma A bound (at least 14). The USB lane does
better: it wins the dispatcher whenever it is idle, released and has a valid head (`usb_wins`,
EDF with the deadline margin; under the ruled scheduler (b′) "head valid" is part of
readiness). Then it is decided at the first idle cycle after its head is valid, and the
dispatcher is idle at least once in any three cycles (`idle3`). So with head lateness `L`
(`head_late_*`), every writeback lands within `L + 4` of its release: `R_u = L + 2`,
independent of the other lanes. A small `R_u` is what lets the USB lane's ARM pairs count once
in other lanes' windows (`wb_close_span`'s `R y + 1 + R z ≤ G z`).
-/
namespace JLane

theorem ts_const (P : Program) (win : Engine → Option Lane) (e0 : Engine) (u : Lane) (s : Nat) :
    ∀ k, (∀ i, i < k → ¬IsWB u (run P win (s + i) e0)) →
      (run P win (s + k) e0).ts u = (run P win s e0).ts u
  | 0, _ => rfl
  | k + 1, h => by
    have ih := ts_const P win e0 u s k (fun i hi => h i (by omega))
    rw [← Nat.add_assoc, ts_flat P win u e0 (s + k) (h k (by omega)), ih]

/-- **The priority lane's response.** -/
theorem prio_resp (P : Program) (win : Engine → Option Lane) (e0 : Engine)
    (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l) (u : Lane) (hu : P.live u = true)
    (L : Nat)
    (t : Nat)
    (hpri : ∀ s, s < t → (run P win s e0).st = .idle → Ready P u (run P win s e0) →
      (run P win s e0).headValid u = true → win (run P win s e0) = some u)
    (hwb : IsWB u (run P win t e0))
    (hfree : ∀ w, w + 2 < t → IsWB u (run P win w e0) →
      (run P win w e0).now < (run P win t e0).ts u)
    (hhv : ∀ c, c < t → (run P win c e0).ts u = (run P win t e0).ts u →
      (run P win t e0).ts u + L ≤ (run P win c e0).now → (run P win c e0).headValid u = true) :
    (run P win t e0).now ≤ (run P win t e0).ts u + L + 4 := by
  obtain ⟨D, rfl, hdec⟩ := wb_back P win e0 h0 t u hwb
  obtain ⟨hts2, hnow2⟩ := dec_ts P win e0 D u hdec
  rw [hts2, hnow2]
  rw [hts2] at hfree hhv
  by_cases hfit : (run P win D e0).now ≤ (run P win D e0).ts u + L + 2
  · omega
  · exfalso
    have hnD := now_run P win D e0
    have hts0 := ts_mono P win u e0 0 D (Nat.zero_le D)
    have h00 : (run P win 0 e0).ts u = e0.ts u := rfl
    have h0u := h0ts u
    -- the cycle at which the job is `L` past its release
    obtain ⟨c0, hc0⟩ : ∃ c0, e0.now + c0 = (run P win D e0).ts u + L :=
      ⟨(run P win D e0).ts u + L - e0.now, by omega⟩
    have hc0D : c0 + 3 ≤ D := by omega
    -- no writeback of u from c0 on, before D
    have noWB : ∀ w, c0 ≤ w → w < D → ¬IsWB u (run P win w e0) := by
      intro w hw1 hw2 hw
      have h1 := hfree w (by omega) hw
      have h2 := now_run P win w e0
      omega
    obtain ⟨s, hs1, hs2, hidle⟩ := idle3 P win e0 c0
    have hns := now_run P win s e0
    have hconst := ts_const P win e0 u s (D - s) (fun i hi => noWB (s + i) (by omega) (by omega))
    rw [show s + (D - s) = D by omega] at hconst
    have hrdy : Ready P u (run P win s e0) := ⟨hu, by omega⟩
    have hv := hhv s (by omega) hconst.symm (by omega)
    have hdec' : Dec win u (run P win s e0) := ⟨hidle, hpri s (by omega) hidle hrdy hv, hv⟩
    have hw2 := dec_wb P win e0 s u hdec'
    rcases Nat.lt_or_ge (s + 2) D with hlt | hge
    · exact noWB (s + 2) (by omega) hlt hw2
    · have hidD : (run P win D e0).st = .idle := hdec.1
      have hst1 : (run P win (s + 1) e0).st = .drive := by
        rw [run_succ']
        exact (step_of_dec P win _ u hdec').1
      have hst2 : (run P win (s + 2) e0).st = .wb := hw2.1
      have : D = s + 1 ∨ D = s + 2 := by omega
      rcases this with h | h
      · rw [h, hst1] at hidD
        cases hidD
      · rw [h, hst2] at hidD
        cases hidD

/-- The sum of the release gaps of `y`'s writebacks in `[a, a + n)`. -/
def gsum (P : Program) (win : Engine → Option Lane) (y : Lane) (e0 : Engine) (a : Nat) :
    Nat → Nat
  | 0 => 0
  | n + 1 => gsum P win y e0 a n +
      (if IsWB y (run P win (a + n) e0) then gp P win y e0 (a + n) else 0)

/-- **The release chain, exact.** A lane's release after `n` cycles is its release at `a` plus
the gaps its writebacks opened in between — the checker's deadline chains (an ARM's gap is its
edge's distance, `arm_release`; another word's is its delay, less one after a rebase). -/
theorem ts_chain (P : Program) (win : Engine → Option Lane) (y : Lane) (e0 : Engine) (a : Nat) :
    ∀ n, (run P win (a + n) e0).ts y = (run P win a e0).ts y + gsum P win y e0 a n
  | 0 => rfl
  | n + 1 => by
    rw [← Nat.add_assoc]
    show (run P win (a + n + 1) e0).ts y = _ + (gsum P win y e0 a n +
      (if IsWB y (run P win (a + n) e0) then gp P win y e0 (a + n) else 0))
    have ih := ts_chain P win y e0 a n
    by_cases hw : IsWB y (run P win (a + n) e0)
    · rw [if_pos hw, ts_after_wb P win y e0 (a + n) hw, ih]
      unfold gp
      omega
    · rw [if_neg hw, ts_flat P win y e0 (a + n) hw, ih, Nat.add_zero]

#print axioms prio_resp
#print axioms ts_chain

end JLane
