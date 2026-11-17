import JLane.Port
import JLane.OptRun
/-!
# Brick S — the guaranteed slot (Wilson 11-16: one requester, one buffer; 1b and F1)

The slot fetches an ARM-headed lane's next word **while the ARM is the head**, through the port,
at a priority the port grants at its scan: **USB receive's branch-1 refill first** (the USB lane
takes no charge from the slot: Wilson 11-16, w30's 1-cycle arming margin), then the slot, then
the other lanes' branch-1 refills, then the round robin.

The requester is abstract (`sreq : Engine → Option Lane`) with a contract (`SReqOK`): it names a
live lane whose head is valid (the ARM) and which wants a fetch, so the slot fills that lane's
spare (`fetchSlot` with a valid head). A slot issue moves the port exactly as a branch-1 issue
does (`pbr1 := true`: the round-robin pointer is not moved).

Proved here:
* `stepS_*` -- only the port's registers differ from `step`; `struct_stepS` -- the structural
  invariant holds under the slot;
* `chargeS` / `chargeS_le` -- **the per-victim charge**: a scan issue for a lane other than `y`
  (USB receive's branch 1, the slot, another lane's branch 1) costs `y` at most `L_REFILL`; an
  issue for `y` itself costs it nothing (it is `y`'s own fetch: `Hit y` at its CAP);
* `phi_stepS`, `port_waitS`, `port_wait_boundS` -- **the port wait bound under the slot**: a live
  lane owing a slot reaches `P_CAP` within 22 cycles plus `L_REFILL` per issue for another
  lane, the slot's issues included -- `Port.port_wait_bound` with the slot's term;
* `slot_waitS` -- **the slot's delay behind USB receive**: a slot request held from a cycle on
  is issued within `3 + L_REFILL · u` cycles, `u` the USB receive branch-1 issues meanwhile.

Owed (next bricks, named): `slot_once` (between two slot issues for a lane, it retires: one
fetch per ARM), the buffer at depth 2 (a third word per lane), and threading `stepS` through the
head-valid theorems that read `chargeSum` (they take `hB` on the charge; with `chargeSumS` the
slot's term enters `hB`).
-/
namespace JLane

/-- This scan serves USB receive's branch-1 refill (`usb` = the USB receive lane when live). -/
def usbFirst (P : Program) (usb : Option Lane) (e : Engine) : Bool :=
  match br1 P e, usb with
  | some w, some u => decide (w = u)
  | _, _ => false

/-- The requester's contract: a named lane is live, its head valid (the ARM), and it wants a
fetch -- so the slot fills its spare. -/
def SReqOK (P : Program) (sreq : Engine → Option Lane) : Prop :=
  ∀ e w, sreq e = some w → P.live w = true ∧ e.headValid w = true ∧ e.wantFetch w = true

/-- The port with the slot: at a scan, USB receive's branch 1, else the slot, else `portNext`. -/
def portNextS (P : Program) (usb : Option Lane) (sreq : Engine → Option Lane) (e : Engine) :
    Port :=
  match e.pst with
  | .scan =>
    if usbFirst P usb e = true then portNext P e
    else
      match sreq e with
      | some w => ⟨.req, w, e.prr, true, e.fetchSlot w⟩
      | none   => portNext P e
  | _ => portNext P e

/-- One cycle with the slot: `step` with the port's registers from `portNextS`. -/
def stepS (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : Engine → Option Lane) (e : Engine) : Engine :=
  let p := portNextS P usb sreq e
  { step P win e with pst := p.pst, pl := p.pl, prr := p.prr, pbr1 := p.pbr1, pslot := p.pslot }

/-- `n` cycles with the slot. -/
def runS (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : Engine → Option Lane) : Nat → Engine → Engine
  | 0, e => e
  | n + 1, e => runS P win usb sreq n (stepS P win usb sreq e)

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : Engine → Option Lane)

theorem portOf_stepS (e : Engine) : portOf (stepS P win usb sreq e) = portNextS P usb sreq e :=
  rfl

theorem stepS_actv (e : Engine) : (stepS P win usb sreq e).actv = (step P win e).actv := rfl
theorem stepS_sel (e : Engine) : (stepS P win usb sreq e).sel = (step P win e).sel := rfl
theorem stepS_npf (e : Engine) : (stepS P win usb sreq e).npf = (step P win e).npf := rfl
theorem stepS_st (e : Engine) : (stepS P win usb sreq e).st = (step P win e).st := rfl
theorem stepS_cur (e : Engine) : (stepS P win usb sreq e).cur = (step P win e).cur := rfl

theorem stepS_want (e : Engine) (l : Lane) :
    (stepS P win usb sreq e).wantFetch l = (step P win e).wantFetch l := rfl

theorem stepS_headValid (e : Engine) (l : Lane) :
    (stepS P win usb sreq e).headValid l = (step P win e).headValid l := rfl

/-- Away from a scan, the slot's port is the shipped port. -/
theorem portNextS_of_ne (e : Engine) (h : e.pst ≠ .scan) :
    portNextS P usb sreq e = portNext P e := by
  unfold portNextS
  cases hp : e.pst with
  | scan => exact absurd hp h
  | req => rfl
  | wait => rfl
  | cap => rfl

/-- A scan serving USB receive's branch 1 is the shipped port. -/
theorem portNextS_usb (e : Engine) (hp : e.pst = .scan) (hu : usbFirst P usb e = true) :
    portNextS P usb sreq e = portNext P e := by
  unfold portNextS
  rw [hp]
  simp [hu]

/-- A scan with no USB receive refill and no slot request is the shipped port. -/
theorem portNextS_none (e : Engine) (hp : e.pst = .scan) (hu : usbFirst P usb e = false)
    (hs : sreq e = none) : portNextS P usb sreq e = portNext P e := by
  unfold portNextS
  rw [hp]
  simp [hu, hs]

/-- A slot issue. -/
theorem portNextS_slot (e : Engine) (hp : e.pst = .scan) (hu : usbFirst P usb e = false)
    {w : Lane} (hs : sreq e = some w) :
    portNextS P usb sreq e = ⟨.req, w, e.prr, true, e.fetchSlot w⟩ := by
  unfold portNextS
  rw [hp]
  simp [hu, hs]

/-! ### The structural invariant under the slot -/

theorem inFlightEmpty_stepS (hok : SReqOK P sreq) (e : Engine) (h1 : InFlightEmpty e) :
    InFlightEmpty (stepS P win usb sreq e) := by
  unfold InFlightEmpty at h1 ⊢
  intro hne
  change (portNextS P usb sreq e).pst ≠ .scan at hne
  show actvNext P e (portNextS P usb sreq e).pl (portNextS P usb sreq e).pslot = false
  by_cases hp : e.pst = .scan
  · by_cases hu : usbFirst P usb e = true
    · rw [portNextS_usb P usb sreq e hp hu] at hne ⊢
      exact actvNext_false P e _ _ (by rw [hp]; decide) (scan_issue_empty P e hp hne)
    · have hu' : usbFirst P usb e = false := by simpa using hu
      cases hs : sreq e with
      | none =>
        rw [portNextS_none P usb sreq e hp hu' hs] at hne ⊢
        exact actvNext_false P e _ _ (by rw [hp]; decide) (scan_issue_empty P e hp hne)
      | some w =>
        rw [portNextS_slot P usb sreq e hp hu' hs]
        exact actvNext_false P e _ _ (by rw [hp]; decide)
          (fetchSlot_invalid e w (hok e w hs).2.2)
  · rw [portNextS_of_ne P usb sreq e hp] at hne ⊢
    obtain ⟨hl, hs⟩ := portNext_keeps P e hp
    rw [hl, hs]
    exact actvNext_false P e _ _ (by
      intro hc
      have : (portNext P e).pst = .scan := by simp [portNext, hc]
      exact hne this) (h1 hp)

theorem dispHeadValid_stepS (e : Engine) (h2 : DispHeadValid e) :
    DispHeadValid (stepS P win usb sreq e) :=
  dispHeadValid_step P win e h2

theorem struct_stepS (hok : SReqOK P sreq) (e : Engine) (h : Struct e) :
    Struct (stepS P win usb sreq e) :=
  ⟨inFlightEmpty_stepS P win usb sreq hok e h.1, dispHeadValid_stepS P win usb sreq e h.2⟩

/-! ### The per-victim charge -/

/-- `L_REFILL` if this cycle's scan issues a fetch for a lane other than `y`: USB receive's
branch 1, the slot, or another lane's branch 1 (`Port.charge`). -/
def chargeS (y : Lane) (e : Engine) : Nat :=
  if e.pst = .scan ∧ usbFirst P usb e = false then
    match sreq e with
    | some w => if w ≠ y then L_REFILL else 0
    | none   => charge P y e
  else charge P y e

/-- Total charge over `n` cycles with the slot. -/
def chargeSumS (y : Lane) : Nat → Engine → Nat
  | 0, _ => 0
  | n + 1, e => chargeS P usb sreq y e + chargeSumS y n (stepS P win usb sreq e)

/-- **At most one refill's worth per cycle, and nothing for `y`'s own fetch.** -/
theorem chargeS_le (y : Lane) (e : Engine) : chargeS P usb sreq y e ≤ L_REFILL := by
  unfold chargeS charge
  split
  · split
    · split <;> simp
    · split
      · split <;> simp
      · simp
  · split
    · split <;> simp
    · simp

theorem chargeS_own (y : Lane) (e : Engine) (hp : e.pst = .scan)
    (hu : usbFirst P usb e = false) (hs : sreq e = some y) : chargeS P usb sreq y e = 0 := by
  unfold chargeS
  simp [hp, hu, hs]

/-! ### The port wait bound under the slot -/

theorem phi_stepS (y : Lane) (e : Engine) (hy : P.live y = true) (hw : e.wantFetch y = true)
    (hn : ¬Hit y e) :
    phi y (portOf (stepS P win usb sreq e)) + 1 ≤ phi y (portOf e) + chargeS P usb sreq y e := by
  rw [portOf_stepS]
  by_cases hp : e.pst = .scan
  · by_cases hu : usbFirst P usb e = true
    · rw [portNextS_usb P usb sreq e hp hu]
      have hc : chargeS P usb sreq y e = charge P y e := by
        unfold chargeS; rw [if_neg (fun h => by simp [h.2] at hu)]
      rw [hc, ← portOf_step P win e]
      exact phi_step P win y e hy hw hn
    · have hu' : usbFirst P usb e = false := by simpa using hu
      cases hs : sreq e with
      | none =>
        rw [portNextS_none P usb sreq e hp hu' hs]
        have hc : chargeS P usb sreq y e = charge P y e := by
          unfold chargeS; simp [hp, hu', hs]
        rw [hc, ← portOf_step P win e]
        exact phi_step P win y e hy hw hn
      | some w =>
        rw [portNextS_slot P usb sreq e hp hu' hs]
        by_cases hwy : w = y
        · simp [phi, ptr, portOf, rem, L_REFILL, hp, hwy] <;> omega
        · have hc : chargeS P usb sreq y e = L_REFILL := by
            unfold chargeS; simp [hp, hu', hs, hwy]
          simp [phi, ptr, portOf, rem, L_REFILL, hp, hwy, hc] <;> omega
  · rw [portNextS_of_ne P usb sreq e hp]
    have hc : chargeS P usb sreq y e = charge P y e := by
      unfold chargeS; rw [if_neg (fun h => hp h.1)]
    rw [hc, ← portOf_step P win e]
    exact phi_step P win y e hy hw hn

theorem want_stepS (y : Lane) (e : Engine) (hS : Struct e) (hw : e.wantFetch y = true)
    (hn : ¬Hit y e) : (stepS P win usb sreq e).wantFetch y = true := by
  rw [stepS_want]
  exact want_step P win y e hS hw hn

theorem port_waitS (hok : SReqOK P sreq) (y : Lane) (hy : P.live y = true) :
    ∀ (n : Nat) (e : Engine), Struct e → e.wantFetch y = true →
      (∀ i, i < n → ¬Hit y (runS P win usb sreq i e)) →
      phi y (portOf (runS P win usb sreq n e)) + n
        ≤ phi y (portOf e) + chargeSumS P win usb sreq y n e
  | 0, e, _, _, _ => by simp [runS, chargeSumS]
  | n + 1, e, hS, hw, hnh => by
    have h0 : ¬Hit y e := hnh 0 (Nat.succ_pos n)
    have hstep := phi_stepS P win usb sreq y e hy hw h0
    have ih := port_waitS hok y hy n (stepS P win usb sreq e)
      (struct_stepS P win usb sreq hok e hS) (want_stepS P win usb sreq y e hS hw h0)
      (fun i hi => hnh (i + 1) (Nat.succ_lt_succ hi))
    show phi y (portOf (runS P win usb sreq n (stepS P win usb sreq e))) + (n + 1)
      ≤ phi y (portOf e) + (chargeS P usb sreq y e
          + chargeSumS P win usb sreq y n (stepS P win usb sreq e))
    omega

/-- **Port wait bound under the slot.** A live lane that owes a slot reaches `P_CAP` within
22 cycles plus `L_REFILL` per fetch issued for another lane in the window -- USB receive's
branch 1, the slot's fetches for other lanes, the other lanes' branch 1 -- and nothing for its
own slot fetch. -/
theorem port_wait_boundS (hok : SReqOK P sreq) (y : Lane) (hy : P.live y = true) (n : Nat)
    (e : Engine) (hS : Struct e) (hw : e.wantFetch y = true)
    (hnh : ∀ i, i < n → ¬Hit y (runS P win usb sreq i e)) :
    n ≤ 22 + chargeSumS P win usb sreq y n e := by
  have h := port_waitS P win usb sreq hok y hy n e hS hw hnh
  have h2 := phi_le y (portOf e)
  omega

/-! ### The slot's delay behind USB receive -/

/-- A slot issue this cycle. -/
def SlotIssue (e : Engine) : Prop :=
  e.pst = .scan ∧ usbFirst P usb e = false ∧ (sreq e).isSome

/-- `L_REFILL` if this cycle's scan serves USB receive's branch 1. -/
def usbCharge (e : Engine) : Nat :=
  if e.pst = .scan ∧ usbFirst P usb e = true then L_REFILL else 0

def usbSum : Nat → Engine → Nat
  | 0, _ => 0
  | n + 1, e => usbCharge P usb e + usbSum n (stepS P win usb sreq e)

/-- **The slot waits only behind USB receive.** With a slot request at every cycle of
`[0, n)` and no slot issue in it, `n ≤ 3 + L_REFILL · (USB receive issues)`: from any port
state the scan comes within 3 cycles, and a scan that is not USB receive's issues the slot. -/
theorem slot_waitS :
    ∀ (n : Nat) (e : Engine),
      (∀ i, i < n → (sreq (runS P win usb sreq i e)).isSome = true) →
      (∀ i, i < n → ¬SlotIssue P usb sreq (runS P win usb sreq i e)) →
      n ≤ rem e.pst + usbSum P win usb sreq n e
  | 0, e, _, _ => by simp [usbSum]
  | n + 1, e, hq, hni => by
    have hq0 : (sreq e).isSome = true := hq 0 (Nat.succ_pos n)
    have hn0 : ¬SlotIssue P usb sreq e := hni 0 (Nat.succ_pos n)
    have ih := slot_waitS n (stepS P win usb sreq e)
      (fun i hi => hq (i + 1) (Nat.succ_lt_succ hi))
      (fun i hi => hni (i + 1) (Nat.succ_lt_succ hi))
    show n + 1 ≤ rem e.pst + (usbCharge P usb e + usbSum P win usb sreq n (stepS P win usb sreq e))
    have hr := rem_le (stepS P win usb sreq e).pst
    by_cases hp : e.pst = .scan
    · by_cases hu : usbFirst P usb e = true
      · have hc : usbCharge P usb e = L_REFILL := by unfold usbCharge; simp [hp, hu]
        -- USB receive's issue: the port goes to REQ (rem 3)
        have hpst : (stepS P win usb sreq e).pst = .req := by
          change (portNextS P usb sreq e).pst = .req
          rw [portNextS_usb P usb sreq e hp hu]
          unfold usbFirst at hu
          cases hb : br1 P e with
          | none => rw [hb] at hu; simp at hu
          | some w => simp [portNext, hp, hb]
        rw [hpst] at ih
        simp [rem, hc, hp, L_REFILL] at ih ⊢
        omega
      · exact absurd ⟨hp, by simpa using hu, hq0⟩ hn0
    · have hc : usbCharge P usb e = 0 := by unfold usbCharge; rw [if_neg (fun h => hp h.1)]
      have hpst : (stepS P win usb sreq e).pst = (portNext P e).pst := by
        change (portNextS P usb sreq e).pst = _
        rw [portNextS_of_ne P usb sreq e hp]
      rw [hpst] at ih
      cases hpe : e.pst with
      | scan => exact absurd hpe hp
      | req => simp [portNext, hpe, rem, hc] at ih ⊢; omega
      | wait => simp [portNext, hpe, rem, hc] at ih ⊢; omega
      | cap => simp [portNext, hpe, rem, hc] at ih ⊢; omega

/-! ### One slot fetch per ARM -/

theorem runS_succ' : ∀ (n : Nat) (e : Engine),
    runS P win usb sreq (n + 1) e = stepS P win usb sreq (runS P win usb sreq n e)
  | 0, _ => rfl
  | n + 1, e => runS_succ' n (stepS P win usb sreq e)

theorem runS_add : ∀ (a k : Nat) (e : Engine),
    runS P win usb sreq (a + k) e = runS P win usb sreq k (runS P win usb sreq a e)
  | a, 0, _ => rfl
  | a, k + 1, e => by
    rw [← Nat.add_assoc, runS_succ', runS_add a k e, ← runS_succ']

theorem keepS (u : Lane) (s : Slot) (e : Engine) (hr : ¬IsRet P u e) (h : e.actv u s = true) :
    (stepS P win usb sreq e).actv u s = true := by
  rw [stepS_actv]
  show actvNext P e u s = true
  unfold actvNext
  have hn := not_ret_form P u e hr
  rw [if_neg (fun h' => hn ⟨h'.1, h'.2.1, h'.2.2.2⟩)]
  split
  · rfl
  · exact h

theorem selS (u : Lane) (e : Engine) (hr : ¬IsRet P u e) :
    (stepS P win usb sreq e).sel u = e.sel u := by
  rw [stepS_sel]
  show selNext P e u = e.sel u
  unfold selNext
  rw [if_neg (not_ret_form P u e hr)]

theorem capFillS (u : Lane) (e : Engine) (hc : e.pst = .cap) (hl : e.pl = u)
    (hr : ¬IsRet P u e) : (stepS P win usb sreq e).actv u e.pslot = true := by
  rw [stepS_actv]
  show actvNext P e u e.pslot = true
  unfold actvNext
  have hn := not_ret_form P u e hr
  rw [if_neg (fun h' => hn ⟨h'.1, h'.2.1, h'.2.2.2⟩), if_pos ⟨hc, hl.symm, rfl⟩]

/-- **`slot_once`: one slot fetch per ARM.** Two slot issues for the same lane `u` have a
retirement of `u` between them: the first fills `u`'s spare behind its valid head (the ARM), and
until `u` retires both slots stay valid, so `u` wants no fetch and the requester cannot name it
(`SReqOK`). -/
theorem slot_once (hok : SReqOK P sreq) (u : Lane) (e1 : Engine) (n : Nat)
    (ha : SlotIssue P usb sreq e1) (hu : sreq e1 = some u)
    (hb : sreq (runS P win usb sreq n e1) = some u)
    (hbs : (runS P win usb sreq n e1).pst = .scan) (_hn : 0 < n) :
    ¬(∀ x, x < n → ¬IsRet P u (runS P win usb sreq x e1)) := by
  intro hnr
  obtain ⟨hp, hu0, _⟩ := ha
  have hv0 : e1.headValid u = true := (hok e1 u hu).2.1
  have hfs : e1.fetchSlot u = !e1.sel u := by
    unfold Engine.fetchSlot; rw [hv0]; rfl
  -- the port after the issue: REQ, WAIT, CAP on u's spare
  have h1 : runS P win usb sreq 1 e1 = stepS P win usb sreq e1 := rfl
  have hp1 : portOf (runS P win usb sreq 1 e1) = ⟨.req, u, e1.prr, true, !e1.sel u⟩ := by
    rw [h1, portOf_stepS, portNextS_slot P usb sreq e1 hp hu0 hu, hfs]
  have hpst1 : (runS P win usb sreq 1 e1).pst = .req := congrArg Port.pst hp1
  have hpl1 : (runS P win usb sreq 1 e1).pl = u := congrArg Port.pl hp1
  have hps1 : (runS P win usb sreq 1 e1).pslot = !e1.sel u := congrArg Port.pslot hp1
  have nxt : ∀ k, (runS P win usb sreq k e1).pst ≠ .scan →
      portOf (runS P win usb sreq (k + 1) e1) = portNext P (runS P win usb sreq k e1) := by
    intro k hk
    rw [runS_succ', portOf_stepS, portNextS_of_ne P usb sreq _ hk]
  have hpst2 : (runS P win usb sreq 2 e1).pst = .wait := by
    show (portOf (runS P win usb sreq (1 + 1) e1)).pst = .wait
    rw [nxt 1 (by rw [hpst1]; decide)]; simp [portNext, hpst1]
  have hkeep2 := portNext_keeps P (runS P win usb sreq 1 e1) (by rw [hpst1]; decide)
  have hpl2 : (runS P win usb sreq 2 e1).pl = u := by
    rw [show (runS P win usb sreq 2 e1).pl = (portOf (runS P win usb sreq (1 + 1) e1)).pl from rfl,
      nxt 1 (by rw [hpst1]; decide), hkeep2.1, hpl1]
  have hps2 : (runS P win usb sreq 2 e1).pslot = !e1.sel u := by
    rw [show (runS P win usb sreq 2 e1).pslot = (portOf (runS P win usb sreq (1 + 1) e1)).pslot from
      rfl, nxt 1 (by rw [hpst1]; decide), hkeep2.2, hps1]
  have hpst3 : (runS P win usb sreq 3 e1).pst = .cap := by
    show (portOf (runS P win usb sreq (2 + 1) e1)).pst = .cap
    rw [nxt 2 (by rw [hpst2]; decide)]; simp [portNext, hpst2]
  have hkeep3 := portNext_keeps P (runS P win usb sreq 2 e1) (by rw [hpst2]; decide)
  have hpl3 : (runS P win usb sreq 3 e1).pl = u := by
    rw [show (runS P win usb sreq 3 e1).pl = (portOf (runS P win usb sreq (2 + 1) e1)).pl from rfl,
      nxt 2 (by rw [hpst2]; decide), hkeep3.1, hpl2]
  have hps3 : (runS P win usb sreq 3 e1).pslot = !e1.sel u := by
    rw [show (runS P win usb sreq 3 e1).pslot = (portOf (runS P win usb sreq (2 + 1) e1)).pslot from
      rfl, nxt 2 (by rw [hpst2]; decide), hkeep3.2, hps2]
  -- the second request is at a scan, so n >= 4
  have hn4 : 4 ≤ n := by
    rcases (by omega : n = 1 ∨ n = 2 ∨ n = 3 ∨ 4 ≤ n) with h | h | h | h
    · rw [h, hpst1] at hbs; cases hbs
    · rw [h, hpst2] at hbs; cases hbs
    · rw [h, hpst3] at hbs; cases hbs
    · exact h
  -- with no retirement: the select holds, the head stays valid, the spare fills at 3
  have inv : ∀ k, k ≤ n → (runS P win usb sreq k e1).sel u = e1.sel u ∧
      (runS P win usb sreq k e1).actv u (e1.sel u) = true ∧
      (4 ≤ k → (runS P win usb sreq k e1).actv u (!e1.sel u) = true) := by
    intro k
    induction k with
    | zero => intro _; exact ⟨rfl, hv0, fun h => absurd h (by omega)⟩
    | succ k ih =>
      intro hk
      obtain ⟨hs, hh, hsp⟩ := ih (by omega)
      have hr := hnr k (by omega)
      rw [runS_succ']
      refine ⟨by rw [selS P win usb sreq u _ hr, hs], keepS P win usb sreq u _ _ hr hh, ?_⟩
      intro h4
      by_cases hk3 : k = 3
      · subst hk3
        have := capFillS P win usb sreq u _ hpst3 hpl3 hr
        rwa [hps3] at this
      · exact keepS P win usb sreq u _ _ hr (hsp (by omega))
  obtain ⟨hs, hh, hsp⟩ := inv n (Nat.le_refl n)
  have hw := (hok _ u hb).2.2
  unfold Engine.wantFetch Engine.headValid Engine.spareValid at hw
  rw [hs, hh, hsp hn4] at hw
  simp at hw


/-! ### USB receive: one branch-1 refill per retirement under the slot -/

theorem usbFirst_spec (v : Lane) (e : Engine) (h : usbFirst P (some v) e = true) :
    br1 P e = some v := by
  unfold usbFirst at h
  cases hb : br1 P e with
  | none => rw [hb] at h; simp at h
  | some w => rw [hb] at h; simp at h; rw [h]

/-- A USB receive branch-1 issue this cycle. -/
def UsbIssue (e : Engine) : Prop := e.pst = .scan ∧ usbFirst P usb e = true

instance (e : Engine) : Decidable (UsbIssue P usb e) :=
  inferInstanceAs (Decidable (e.pst = .scan ∧ usbFirst P usb e = true))

/-- **`usb_once_S`.** Under the slot, two USB receive issues have a retirement of the USB lane
between them: the first fills its empty head, which stays valid until it retires, and branch 1
needs an empty head. -/
theorem usb_once_S (v : Lane) (hv : usb = some v) (e1 : Engine) (n : Nat)
    (ha : UsbIssue P usb e1) (hb : UsbIssue P usb (runS P win usb sreq n e1)) (_hn : 0 < n) :
    ¬(∀ x, x < n → ¬IsRet P v (runS P win usb sreq x e1)) := by
  intro hnr
  subst hv
  obtain ⟨hp, hu0⟩ := ha
  have hb1 := usbFirst_spec P v e1 hu0
  have hp1 : portOf (runS P win (some v) sreq 1 e1) = ⟨.req, v, e1.prr, true, e1.sel v⟩ := by
    show portNextS P (some v) sreq e1 = _
    rw [portNextS_usb P (some v) sreq e1 hp hu0]
    simp [portNext, hp, hb1]
  have hpst1 : (runS P win (some v) sreq 1 e1).pst = .req := congrArg Port.pst hp1
  have hpl1 : (runS P win (some v) sreq 1 e1).pl = v := congrArg Port.pl hp1
  have hps1 : (runS P win (some v) sreq 1 e1).pslot = e1.sel v := congrArg Port.pslot hp1
  have nxt : ∀ k, (runS P win (some v) sreq k e1).pst ≠ .scan →
      portOf (runS P win (some v) sreq (k + 1) e1)
        = portNext P (runS P win (some v) sreq k e1) := by
    intro k hk
    rw [runS_succ', portOf_stepS, portNextS_of_ne P (some v) sreq _ hk]
  have hpst2 : (runS P win (some v) sreq 2 e1).pst = .wait := by
    show (portOf (runS P win (some v) sreq (1 + 1) e1)).pst = .wait
    rw [nxt 1 (by rw [hpst1]; decide)]; simp [portNext, hpst1]
  have hk2 := portNext_keeps P (runS P win (some v) sreq 1 e1) (by rw [hpst1]; decide)
  have hpl2 : (runS P win (some v) sreq 2 e1).pl = v := by
    rw [show (runS P win (some v) sreq 2 e1).pl
        = (portOf (runS P win (some v) sreq (1 + 1) e1)).pl from rfl,
      nxt 1 (by rw [hpst1]; decide), hk2.1, hpl1]
  have hps2 : (runS P win (some v) sreq 2 e1).pslot = e1.sel v := by
    rw [show (runS P win (some v) sreq 2 e1).pslot
        = (portOf (runS P win (some v) sreq (1 + 1) e1)).pslot from rfl,
      nxt 1 (by rw [hpst1]; decide), hk2.2, hps1]
  have hpst3 : (runS P win (some v) sreq 3 e1).pst = .cap := by
    show (portOf (runS P win (some v) sreq (2 + 1) e1)).pst = .cap
    rw [nxt 2 (by rw [hpst2]; decide)]; simp [portNext, hpst2]
  have hk3 := portNext_keeps P (runS P win (some v) sreq 2 e1) (by rw [hpst2]; decide)
  have hpl3 : (runS P win (some v) sreq 3 e1).pl = v := by
    rw [show (runS P win (some v) sreq 3 e1).pl
        = (portOf (runS P win (some v) sreq (2 + 1) e1)).pl from rfl,
      nxt 2 (by rw [hpst2]; decide), hk3.1, hpl2]
  have hps3 : (runS P win (some v) sreq 3 e1).pslot = e1.sel v := by
    rw [show (runS P win (some v) sreq 3 e1).pslot
        = (portOf (runS P win (some v) sreq (2 + 1) e1)).pslot from rfl,
      nxt 2 (by rw [hpst2]; decide), hk3.2, hps2]
  have hbs := hb.1
  have hn4 : 4 ≤ n := by
    rcases (by omega : n = 0 ∨ n = 1 ∨ n = 2 ∨ n = 3 ∨ 4 ≤ n) with h | h | h | h | h
    · omega
    · rw [h, hpst1] at hbs; cases hbs
    · rw [h, hpst2] at hbs; cases hbs
    · rw [h, hpst3] at hbs; cases hbs
    · exact h
  have inv : ∀ k, k ≤ n → (runS P win (some v) sreq k e1).sel v = e1.sel v ∧
      (4 ≤ k → (runS P win (some v) sreq k e1).actv v (e1.sel v) = true) := by
    intro k
    induction k with
    | zero => intro _; exact ⟨rfl, fun h => absurd h (by omega)⟩
    | succ k ih =>
      intro hk
      obtain ⟨hs, hh⟩ := ih (by omega)
      have hr := hnr k (by omega)
      rw [runS_succ']
      refine ⟨by rw [selS P win (some v) sreq v _ hr, hs], ?_⟩
      intro h4
      by_cases hk3 : k = 3
      · subst hk3
        have := capFillS P win (some v) sreq v _ hpst3 hpl3 hr
        rwa [hps3] at this
      · exact keepS P win (some v) sreq v _ _ hr (hh (by omega))
  obtain ⟨hs, hh⟩ := inv n (Nat.le_refl n)
  have hbr := usbFirst_spec P v _ hb.2
  have hhv := (br1_spec P _ v hbr).2
  unfold Engine.headValid at hhv
  rw [hs, hh hn4] at hhv
  cases hhv

/-! ### Counting along a slot run: one issue per retirement, plus one -/

/-- Cycles satisfying `Q` among the first `n` of the slot run. -/
def cntS (Q : Engine → Prop) [DecidablePred Q] : Nat → Engine → Nat
  | 0, _ => 0
  | n + 1, e => (if Q e then 1 else 0) + cntS Q n (stepS P win usb sreq e)

theorem cntS_add (Q : Engine → Prop) [DecidablePred Q] :
    ∀ (a k : Nat) (e : Engine),
      cntS P win usb sreq Q (a + k) e
        = cntS P win usb sreq Q a e + cntS P win usb sreq Q k (runS P win usb sreq a e)
  | 0, k, e => by
    show cntS P win usb sreq Q (0 + k) e = 0 + cntS P win usb sreq Q k e
    rw [Nat.zero_add, Nat.zero_add]
  | a + 1, k, e => by
    rw [Nat.add_right_comm]
    show (if Q e then 1 else 0) + cntS P win usb sreq Q (a + k) (stepS P win usb sreq e)
        = ((if Q e then 1 else 0) + cntS P win usb sreq Q a (stepS P win usb sreq e))
          + cntS P win usb sreq Q k (runS P win usb sreq a (stepS P win usb sreq e))
    rw [cntS_add Q a k (stepS P win usb sreq e)]
    omega

theorem cntS_reach (Q : Engine → Prop) [DecidablePred Q] :
    ∀ (n : Nat) (e : Engine) (k : Nat), k < cntS P win usb sreq Q n e →
      ∃ t, t < n ∧ cntS P win usb sreq Q t e = k ∧ Q (runS P win usb sreq t e)
  | 0, e, k, h => by simp [cntS] at h
  | n + 1, e, k, h => by
    have e1 : cntS P win usb sreq Q (n + 1) e
        = (if Q e then 1 else 0) + cntS P win usb sreq Q n (stepS P win usb sreq e) := rfl
    by_cases hq : Q e
    · rw [if_pos hq] at e1
      cases k with
      | zero => exact ⟨0, Nat.succ_pos n, rfl, hq⟩
      | succ k =>
        obtain ⟨t, ht, hc, hq'⟩ := cntS_reach Q n (stepS P win usb sreq e) k (by omega)
        have e2 : cntS P win usb sreq Q (t + 1) e
            = (if Q e then 1 else 0) + cntS P win usb sreq Q t (stepS P win usb sreq e) := rfl
        rw [if_pos hq] at e2
        exact ⟨t + 1, by omega, by omega, hq'⟩
    · rw [if_neg hq] at e1
      obtain ⟨t, ht, hc, hq'⟩ := cntS_reach Q n (stepS P win usb sreq e) k (by omega)
      have e2 : cntS P win usb sreq Q (t + 1) e
          = (if Q e then 1 else 0) + cntS P win usb sreq Q t (stepS P win usb sreq e) := rfl
      rw [if_neg hq] at e2
      exact ⟨t + 1, by omega, by omega, hq'⟩

theorem cntS_pos_of (Q : Engine → Prop) [DecidablePred Q] (e : Engine) (s t : Nat)
    (hst : s < t) (hq : Q (runS P win usb sreq s e)) : 1 ≤ cntS P win usb sreq Q t e := by
  obtain ⟨j, rfl⟩ : ∃ j, t = s + (j + 1) := ⟨t - s - 1, by omega⟩
  rw [cntS_add P win usb sreq Q s (j + 1) e]
  have h1 : cntS P win usb sreq Q (j + 1) (runS P win usb sreq s e)
      = (if Q (runS P win usb sreq s e) then 1 else 0)
        + cntS P win usb sreq Q j (stepS P win usb sreq (runS P win usb sreq s e)) := rfl
  rw [h1, if_pos hq]
  omega

/-- **One issue per retirement, plus one** -- for any issue predicate `I` whose two occurrences
always have a retirement `R` between them (`slot_once`, `usb_once_S`). -/
theorem cntS_once (I R : Engine → Prop) [DecidablePred I] [DecidablePred R] (e0 : Engine)
    (hOnce : ∀ a n, 0 < n → I (runS P win usb sreq a e0) →
      I (runS P win usb sreq (a + n) e0) →
      ¬(∀ x, x < n → ¬R (runS P win usb sreq (a + x) e0))) :
    ∀ m a, cntS P win usb sreq I m (runS P win usb sreq a e0)
      ≤ cntS P win usb sreq R m (runS P win usb sreq a e0) + 1 := by
  suffices H : ∀ N m a, m ≤ N → cntS P win usb sreq I m (runS P win usb sreq a e0)
      ≤ cntS P win usb sreq R m (runS P win usb sreq a e0) + 1 from
    fun m a => H m m a (Nat.le_refl m)
  intro N
  induction N with
  | zero =>
    intro m a hm
    have : m = 0 := by omega
    subst this
    simp [cntS]
  | succ N ih =>
    intro m a hm
    cases m with
    | zero => simp [cntS]
    | succ k =>
      have step1 : ∀ (Q : Engine → Prop) [DecidablePred Q],
          cntS P win usb sreq Q (k + 1) (runS P win usb sreq a e0)
            = (if Q (runS P win usb sreq a e0) then 1 else 0)
              + cntS P win usb sreq Q k (runS P win usb sreq (a + 1) e0) := by
        intro Q _
        rw [runS_succ']
        rfl
      rw [step1 I, step1 R]
      by_cases hia : I (runS P win usb sreq a e0)
      · rw [if_pos hia]
        rcases Nat.eq_zero_or_pos (cntS P win usb sreq I k (runS P win usb sreq (a + 1) e0))
          with h0 | hpos
        · rw [h0]; split <;> omega
        · obtain ⟨s0, hs0k, hc0, hq0⟩ :=
            cntS_reach P win usb sreq I k (runS P win usb sreq (a + 1) e0) 0 hpos
          rw [← runS_add, show a + 1 + s0 = a + (s0 + 1) by omega] at hq0
          have hret : 1 ≤ cntS P win usb sreq R (s0 + 1) (runS P win usb sreq a e0) := by
            rcases Nat.eq_zero_or_pos (cntS P win usb sreq R (s0 + 1) (runS P win usb sreq a e0))
              with hz | hp
            · exfalso
              apply hOnce a (s0 + 1) (by omega) hia hq0
              intro x hx hr
              have := cntS_pos_of P win usb sreq R (runS P win usb sreq a e0) x (s0 + 1) hx
                (by rw [← runS_add]; exact hr)
              omega
            · exact hp
          have hsplitI := cntS_add P win usb sreq I s0 (k - s0) (runS P win usb sreq (a + 1) e0)
          rw [show s0 + (k - s0) = k by omega, hc0, ← runS_add] at hsplitI
          have hsplitR := cntS_add P win usb sreq R (s0 + 1) (k - s0) (runS P win usb sreq a e0)
          rw [show s0 + 1 + (k - s0) = k + 1 by omega, ← runS_add,
            show a + (s0 + 1) = a + 1 + s0 by omega] at hsplitR
          have hih := ih (k - s0) (a + 1 + s0) (by omega)
          have eR1 := step1 R
          omega
      · rw [if_neg hia]
        have hih := ih k (a + 1) (by omega)
        split <;> omega

/-- A slot issue for lane `u`. -/
def SlotFor (u : Lane) (e : Engine) : Prop :=
  e.pst = .scan ∧ usbFirst P usb e = false ∧ sreq e = some u

instance (u : Lane) (e : Engine) : Decidable (SlotFor P usb sreq u e) :=
  inferInstanceAs (Decidable (e.pst = .scan ∧ usbFirst P usb e = false ∧ sreq e = some u))

/-- **The per-window count, the slot.** Over any `m` cycles, lane `u`'s slot fetches are at
most its retirements plus one: one fetch per ARM. -/
theorem slot_count (hok : SReqOK P sreq) (u : Lane) (e0 : Engine) (m a : Nat) :
    cntS P win usb sreq (SlotFor P usb sreq u) m (runS P win usb sreq a e0)
      ≤ cntS P win usb sreq (IsRet P u) m (runS P win usb sreq a e0) + 1 :=
  cntS_once P win usb sreq _ _ e0 (fun a n hn ha hb => by
    rw [runS_add] at hb
    have h := slot_once P win usb sreq hok u (runS P win usb sreq a e0) n
      ⟨ha.1, ha.2.1, by rw [ha.2.2]; rfl⟩ ha.2.2 hb.2.2 hb.1 hn
    intro hall
    exact h (fun x hx hr => hall x hx (by rw [runS_add]; exact hr))) m a

/-- **The per-window count, USB receive.** Over any `m` cycles, USB receive's branch-1 issues
under the slot are at most the USB lane's retirements plus one -- the count the certificate
evaluates per window (`lane_cert.br1_window_count`: one per late word). -/
theorem usb_count (v : Lane) (hv : usb = some v) (e0 : Engine) (m a : Nat) :
    cntS P win usb sreq (UsbIssue P usb) m (runS P win usb sreq a e0)
      ≤ cntS P win usb sreq (IsRet P v) m (runS P win usb sreq a e0) + 1 :=
  cntS_once P win usb sreq _ _ e0 (fun a n hn ha hb => by
    rw [runS_add] at hb
    have h := usb_once_S P win usb sreq v hv (runS P win usb sreq a e0) n ha hb hn
    intro hall
    exact h (fun x hx hr => hall x hx (by rw [runS_add]; exact hr))) m a

/-! ### The bound's constants (pinned: `proof_constants.slot_wait_base` / `slot_charge`) -/

/-- The slot's wait from any port state to its scan: the in-flight refill's remaining cycles. -/
abbrev SLOT_WAIT_BASE : Nat := L_REFILL - 1
/-- What one fetch for another lane costs a lane: one refill. -/
abbrev SLOT_CHARGE : Nat := L_REFILL

theorem slot_wait_base_val : SLOT_WAIT_BASE = 3 := rfl
theorem slot_charge_val : SLOT_CHARGE = 4 := rfl

/-- **The slot's wait, with its constants.** `n ≤ SLOT_WAIT_BASE + SLOT_CHARGE · (USB receive
issues)` (`slot_waitS`; `usbSum_eq_cnt`). -/
theorem slot_wait_bound (n : Nat) (e : Engine)
    (hq : ∀ i, i < n → (sreq (runS P win usb sreq i e)).isSome = true)
    (hni : ∀ i, i < n → ¬SlotIssue P usb sreq (runS P win usb sreq i e)) :
    n ≤ SLOT_WAIT_BASE + usbSum P win usb sreq n e := by
  have h := slot_waitS P win usb sreq n e hq hni
  have h2 := rem_le e.pst
  show n ≤ L_REFILL - 1 + _
  simp only [L_REFILL]
  omega

theorem usbSum_eq_cnt : ∀ (n : Nat) (e : Engine),
    usbSum P win usb sreq n e = SLOT_CHARGE * cntS P win usb sreq (UsbIssue P usb) n e
  | 0, _ => by simp [usbSum, cntS]
  | n + 1, e => by
    show usbCharge P usb e + usbSum P win usb sreq n (stepS P win usb sreq e)
      = SLOT_CHARGE * ((if UsbIssue P usb e then 1 else 0)
          + cntS P win usb sreq (UsbIssue P usb) n (stepS P win usb sreq e))
    rw [usbSum_eq_cnt n]
    unfold usbCharge UsbIssue
    split <;> simp [Nat.mul_add, SLOT_CHARGE]

end

end JLane
