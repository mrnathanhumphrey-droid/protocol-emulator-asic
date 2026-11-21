import JLane.CountBK
import JLane.HfreeR
import JLane.SchedK11
/-!
# Brick C3e — the per-lane response bounds closed on `runBK` (`slot_on_composition`, closure step 4b)

`RespClose.wb_close` closed every lane's bound `R y + 2` on `run` by strong induction over time.
`wb_closeBK` is the same closure on the buffered engine with flushes, from
`RespWinB.wb_bound_winBK_fl` (`K = R y + 1`):

* `hnf` — free on every `runBK` (`HfreeR.hnf_runBK`);
* `hfree` — from the induction and `HrelR` (`HfreeR.hfree_runBK`);
* `hM` — every other lane `z` is decided at most `m z` times in the window, its decisions being
  `σ z` apart (`hsep`, given the induction's bound on the first one's writeback) and
  `σ z · m z ≥ R y + 1` (`cntBK_sparse_g`), split over the lanes (`cntBK_decOther_split`,
  `cntBK_decAny_split`);
* `hS` — a premise, asked only of the window where `y` waits (ready, undecided, decided at its
  end, unflushed through it).

On the bridged run (`wb_closeBK_K11`) every premise is discharged: `hsep` by
`HfreeB.hsep_bridged`, `hrel` by `HfreeR.hrelR_bridged`, `hwin` through the mask
(`SchedK11.winA_some`), and `hS` with `S = 0` under K11 and (b′) (`noDec_zero_K11`): in the
window `y` is unarmed (armed, it would stay armed to its decision -- `armed_persist` -- and an
armed lane is never decided, `arm_no_dec`), so the masked dispatcher chooses as `win`
(`winS_eq_of_K11`), which names a lane (`hws`) with a valid head (`BPrimeWin`): no idle cycle
goes undecided.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- All decisions, split by lane, along `runBK`. -/
theorem cntBK_decAny_split (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) :
    ∀ (n : Nat) (X : EngBK),
      cntBK P win usb sreq fl k (fun e => decAny win e = true) n X
        = cntBK P win usb sreq fl k (Dec win L0) n X + cntBK P win usb sreq fl k (Dec win L1) n X
          + cntBK P win usb sreq fl k (Dec win L2) n X + cntBK P win usb sreq fl k (Dec win L3) n X
          + cntBK P win usb sreq fl k (Dec win L4) n X
  | 0, X => by simp [cntBK]
  | n + 1, X => by
    have ih := cntBK_decAny_split fl k n (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X)
    have h := decAny_split win X.x.e
    have e0 : cntBK P win usb sreq fl k (fun e => decAny win e = true) (n + 1) X
        = (if decAny win X.x.e = true then 1 else 0)
          + cntBK P win usb sreq fl k (fun e => decAny win e = true) n
            (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    have e1 : cntBK P win usb sreq fl k (Dec win L0) (n + 1) X
        = (if Dec win L0 X.x.e then 1 else 0) + cntBK P win usb sreq fl k (Dec win L0) n
            (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    have e2 : cntBK P win usb sreq fl k (Dec win L1) (n + 1) X
        = (if Dec win L1 X.x.e then 1 else 0) + cntBK P win usb sreq fl k (Dec win L1) n
            (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    have e3 : cntBK P win usb sreq fl k (Dec win L2) (n + 1) X
        = (if Dec win L2 X.x.e then 1 else 0) + cntBK P win usb sreq fl k (Dec win L2) n
            (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    have e4 : cntBK P win usb sreq fl k (Dec win L3) (n + 1) X
        = (if Dec win L3 X.x.e then 1 else 0) + cntBK P win usb sreq fl k (Dec win L3) n
            (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    have e5 : cntBK P win usb sreq fl k (Dec win L4) (n + 1) X
        = (if Dec win L4 X.x.e then 1 else 0) + cntBK P win usb sreq fl k (Dec win L4) n
            (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    omega

/-- No event in the first `t` cycles: the counter is 0. -/
theorem cntBK_zero_of (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (Q : Engine → Prop)
    [DecidablePred Q] (t : Nat) (X : EngBK)
    (h : ∀ s, s < t → ¬Q (runBK P win usb sreq fl k s X).x.e) :
    cntBK P win usb sreq fl k Q t X = 0 := by
  rcases Nat.eq_zero_or_pos (cntBK P win usb sreq fl k Q t X) with h0 | hpos
  · exact h0
  · obtain ⟨s, hs, _, hq⟩ := cntBK_reach P win usb sreq fl k Q t X 0 hpos
    exact absurd hq (h s hs)

/-- **The per-lane response bounds, closed on `runBK`.** Under the conditional program facts,
every writeback of every live lane `y` before `T` lands within `R y + 2` of its release. -/
theorem wb_closeBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (T S : Nat)
    (R m σ : Lane → Nat)
    (h0 : X0.x.e.st = .idle) (h0ts : ∀ l, X0.x.e.now ≤ X0.x.e.ts l)
    (hwin : ∀ e w, win e = some w → P.live w = true)
    (hσ : ∀ z, 1 ≤ σ z)
    (hS : ∀ y c, P.live y = true → c + (R y + 1) + 2 ≤ T →
      (∀ i, i < R y + 1 → Ready P y (runBK P win usb sreq fl k (c + i) X0).x.e ∧
        ¬Dec win y (runBK P win usb sreq fl k (c + i) X0).x.e) →
      Dec win y (runBK P win usb sreq fl k (c + (R y + 1)) X0).x.e →
      (∀ i, i ≤ R y + 1 → fl (runBK P win usb sreq fl k (c + i) X0).x.e.now y = false) →
      cntBK P win usb sreq fl k (fun e => noDecB win e = true) (R y + 1)
        (runBK P win usb sreq fl k c X0) ≤ S)
    (hsep : ∀ z a b, a < b → Dec win z (runBK P win usb sreq fl k a X0).x.e →
      Dec win z (runBK P win usb sreq fl k b X0).x.e →
      (runBK P win usb sreq fl k (a + 2) X0).x.e.now
        ≤ (runBK P win usb sreq fl k (a + 2) X0).x.e.ts z + R z + 2 → a + σ z ≤ b)
    (hrel : ∀ y, HrelR P win usb sreq fl k X0 y (R y + 1))
    (hmul : ∀ y z, z ≠ y → R y + 1 ≤ σ z * m z)
    (hK : ∀ y, 3 * (m L0 + m L1 + m L2 + m L3 + m L4 - m y) + S + 3 ≤ R y + 1) :
    ∀ t, t < T → ∀ y, P.live y = true → IsWB y (runBK P win usb sreq fl k t X0).x.e →
      (runBK P win usb sreq fl k t X0).x.e.now
        ≤ (runBK P win usb sreq fl k t X0).x.e.ts y + R y + 2 := by
  have key : ∀ n, ∀ t, t < n → t < T → ∀ y, P.live y = true →
      IsWB y (runBK P win usb sreq fl k t X0).x.e →
      (runBK P win usb sreq fl k t X0).x.e.now
        ≤ (runBK P win usb sreq fl k t X0).x.e.ts y + R y + 2 := by
    intro n
    induction n with
    | zero => intro t ht; exact absurd ht (Nat.not_lt_zero t)
    | succ n ih =>
      intro t ht htT y hy hwb
      rcases Nat.lt_or_ge t n with htn | htn
      · exact ih t htn htT y hy hwb
      · have IH : ∀ t', t' < t → ∀ z, P.live z = true →
            IsWB z (runBK P win usb sreq fl k t' X0).x.e →
            (runBK P win usb sreq fl k t' X0).x.e.now
              ≤ (runBK P win usb sreq fl k t' X0).x.e.ts z + R z + 2 :=
          fun t' h' => ih t' (by omega) (by omega)
        have hw := wb_bound_winBK_fl P win usb sreq fl k X0 h0 h0ts y hy
          (m L0 + m L1 + m L2 + m L3 + m L4 - m y) S (R y + 1) (hK y) t hwb
          (hnf_runBK P win usb sreq fl k X0 y t)
          (hfree_runBK P win usb sreq fl k X0 y (R y + 1) t hwb (hrel y)
            (fun w hw hwbw => by
              have := IH w hw y hy hwbw
              omega))
          (fun c hc => by
            have hz : ∀ z, z ≠ y → cntBK P win usb sreq fl k (Dec win z) (R y + 1)
                (runBK P win usb sreq fl k c X0) ≤ m z := by
              intro z hzy
              apply cntBK_sparse_g P win usb sreq fl k (Dec win z) (runBK P win usb sreq fl k c X0)
                (σ z) (hσ z) (m z) (R y + 1) (hmul y z hzy)
              intro i j hij hj hqi hqj
              rw [← runBK_add] at hqi hqj
              have hlz := hwin _ z hqi.2.1
              have hr := IH (c + i + 2) (by omega) z hlz
                (dec_wbBK P win usb sreq fl k X0 (c + i) z hqi)
              have := hsep z (c + i) (c + j) (by omega) hqi hqj hr
              omega
            have hs := cntBK_decOther_split P win usb sreq fl k y (R y + 1)
              (runBK P win usb sreq fl k c X0)
            have ha := cntBK_decAny_split P win usb sreq fl k (R y + 1)
              (runBK P win usb sreq fl k c X0)
            rcases lane_cases y with rfl | rfl | rfl | rfl | rfl
            · have a := hz L1 (by decide); have b := hz L2 (by decide)
              have c' := hz L3 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L2 (by decide)
              have c' := hz L3 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L1 (by decide)
              have c' := hz L3 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L1 (by decide)
              have c' := hz L2 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L1 (by decide)
              have c' := hz L2 (by decide); have d := hz L3 (by decide); omega)
          (fun c hc hrd hd hf => hS y c hy (by omega) hrd hd hf)
        omega
  intro t ht
  exact key (t + 1) t (Nat.lt_succ_self t) ht

end

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)
  (kt : Nat → Lane → Nat) (A0 : EngBA)

/-- **Armed until a hit**: an armed lane stays armed while it is not hit. -/
theorem armed_persist (y : Lane) (m : Nat)
    (ha : (runBA P win usb sreq isArm edge kt m A0).armed y = true) :
    ∀ d, (∀ j, j < d → (runBA P win usb sreq isArm edge kt (m + j) A0).hit y = false) →
      (runBA P win usb sreq isArm edge kt (m + d) A0).armed y = true
  | 0, _ => ha
  | d + 1, h => by
    have ih := armed_persist y m ha d (fun j hj => h j (by omega))
    have hh := h d (by omega)
    rw [show m + (d + 1) = (m + d) + 1 from rfl, runBA_succ, stepBA_armed, hh]
    simp only [Bool.false_eq_true, if_false, ih]
    split <;> rfl

/-- **`y` is unarmed while it waits**: decided at the window's end and unflushed through it. -/
theorem unarmed_in_window (y : Lane) (c K : Nat)
    (hdec : Dec (winS P win usb sreq isArm edge kt A0) y
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt (c + K) A0.X).x.e)
    (hnf : ∀ i, i ≤ K → flS P win usb sreq isArm edge kt A0
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt (c + i) A0.X).x.e.now y = false) :
    ∀ i, i < K → (runBA P win usb sreq isArm edge kt (c + i) A0).armed y = false := by
  intro i hi
  cases ha : (runBA P win usb sreq isArm edge kt (c + i) A0).armed y with
  | false => rfl
  | true =>
    exfalso
    have hp := armed_persist P win usb sreq isArm edge kt A0 y (c + i) ha (K - i)
      (fun j hj => by
        rw [← flS_runBK P win usb sreq isArm edge kt A0, show c + i + j = c + (i + j) by omega]
        exact hnf (i + j) (by omega))
    rw [show c + i + (K - i) = c + K by omega] at hp
    exact arm_no_dec P win usb sreq isArm edge kt A0 (c + K) y hp hdec

/-- **`hS = 0` under K11 and (b′)** on the bridged run: in the window where `y` waits, no idle
cycle goes undecided. -/
theorem noDec_zero_K11 (hb : BPrimeWin win)
    (hws : ∀ y e, e.st = .idle → Ready P y e → win e ≠ none)
    (hK11 : ∀ n, K11At P win (runBA P win usb sreq isArm edge kt n A0).armed
      (runBA P win usb sreq isArm edge kt n A0).X.x.e)
    (y : Lane) (c K : Nat)
    (hw : ∀ i, i < K → Ready P y (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt (c + i) A0.X).x.e ∧
      ¬Dec (winS P win usb sreq isArm edge kt A0) y (runBK P (winS P win usb sreq isArm edge kt A0)
        usb sreq (flS P win usb sreq isArm edge kt A0) kt (c + i) A0.X).x.e)
    (hdec : Dec (winS P win usb sreq isArm edge kt A0) y
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt (c + K) A0.X).x.e)
    (hnf : ∀ i, i ≤ K → flS P win usb sreq isArm edge kt A0
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt (c + i) A0.X).x.e.now y = false) :
    cntBK P (winS P win usb sreq isArm edge kt A0) usb sreq (flS P win usb sreq isArm edge kt A0) kt
      (fun e => noDecB (winS P win usb sreq isArm edge kt A0) e = true) K
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt c A0.X) = 0 := by
  apply cntBK_zero_of
  intro i hi hn
  rw [← runBK_add] at hn
  have hu := unarmed_in_window P win usb sreq isArm edge kt A0 y c K hdec hnf i hi
  have heq := winS_eq_of_K11 P win usb sreq isArm edge kt A0 hK11 (c + i) y hu (hw i hi).1
  unfold noDecB at hn
  rw [heq] at hn
  cases hst : (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
      (flS P win usb sreq isArm edge kt A0) kt (c + i) A0.X).x.e.st with
  | idle =>
    cases hwn : win (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt (c + i) A0.X).x.e with
    | none => exact hws y _ hst (hw i hi).1 hwn
    | some v =>
      rw [hwn] at hn
      simp [hb _ v hwn] at hn
  | drive => rw [hst] at hn; simp at hn
  | wb => rw [hst] at hn; simp at hn

/-- **The per-lane bounds closed on the bridged run** (`slot_on_composition` L4 hM/hS): every
premise of `wb_closeBK` discharged -- `hsep` (`hsep_bridged`), `hrel` (`hrelR_bridged`), `hwin`
through the mask, `hS` with `S = 0` (`noDec_zero_K11`) -- from the armed run's invariant, the
scheduler contracts (`hwin`, `hws`, (b′), K11) and the gaps of the non-arming writebacks. -/
theorem wb_closeBK_K11 (hedge : ∀ t l, t + 1 ≤ edge t l) (hA : ArmInvB A0)
    (h0 : A0.X.x.e.st = .idle) (h0a : ∀ l, A0.armed l = false)
    (h0ts : ∀ l, A0.X.x.e.now ≤ A0.X.x.e.ts l)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hb : BPrimeWin win) (hws : ∀ y e, e.st = .idle → Ready P y e → win e ≠ none)
    (hK11 : ∀ n, K11At P win (runBA P win usb sreq isArm edge kt n A0).armed
      (runBA P win usb sreq isArm edge kt n A0).X.x.e)
    (T : Nat) (R m σ : Lane → Nat) (hσ : ∀ z, 1 ≤ σ z) (hσ4 : ∀ z, σ z ≤ 4)
    (hgap : ∀ z x, IsWB z (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt x A0.X).x.e →
      (runBA P win usb sreq isArm edge kt x A0).arms P isArm z = false →
      σ z + R z ≤ P.dly z + P.ext (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt x A0.X).x.e.now z ∧
        R z + 3 ≤ P.dly z + P.ext (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt x A0.X).x.e.now z)
    (hmul : ∀ y z, z ≠ y → R y + 1 ≤ σ z * m z)
    (hK : ∀ y, 3 * (m L0 + m L1 + m L2 + m L3 + m L4 - m y) + 0 + 3 ≤ R y + 1) :
    ∀ t, t < T → ∀ y, P.live y = true →
      IsWB y (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt t A0.X).x.e →
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt t A0.X).x.e.now
        ≤ (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt t A0.X).x.e.ts y + R y + 2 :=
  wb_closeBK P (winS P win usb sreq isArm edge kt A0) usb sreq
    (flS P win usb sreq isArm edge kt A0) kt A0.X T 0 R m σ h0 h0ts
    (fun e w h => (hwin e w (winA_some win _ e w h)).1) hσ
    (fun y c _ _ hrd hd hf => Nat.le_of_eq
      (noDec_zero_K11 P win usb sreq isArm edge kt A0 hb hws hK11 y c (R y + 1) hrd hd hf))
    (fun z a b hab hda hdb hr => hsep_bridged P win usb sreq isArm edge kt A0 hedge hA h0 h0a
      (fun e w h => (hwin e w h).2) z (σ z) (R z) (hσ4 z)
      (fun x hx ha => (hgap z x hx ha).1) b a hab hda hdb hr)
    (fun y => hrelR_bridged P win usb sreq isArm edge kt A0 hedge hA h0 y (R y + 1)
      (fun x hx ha => by
        have := (hgap y x hx ha).2
        omega))
    hmul hK

end

end JLane
