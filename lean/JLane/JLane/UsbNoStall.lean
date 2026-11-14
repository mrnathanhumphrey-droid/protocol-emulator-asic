import JLane.EdfUsb
/-!
# Brick N — the USB lane never stalls, branch-1 allowed (Wilson 11-13, revised ruling)

A real USB device decides and re-arms within ~80 cycles of each packet, so its words retire
20–33 cycles apart, back to back: no per-pair spacing rule can hold for it, and "no branch-1"
is not the property that matters. This brick proves what does:

* `usb_nostall`: from a primed start, no dispatch ever stalls, and **branch 1 only ever issues
  for the USB lane** — for any USB program whose words all have delay `≥ NOWB_MIN` (20), with the
  deadline margin `USB_DEADLINE_MARGIN` (17) and every other live lane at
  `≥ CORESIDENT_USB = R_USB + 25 + BR1_BUDGET = 50`;
* `usb_j2_nb`: under the same hypotheses the USB lane's samples keep `J ≤ 2`;
* `usb_br1_window`: in any window of `23 + BR1_BUDGET = 31` cycles, at most
  `USB_BR1_PER_WINDOW = 2` USB-lane branch-1 refills — **proved**, from the USB lane's decision
  lateness `≤ 2` and its delay `≥ 20`, which space its retirements `≥ 18` apart.

How: a USB branch-1 at a scan cycle `t` follows a USB retirement at `t − 1` (the head was valid
when the lane was last the winner). The USB lane's head is valid whenever it is ready
(`2 + 25 + 0 < 20 + 20`: its own refills are never charged, since no other lane branch-1s), and
the other lanes' (`17 + 25 + 8 < 50 + 50`, `D* + 8 ≤ 50`); the other lanes never branch-1
(retirement spacing `≥ 17 + 25 + 8 = 50`).
-/
namespace JLane

/-- Branch 1, if it issues this cycle, issues for lane `u`. -/
def Br1Only (P : Program) (u : Lane) (e : Engine) : Prop :=
  e.pst = .scan → ∀ w, br1 P e = some w → w = u

/-- A USB-lane branch-1 issue this cycle. -/
def UBr1 (P : Program) (u : Lane) (e : Engine) : Prop :=
  e.pst = .scan ∧ br1 P e = some u

instance (P : Program) (u : Lane) (e : Engine) : Decidable (UBr1 P u e) :=
  inferInstanceAs (Decidable (e.pst = .scan ∧ br1 P e = some u))

/-- A nonzero charge against lane `y` this cycle. -/
def Charged (P : Program) (y : Lane) (e : Engine) : Prop := charge P y e ≠ 0

instance (P : Program) (y : Lane) (e : Engine) : Decidable (Charged P y e) :=
  inferInstanceAs (Decidable (charge P y e ≠ 0))

/-! ### Counting -/

theorem charge_le (P : Program) (y : Lane) (e : Engine) : charge P y e ≤ L_REFILL := by
  unfold charge
  split
  · split <;> omega
  · omega

theorem charged_ubr1 (P : Program) (u y : Lane) (e : Engine) (h : Charged P y e)
    (ho : Br1Only P u e) : UBr1 P u e := by
  unfold Charged charge at h
  cases hb : br1 P e with
  | none => rw [hb] at h; exact absurd rfl h
  | some w =>
    rw [hb] at h
    dsimp only at h
    by_cases hc : e.pst = .scan ∧ w ≠ y
    · have hw := ho hc.1 w hb
      rw [hw] at hb
      exact ⟨hc.1, hb⟩
    · rw [if_neg hc] at h
      exact absurd rfl h

theorem chargeSum_le_cnt (P : Program) (win : Engine → Option Lane) (y : Lane) :
    ∀ (m : Nat) (e : Engine), chargeSum P win y m e ≤ L_REFILL * cnt P win (Charged P y) m e
  | 0, _ => Nat.zero_le _
  | m + 1, e => by
    have ih := chargeSum_le_cnt P win y m (step P win e)
    show charge P y e + chargeSum P win y m (step P win e) ≤
      L_REFILL * ((if Charged P y e then 1 else 0) + cnt P win (Charged P y) m (step P win e))
    have hl := charge_le P y e
    by_cases hc : Charged P y e
    · rw [if_pos hc]
      rw [Nat.mul_add]
      omega
    · rw [if_neg hc, Nat.zero_add]
      have : charge P y e = 0 := Decidable.of_not_not hc
      omega

/-- At most one event per 16 cycles: at most `⌈m / 16⌉` of them in `m` cycles. -/
theorem cnt_sparse (P : Program) (win : Engine → Option Lane) (Q : Engine → Prop)
    [DecidablePred Q] (e : Engine) :
    ∀ N m, m ≤ N → (∀ i j, i < j → j < m → Q (run P win i e) → Q (run P win j e) → i + 16 ≤ j) →
      cnt P win Q m e ≤ (m + 15) / 16 := by
  intro N
  induction N with
  | zero =>
    intro m hm _
    have : m = 0 := by omega
    subst this
    simp [cnt]
  | succ N ih =>
    intro m hm hsep
    rcases Nat.lt_or_ge m (N + 1) with hlt | hge
    · exact ih m (by omega) hsep
    · have hmN : m = N + 1 := by omega
      subst hmN
      rw [cnt_succ_back]
      have hsep' : ∀ i j, i < j → j < N → Q (run P win i e) → Q (run P win j e) → i + 16 ≤ j :=
        fun i j hij hj => hsep i j hij (by omega)
      by_cases hq : Q (run P win N e)
      · rw [if_pos hq]
        rcases Nat.lt_or_ge N 15 with hs | hs
        · have h0 : cnt P win Q N e = 0 := cnt_zero_of P win Q N e (fun s hs' hqs => by
            have := hsep s N hs' (by omega) hqs hq
            omega)
          omega
        · have hsplit := cnt_add P win Q (N - 15) 15 e
          have hN : N - 15 + 15 = N := by omega
          rw [hN] at hsplit
          have hz : cnt P win Q 15 (run P win (N - 15) e) = 0 :=
            cnt_zero_of P win Q 15 _ (fun s hs' hqs => by
              rw [← run_add] at hqs
              have := hsep (N - 15 + s) N (by omega) (by omega) hqs hq
              omega)
          have hrec := ih (N - 15) (by omega) (fun i j hij hj => hsep i j hij (by omega))
          omega
      · rw [if_neg hq]
        have := ih N (Nat.le_refl N) hsep'
        omega

/-! ### The dispatch FSM is idle at least once in any three cycles -/

theorem idle3 (P : Program) (win : Engine → Option Lane) (e0 : Engine) (c : Nat) :
    ∃ s, c ≤ s ∧ s ≤ c + 2 ∧ (run P win s e0).st = .idle := by
  cases hs : (run P win c e0).st with
  | idle => exact ⟨c, Nat.le_refl c, by omega, hs⟩
  | wb =>
    refine ⟨c + 1, by omega, by omega, ?_⟩
    rw [run_succ']
    exact step_wb_idle P win _ hs
  | drive =>
    refine ⟨c + 2, by omega, Nat.le_refl _, ?_⟩
    have h1 := (step_drive P win (run P win c e0) hs).1
    show (run P win ((c + 1) + 1) e0).st = .idle
    rw [run_succ', run_succ']
    exact step_wb_idle P win _ h1

section
variable (P : Program) (win : Engine → Option Lane) (e0 : Engine) (u : Lane) (ds : Lane → Nat)
  (hW : Wf e0) (hfull : ∀ l s, P.live l = true → e0.actv l s = true)
  (hfn : ∀ e, P.fnpf e = false) (hn0 : e0.NoNpf)
  (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l)
  (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
  (hws : ∀ y e, e.st = .idle → Ready P y e → win e ≠ none)
  (hdu : NOWB_MIN ≤ P.dly u)
  (hd : ∀ l, P.live l = true → l ≠ u → CORESIDENT_USB ≤ P.dly l)
  (hedf : EdfBeats P ds win u)
  (hmargin : ∀ z, P.live z = true → z ≠ u → ds u + USB_DEADLINE_MARGIN ≤ ds z)

include hd in
theorem hd42 : ∀ l, P.live l = true → l ≠ u → DSTAR_RETIRE_USB ≤ P.dly l := fun l hl hlu => by
  have := hd l hl hlu
  have h1 : CORESIDENT_USB = 50 := rfl
  have h2 : DSTAR_RETIRE_USB = 42 := rfl
  omega

/-! ### On a stall-free prefix -/

include h0 h0ts hwin hws hdu hd hedf hmargin in
/-- `usb_wins` on a stall-free prefix. -/
theorem usb_wins_pre (n : Nat) (hNSp : ∀ t, t < n → NoStall win (run P win t e0)) :
    ∀ s, s < n → (run P win s e0).st = .idle → Ready P u (run P win s e0) →
      win (run P win s e0) = some u := by
  intro s hsn hid hr
  cases hw : win (run P win s e0) with
  | none => exact absurd hw (hws u _ hid hr)
  | some w =>
    by_cases hwu : w = u
    · rw [hwu]
    · exfalso
      have hb := hedf _ w hw hwu hr
      have hlw := (hwin _ w hw).1
      have hm := hmargin w hlw hwu
      have hru := hr.2
      have hdec : Dec win w (run P win s e0) := ⟨hid, hw, hNSp s hsn hid w hw⟩
      have hst1 := (step_of_dec P win _ w hdec).1
      have hst2 := (dec_wb P win e0 s w hdec).1
      have hNS3 : ∀ t', t' < s + 3 → NoStall win (run P win t' e0) := fun t' ht' => by
        rcases Nat.lt_or_ge s t' with hlt | hge
        · intro hidle
          exfalso
          have : t' = s + 1 ∨ t' = s + 2 := by omega
          rcases this with rfl | rfl
          · rw [run_succ', hst1] at hidle
            cases hidle
          · rw [hst2] at hidle
            cases hidle
        · exact hNSp t' (by omega)
      have hwb := dec_wb P win e0 s w hdec
      have hR := wb_bound_usb P win e0 (s + 3) u h0 h0ts hwin hws hdu (hd42 P u hd) hNS3
        (s + 2) (by omega) w hlw hwb
      obtain ⟨hts2, hnow2⟩ := dec_ts P win e0 s w hdec
      rw [hts2, hnow2] at hR
      have hRv : R_USB = 17 := rfl
      have hMv : USB_DEADLINE_MARGIN = 17 := rfl
      omega

include h0 h0ts hwin hws hdu hd hedf hmargin in
/-- **The USB lane is decided at most 2 cycles after its release**, on a stall-free prefix. -/
theorem usb_dec_late (n : Nat) (hNSp : ∀ t, t < n → NoStall win (run P win t e0)) :
    ∀ D, D < n → Dec win u (run P win D e0) →
      (run P win D e0).now ≤ (run P win D e0).ts u + 2 := by
  have key : ∀ N, ∀ D, D < N → D < n → Dec win u (run P win D e0) →
      (run P win D e0).now ≤ (run P win D e0).ts u + 2 := by
    intro N
    induction N with
    | zero => intro D hD; exact absurd hD (Nat.not_lt_zero D)
    | succ N ih =>
      intro D hDN hDn hdec
      by_cases hok : (run P win D e0).now ≤ (run P win D e0).ts u + 2
      · exact hok
      · exfalso
        have hnD := now_run P win D e0
        have hlu : P.live u = true := (hwin _ u hdec.2.1).1
        rcases Nat.lt_or_ge D 3 with hD3 | hD3
        · have hm := ts_mono P win u e0 0 D (Nat.zero_le D)
          have h00 : (run P win 0 e0).ts u = e0.ts u := rfl
          have := h0ts u
          omega
        · obtain ⟨s, hcs, hsc, hid⟩ := idle3 P win e0 (D - 3)
          have hsD : s < D := by omega
          have hrs : Ready P u (run P win s e0) := by
            refine ⟨hlu, ?_⟩
            have hm := ts_mono P win u e0 s D (by omega)
            have hns := now_run P win s e0
            omega
          have hws' := usb_wins_pre P win e0 u ds h0 h0ts hwin hws hdu hd hedf hmargin n hNSp
            s (by omega) hid hrs
          have hds : Dec win u (run P win s e0) := ⟨hid, hws', hNSp s (by omega) hid u hws'⟩
          have hsep := dec_sep P win e0 u s D hsD hds hdec
          have hsc' : s = D - 3 := by omega
          have hls := ih s (by omega) (by omega) hds
          have hgap := dec_gap P win e0 u hwin s D hsD hds hdec
          have hns := now_run P win s e0
          have hNv : NOWB_MIN = 20 := rfl
          omega
  intro D hDn hdec
  exact key (D + 1) D (Nat.lt_succ_self D) hDn hdec

include h0 h0ts hwin hws hdu hd hedf hmargin in
/-- Two USB decisions on a stall-free prefix are `≥ NOWB_MIN − 2 = 18` cycles apart. -/
theorem usb_dec_sep18 (n : Nat) (hNSp : ∀ t, t < n → NoStall win (run P win t e0))
    (a b : Nat) (hab : a < b) (hbn : b < n) (ha : Dec win u (run P win a e0))
    (hb : Dec win u (run P win b e0)) : a + 18 ≤ b := by
  have hl := usb_dec_late P win e0 u ds h0 h0ts hwin hws hdu hd hedf hmargin n hNSp a (by omega) ha
  have hg := dec_gap P win e0 u hwin a b hab ha hb
  have hna := now_run P win a e0
  have hnb := now_run P win b e0
  have hNv : NOWB_MIN = 20 := rfl
  omega

/-- The prefix facts the main induction carries. -/
def Good (n : Nat) : Prop :=
  ∀ t, t < n → NoStall win (run P win t e0) ∧ Br1Only P u (run P win t e0)

/-- Every live lane's head is valid whenever it is ready, at cycle `n`. -/
def HVat (n : Nat) : Prop :=
  ∀ y, P.live y = true → (run P win n e0).ts y ≤ (run P win n e0).now →
    (run P win n e0).headValid y = true

include hfull hwin in
/-- A USB branch-1 at cycle `t` follows a USB retirement at `t − 1`. -/
theorem ubr1_after_ret (t : Nat) (hHV : ∀ s, s < t → HVat P win e0 s)
    (hU : UBr1 P u (run P win t e0)) :
    ∃ m, t = m + 1 ∧ IsRet P u (run P win m e0) := by
  obtain ⟨_, hb⟩ := hU
  obtain ⟨hlive, hinv⟩ := br1_spec P _ u hb
  cases t with
  | zero =>
    exfalso
    have hv : (run P win 0 e0).headValid u = true := hfull u _ hlive
    rw [hv] at hinv
    cases hinv
  | succ m =>
    refine ⟨m, rfl, ?_⟩
    have hwq : win (run P win m e0) = some u := by
      have := br1_winq P _ u hb
      rw [run_succ'] at this
      exact this
    exact head_drop_wb P win (run P win m e0) u
      (hHV m (Nat.lt_succ_self m) u hlive ((hwin _ u hwq).2))
      (by rw [← run_succ']; exact hinv)

include hfull h0 h0ts hwin hws hdu hd hedf hmargin in
/-- **The budget**: on a good prefix with valid heads, any window of `≤ 23 + BR1_BUDGET` cycles
carries at most `BR1_BUDGET` of branch-1 charge against any lane. -/
theorem budget (n : Nat) (hG : Good P win e0 u n) (hHV : ∀ s, s < n → HVat P win e0 s)
    (y : Lane) (a m : Nat) (ham : a + m ≤ n) (hm : m ≤ 23 + BR1_BUDGET) :
    chargeSum P win y m (run P win a e0) ≤ BR1_BUDGET := by
  have hNSp : ∀ t, t < n → NoStall win (run P win t e0) := fun t ht => (hG t ht).1
  -- a charged cycle a + i is a USB branch-1, right after a USB retirement, decided at a + i - 3
  have hdec_of : ∀ i, i < m → Charged P y (run P win i (run P win a e0)) →
      ∃ D, a + i = D + 3 ∧ Dec win u (run P win D e0) := by
    intro i hi hc
    rw [← run_add] at hc
    have hU := charged_ubr1 P u y _ hc (hG (a + i) (by omega)).2
    obtain ⟨mm, hmm, hret⟩ := ubr1_after_ret P win e0 u hfull hwin (a + i)
      (fun s hs => hHV s (by omega)) hU
    obtain ⟨D, hD, hdec⟩ := wb_back P win e0 h0 mm u (isWB_of_ret P u _ hret)
    exact ⟨D, by omega, hdec⟩
  have hsep : ∀ i j, i < j → j < m → Charged P y (run P win i (run P win a e0)) →
      Charged P y (run P win j (run P win a e0)) → i + 16 ≤ j := by
    intro i j hij hj hci hcj
    obtain ⟨Di, hDi, hdi⟩ := hdec_of i (by omega) hci
    obtain ⟨Dj, hDj, hdj⟩ := hdec_of j hj hcj
    have := usb_dec_sep18 P win e0 u ds h0 h0ts hwin hws hdu hd hedf hmargin n hNSp Di Dj
      (by omega) (by omega) hdi hdj
    omega
  have hc := cnt_sparse P win (Charged P y) (run P win a e0) m m (Nat.le_refl m) hsep
  have hs := chargeSum_le_cnt P win y m (run P win a e0)
  have hB : BR1_BUDGET = 8 := rfl
  have hL : L_REFILL = 4 := rfl
  rw [hL] at hs
  rw [hB] at hm ⊢
  omega

include hfull h0 h0ts hwin hws hdu hd hedf hmargin in
/-- No lane but the USB lane is ever charged against the USB lane: its charge is zero. -/
theorem budget_usb (n : Nat) (hG : Good P win e0 u n) (a m : Nat) (ham : a + m ≤ n) :
    chargeSum P win u m (run P win a e0) ≤ 0 := by
  have hs := chargeSum_le_cnt P win u m (run P win a e0)
  have hz : cnt P win (Charged P u) m (run P win a e0) = 0 :=
    cnt_zero_of P win _ m _ (fun s hs' hc => by
      rw [← run_add] at hc
      obtain ⟨_, hb⟩ := charged_ubr1 P u u _ hc (hG (a + s) (by omega)).2
      unfold Charged charge at hc
      rw [hb] at hc
      simp at hc)
  rw [hz, Nat.mul_zero] at hs
  omega

include hW hfull hfn hn0 h0 h0ts hwin hws hdu hd hedf hmargin in
/-- Valid heads at `n`, from the good prefix and valid heads before `n`. -/
theorem hv_step (n : Nat) (hG : Good P win e0 u n) (hHV : ∀ s, s < n → HVat P win e0 s) :
    HVat P win e0 n := by
  have hNSp : ∀ t, t < n → NoStall win (run P win t e0) := fun t ht => (hG t ht).1
  intro y hy hrdy
  have hDv : DSTAR = 20 := rfl
  have hRv : R_USB = 17 := rfl
  have hBv : BR1_BUDGET = 8 := rfl
  have hNv : NOWB_MIN = 20 := rfl
  have hCv : CORESIDENT_USB = 50 := rfl
  by_cases hyu : y = u
  · subst hyu
    apply head_valid_ret P win y e0 (P.dly y) 2 0 n (P.dly y) hW hfull hy rfl (by omega) (fun t => nonpf_run P win hfn t e0 hn0)
      (retSpaced_of_dly P win e0 y _ (Nat.le_refl _)) (by omega)
    · intro t ht hwb
      obtain ⟨D, rfl, hdec⟩ := wb_back P win e0 h0 t y hwb
      have hl := usb_dec_late P win e0 y ds h0 h0ts hwin hws hdu hd hedf hmargin n hNSp D
        (by omega) hdec
      obtain ⟨hts2, hnow2⟩ := dec_ts P win e0 D y hdec
      rw [hts2, hnow2]
      omega
    · intro a m ham _
      exact budget_usb P win e0 y ds hfull h0 h0ts hwin hws hdu hd hedf hmargin n hG a m ham
    · exact Nat.le_refl n
    · exact hrdy
  · have hdy := hd y hy hyu
    apply head_valid_ret P win y e0 (P.dly y) R_USB BR1_BUDGET n (P.dly y) hW hfull hy rfl
      (by omega) (fun t => nonpf_run P win hfn t e0 hn0) (retSpaced_of_dly P win e0 y _ (Nat.le_refl _)) (by omega)
    · intro t ht hwb
      exact wb_bound_usb P win e0 n u h0 h0ts hwin hws hdu (hd42 P u hd) hNSp t ht y hy hwb
    · intro a m ham hm
      exact budget P win e0 u ds hfull h0 h0ts hwin hws hdu hd hedf hmargin n hG hHV y a m ham hm
    · exact Nat.le_refl n
    · exact hrdy

include hW hfull hfn hn0 h0 h0ts hwin hws hdu hd hedf hmargin in
/-- **The USB lane never stalls, and branch 1 only ever issues for it.** For any USB program
whose words have delay `≥ NOWB_MIN`, the deadline margin, and every other live lane at
`≥ CORESIDENT_USB`. -/
theorem usb_nostall : ∀ T, NoStall win (run P win T e0) ∧ Br1Only P u (run P win T e0) := by
  have hS : Struct e0 := by
    have hw := hW
    unfold Wf at hw
    exact hw.1
  have key : ∀ n, Good P win e0 u n ∧ ∀ s, s < n → HVat P win e0 s := by
    intro n
    induction n with
    | zero => exact ⟨fun t ht => absurd ht (Nat.not_lt_zero t), fun s hs => absurd hs (Nat.not_lt_zero s)⟩
    | succ n ih =>
      obtain ⟨hG, hHV⟩ := ih
      have hvn := hv_step P win e0 u ds hW hfull hfn hn0 h0 h0ts hwin hws hdu hd hedf hmargin n hG hHV
      have hHV' : ∀ s, s < n + 1 → HVat P win e0 s := fun s hs => by
        rcases Nat.lt_or_ge s n with h | h
        · exact hHV s h
        · have : s = n := by omega
          rw [this]
          exact hvn
      refine ⟨fun t ht => ?_, hHV'⟩
      rcases Nat.lt_or_ge t n with htn | htn
      · exact hG t htn
      · have hteq : t = n := by omega
        rw [hteq]
        constructor
        · intro _hidle w hw
          obtain ⟨hlive, hrdy⟩ := hwin _ w hw
          exact hvn w hlive hrdy
        · intro _hscan w hb
          by_cases hwu : w = u
          · exact hwu
          · exfalso
            obtain ⟨hlive, hinv⟩ := br1_spec P _ w hb
            cases n with
            | zero =>
              have hv : (run P win 0 e0).headValid w = true := hfull w _ hlive
              rw [hv] at hinv
              cases hinv
            | succ m =>
              have hwq : win (run P win m e0) = some w := by
                have := br1_winq P _ w hb
                rw [run_succ'] at this
                exact this
              have hrdy := (hwin _ w hwq).2
              have hvalid := hHV m (Nat.lt_succ_self m) w hlive hrdy
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
              have hcb := cnt_succ_back P win (IsRet P w) m e0
              rw [if_pos hwb] at hcb
              have hJ : 1 ≤ cnt P win (IsRet P w) m e0 := by omega
              have hdw := hd w hlive hwu
              have hDv : DSTAR = 20 := rfl
              have hRv : R_USB = 17 := rfl
              have hBv : BR1_BUDGET = 8 := rfl
              have hCv : CORESIDENT_USB = 50 := rfl
              have hNSp : ∀ t, t < m + 1 → NoStall win (run P win t e0) := fun t ht => (hG t ht).1
              obtain ⟨w', hw'm, hw'k, hw'b⟩ :=
                cnt_reach P win (IsRet P w) m e0 (cnt P win (IsRet P w) m e0 - 1) (by omega)
              have hpb := pending_bound P win w e0 (P.dly w) R_USB BR1_BUDGET (m + 1) hW hfull
                hlive rfl (by omega) (fun t => nonpf_run P win hfn t e0 hn0)
                (fun t ht hwb' => wb_bound_usb P win e0 (m + 1) u h0 h0ts hwin hws hdu
                  (hd42 P u hd) hNSp t ht w hlive hwb')
                (fun a k hak hk => budget P win e0 u ds hfull h0 h0ts hwin hws hdu hd hedf hmargin
                  (m + 1) hG hHV w a k hak hk)
                (cnt P win (IsRet P w) m e0 - 1) (m + 1) w' (Nat.le_refl _) (by omega) hw'k hw'b
                (by omega)
              have hsp := ts_ge_after_wb P win w e0 w' m hw'm (isWB_of_ret P w _ hw'b)
              have hnow := now_run P win m e0
              omega
  intro T
  exact (key (T + 1)).1 T (Nat.lt_succ_self T)

include hW hfull hfn hn0 h0 h0ts hwin hws hdu hd hedf hmargin in
/-- **`J ≤ 2` for the USB lane's samples, branch-1 allowed** (Wilson 11-13 condition 1). -/
theorem usb_j2_nb :
    ∀ t, Ready P u (run P win t e0) → NotMid u (run P win t e0) →
      ∃ j, j ≤ 2 ∧ Dec win u (run P win (t + j) e0) := by
  have hNS := fun T => (usb_nostall P win e0 u ds hW hfull hfn hn0 h0 h0ts hwin hws hdu hd hedf hmargin T).1
  have hwins : ∀ s, (run P win s e0).st = .idle → Ready P u (run P win s e0) →
      win (run P win s e0) = some u := fun s hi hr =>
    usb_wins_pre P win e0 u ds h0 h0ts hwin hws hdu hd hedf hmargin (s + 1)
      (fun t _ => hNS t) s (Nat.lt_succ_self s) hi hr
  have decAt : ∀ n, (run P win n e0).st = .idle → Ready P u (run P win n e0) →
      Dec win u (run P win n e0) := fun n hi hrn => by
    have hwn := hwins n hi hrn
    exact ⟨hi, hwn, hNS n hi u hwn⟩
  have keep : ∀ n, (run P win n e0).cur ≠ u ∨ (run P win n e0).st ≠ .wb →
      Ready P u (run P win n e0) → Ready P u (run P win (n + 1) e0) := fun n hc hrn => by
    refine ⟨hrn.1, ?_⟩
    rw [run_succ', ts_step_keep P win _ u (fun h' => by
      rcases hc with hc | hc
      · exact hc h'.2.symm
      · exact hc h'.1)]
    have := hrn.2
    show _ ≤ (run P win n e0).now + 1
    omega
  intro t hr hm
  cases hs : (run P win t e0).st with
  | idle => exact ⟨0, by omega, decAt t hs hr⟩
  | wb =>
    have hcu : (run P win t e0).cur ≠ u := fun h' => hm ⟨by rw [hs]; decide, h'⟩
    have hi1 : (run P win (t + 1) e0).st = .idle := by
      rw [run_succ']
      exact step_wb_idle P win _ hs
    exact ⟨1, by omega, decAt (t + 1) hi1 (keep t (Or.inl hcu) hr)⟩
  | drive =>
    have hcu : (run P win t e0).cur ≠ u := fun h' => hm ⟨by rw [hs]; decide, h'⟩
    have hd1 := step_drive P win (run P win t e0) hs
    have hs1 : (run P win (t + 1) e0).st = .wb := by
      rw [run_succ']
      exact hd1.1
    have hc1 : (run P win (t + 1) e0).cur ≠ u := by
      rw [run_succ', hd1.2]
      exact hcu
    have hr1 := keep t (Or.inr (by rw [hs]; decide)) hr
    have hi2 : (run P win (t + 2) e0).st = .idle := by
      show (run P win ((t + 1) + 1) e0).st = .idle
      rw [run_succ']
      exact step_wb_idle P win _ hs1
    exact ⟨2, by omega, decAt (t + 2) hi2 (keep (t + 1) (Or.inl hc1) hr1)⟩

include hW hfull hfn hn0 h0 h0ts hwin hws hdu hd hedf hmargin in
/-- **At most `USB_BR1_PER_WINDOW` USB branch-1 refills in any `23 + BR1_BUDGET`-cycle window**
(Wilson 11-13 condition 2), proved. -/
theorem usb_br1_window (a m : Nat) (hm : m ≤ 23 + BR1_BUDGET) :
    cnt P win (UBr1 P u) m (run P win a e0) ≤ USB_BR1_PER_WINDOW := by
  have hall := usb_nostall P win e0 u ds hW hfull hfn hn0 h0 h0ts hwin hws hdu hd hedf hmargin
  have hG : ∀ n, Good P win e0 u n := fun n t _ => hall t
  have hHV : ∀ s, HVat P win e0 s := by
    intro s
    induction s using Nat.strongRecOn with
    | _ s ih => exact hv_step P win e0 u ds hW hfull hfn hn0 h0 h0ts hwin hws hdu hd hedf hmargin s (hG s) ih
  have hNSp : ∀ t, NoStall win (run P win t e0) := fun t => (hall t).1
  have hdec_of : ∀ i, UBr1 P u (run P win i (run P win a e0)) →
      ∃ D, a + i = D + 3 ∧ Dec win u (run P win D e0) := by
    intro i hU
    rw [← run_add] at hU
    obtain ⟨mm, hmm, hret⟩ := ubr1_after_ret P win e0 u hfull hwin (a + i) (fun s _ => hHV s) hU
    obtain ⟨D, hD, hdec⟩ := wb_back P win e0 h0 mm u (isWB_of_ret P u _ hret)
    exact ⟨D, by omega, hdec⟩
  have hsep : ∀ i j, i < j → j < m → UBr1 P u (run P win i (run P win a e0)) →
      UBr1 P u (run P win j (run P win a e0)) → i + 16 ≤ j := by
    intro i j hij _ hci hcj
    obtain ⟨Di, hDi, hdi⟩ := hdec_of i hci
    obtain ⟨Dj, hDj, hdj⟩ := hdec_of j hcj
    have := usb_dec_sep18 P win e0 u ds h0 h0ts hwin hws hdu hd hedf hmargin (Dj + 1)
      (fun t _ => hNSp t) Di Dj (by omega) (Nat.lt_succ_self Dj) hdi hdj
    omega
  have hc := cnt_sparse P win (UBr1 P u) (run P win a e0) m m (Nat.le_refl m) hsep
  have hB : BR1_BUDGET = 8 := rfl
  have hU : USB_BR1_PER_WINDOW = 2 := rfl
  omega

end

#print axioms usb_nostall
#print axioms usb_j2_nb
#print axioms usb_br1_window

end JLane
