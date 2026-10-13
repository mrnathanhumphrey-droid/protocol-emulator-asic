import JLane.BZero
/-!
# Brick B2 — B = 0, and D* with no external hypotheses
With every live lane at `d ≥ 39`, from a primed start, any work-conserving scheduler
that picks a ready lane never stalls and never issues a branch-1 refill.
Joint induction on time: no stall and no branch-1 issue before `n` give `R = 14`
(`wb_bound`) and zero charge (`chargeSum_zero`), hence valid heads at `n`; a branch-1
issue at `n` would need a doubly-owed writeback, which `pending_bound` rules out
unless `d ≤ 38`.
-/
namespace JLane

theorem dstar39 (P : Program) (win : Engine → Option Lane) (e0 : Engine)
    (hW : Wf e0) (hfull : ∀ l s, P.live l = true → e0.actv l s = true)
    (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hws : ∀ y e, e.st = .idle → Ready P y e → win e ≠ none)
    (hd : ∀ l, P.live l = true → 39 ≤ P.dly l) :
    ∀ T, NoStall win (run P win T e0) ∧ NoBr1 P (run P win T e0) := by
  have hS : Struct e0 := by
    have hw := hW
    unfold Wf at hw
    exact hw.1
  have hd29 : ∀ l, P.live l = true → 29 ≤ P.dly l := fun l hl => by
    have := hd l hl
    omega
  have hD : DSTAR = 20 := dstar_val
  -- the response bound, from a stall-free prefix
  have hRof : ∀ n, (∀ t, t < n → NoStall win (run P win t e0)) →
      ∀ y, P.live y = true → ∀ t, t < n → IsWB y (run P win t e0) →
        (run P win t e0).now ≤ (run P win t e0).ts y + 14 + 2 :=
    fun n hn y hy t ht hwb => wb_bound P win e0 n h0 h0ts hwin hws hd29 hn t ht y hy hwb
  -- the zero budget, from a branch-1-free prefix
  have hBof : ∀ n, (∀ t, t < n → NoBr1 P (run P win t e0)) →
      ∀ y a m, a + m ≤ n → m ≤ 23 + 0 → chargeSum P win y m (run P win a e0) ≤ 0 := by
    intro n hn y a m ham _
    have := chargeSum_zero P win y m (run P win a e0) (fun i hi => by
      rw [← run_add]
      exact hn (a + i) (by omega))
    omega
  -- valid heads whenever ready, up to a clean horizon
  have hHV : ∀ n, (∀ t, t < n → NoStall win (run P win t e0) ∧ NoBr1 P (run P win t e0)) →
      ∀ y, P.live y = true → (run P win n e0).ts y ≤ (run P win n e0).now →
        (run P win n e0).headValid y = true := by
    intro n hn y hy hrdy
    have hdy := hd y hy
    exact head_valid_when_ready P win y e0 (P.dly y) 14 0 n hW hfull hy rfl
      (by omega) (by omega)
      (fun t ht hwb => hRof n (fun t ht => (hn t ht).1) y hy t ht hwb)
      (fun a m ham hm => hBof n (fun t ht => (hn t ht).2) y a m ham hm)
      n (Nat.le_refl n) hrdy
  have key : ∀ n, ∀ t, t < n →
      NoStall win (run P win t e0) ∧ NoBr1 P (run P win t e0) := by
    intro n
    induction n with
    | zero =>
      intro t ht
      exact absurd ht (Nat.not_lt_zero t)
    | succ n ih =>
      intro t ht
      rcases Nat.lt_or_ge t n with htn | htn
      · exact ih t htn
      · have hteq : t = n := by omega
        rw [hteq]
        constructor
        · -- no stall at n
          unfold NoStall
          intro _hidle w hw
          obtain ⟨hlive, hrdy⟩ := hwin _ w hw
          exact hHV n ih w hlive hrdy
        · -- no branch-1 issue at n
          unfold NoBr1
          intro _hscan
          cases hb : br1 P (run P win n e0) with
          | none => rfl
          | some w =>
            exfalso
            obtain ⟨hlive, hinv⟩ := br1_spec P _ w hb
            cases n with
            | zero =>
              have hv : (run P win 0 e0).headValid w = true := hfull w _ hlive
              rw [hv] at hinv
              cases hinv
            | succ m =>
              -- last cycle's winner was w: ready, with a valid head
              have hwq : win (run P win m e0) = some w := by
                have := br1_winq P _ w hb
                rw [run_succ'] at this
                exact this
              have hrdy := (hwin _ w hwq).2
              have hvalid := hHV m (fun t ht => ih t (by omega)) w hlive hrdy
              -- so it wrote back at m, and now owes both slots
              have hinv' : (step P win (run P win m e0)).headValid w = false := by
                rw [← run_succ']
                exact hinv
              have hwb := head_drop_wb P win (run P win m e0) w hvalid hinv'
              have hH : HeadFirst (run P win (m + 1) e0) := by
                have hw := wf_run P win (m + 1) e0 hW
                unfold Wf at hw
                exact hw.2.1
              have h2 := owed_two_of_head _ w hH hinv
              have hown := owed_run P win w (m + 1) e0 hS
              have h0w := owed_full e0 w (fun s => hfull w s hlive)
              have hcb := cnt_succ_back P win (IsWB w) m e0
              rw [if_pos hwb] at hcb
              have hJ : 1 ≤ cnt P win (IsWB w) m e0 := by omega
              have hdw := hd w hlive
              -- the refill owed at the previous writeback is still pending at m + 1
              -- writeback #(J − 1) of w, at some w' < m: its refill is still pending at m + 1
              obtain ⟨w', hw'm, hw'k, hw'b⟩ :=
                cnt_reach P win (IsWB w) m e0 (cnt P win (IsWB w) m e0 - 1) (by omega)
              have hpb := pending_bound P win w e0 (P.dly w) 14 0 (m + 1) hW hfull hlive rfl
                (by omega)
                (fun t ht hwb' => hRof (m + 1) (fun t ht => (ih t ht).1) w hlive t ht hwb')
                (fun a k hak hk => hBof (m + 1) (fun t ht => (ih t ht).2) w a k hak hk)
                (cnt P win (IsWB w) m e0 - 1) (m + 1) w' (Nat.le_refl _) (by omega) hw'k hw'b
                (by omega)
              -- ... yet w was ready at m, one full writeback after w': at least d later
              have hsp := ts_spacing P win w e0 w' (m - w')
              have hmw : w' + (m - w') = m := by omega
              rw [hmw, hw'k] at hsp
              have h1 : cnt P win (IsWB w) m e0 - (cnt P win (IsWB w) m e0 - 1) = 1 := by omega
              rw [h1, Nat.mul_one] at hsp
              have hnow := now_run P win m e0
              omega
  intro T
  exact key (T + 1) T (Nat.lt_succ_self T)

#print axioms dstar39

end JLane
