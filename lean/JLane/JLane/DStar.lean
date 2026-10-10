import JLane.Run
/-!
# Brick 9 — the D* theorem
From a primed start, no dispatch decision ever stalls, provided:
* the EDF winner is always a ready lane;
* every live lane has `d ≥ D* + B` (throughput) and `R + 26 + B ≤ 2d` (latency);
* `hEDF`: on any stall-free prefix, every writeback lands within `R + 2` of its release;
* `hB`: on any stall-free prefix, every window of length ≤ `23 + B` carries at most
  `B` branch-1 charges.
The response bound and the budget are assumed only on stall-free prefixes, so the
induction is not circular.
-/
namespace JLane

/-- No stall this cycle: an idle FSM with a winner always finds the winner's head valid. -/
def NoStall (win : Engine → Option Lane) (e : Engine) : Prop :=
  e.st = .idle → ∀ w, win e = some w → e.headValid w = true

theorem dstar (P : Program) (win : Engine → Option Lane) (e0 : Engine)
    (R : Lane → Nat) (B : Nat)
    (hW : Wf e0) (hfull : ∀ l s, P.live l = true → e0.actv l s = true)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hthr : ∀ l, P.live l = true → DSTAR + B ≤ P.dly l)
    (hlat : ∀ l, P.live l = true → R l + 26 + B ≤ 2 * P.dly l)
    (hEDF : ∀ T, (∀ t, t < T → NoStall win (run P win t e0)) →
      ∀ y t, P.live y = true → t < T → IsWB y (run P win t e0) →
        (run P win t e0).now ≤ (run P win t e0).ts y + R y + 2)
    (hB : ∀ T, (∀ t, t < T → NoStall win (run P win t e0)) →
      ∀ y a m, P.live y = true → a + m ≤ T → m ≤ 23 + B →
        chargeSum P win y m (run P win a e0) ≤ B) :
    ∀ T, NoStall win (run P win T e0) := by
  have key : ∀ T, ∀ t, t < T → NoStall win (run P win t e0) := by
    intro T
    induction T with
    | zero =>
      intro t ht
      exact absurd ht (Nat.not_lt_zero t)
    | succ T ih =>
      intro t ht
      by_cases htT : t < T
      · exact ih t htT
      · have hteq : t = T := by omega
        rw [hteq]
        unfold NoStall
        intro _hidle w hw
        obtain ⟨hlive, hrdy⟩ := hwin _ w hw
        exact head_valid_when_ready P win w e0 (P.dly w) (R w) B T hW hfull hlive rfl
          (hthr w hlive) (hlat w hlive)
          (fun s hs hwb => hEDF T ih w s hlive hs hwb)
          (fun a m h1 h2 => hB T ih w a m hlive h1 h2)
          T (Nat.le_refl T) hrdy
  intro T
  exact key (T + 1) T (Nat.lt_succ_self T)

/-- At `B = 0`: throughput `d ≥ 20`, latency `R ≤ 2d − 26`. -/
theorem dstar_zero_budget_conditions (d R : Nat) (h1 : DSTAR + 0 ≤ d)
    (h2 : R + 26 + 0 ≤ 2 * d) : 20 ≤ d ∧ R + 26 ≤ 2 * d := by
  have : DSTAR = 20 := dstar_val
  omega

#print axioms dstar

end JLane
