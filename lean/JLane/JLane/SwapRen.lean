import JLane.SecondB
/-!
# Brick K12b — the RTL's no-swap writeback is BufEng up to a renaming (11-22, Part A)

At a FALLTHROUGH ARM's writeback the RTL does not swap the slots unless the spare holds (or a first
fetch is filing into it) the untagged timeout word (`ft_k6`, agent 1 11-22): the head is left empty,
the edge word where it was. BufEng swaps at every retiring writeback. The two states hold the same
words in the same physical slots; only the select differs. So the RTL's state is BufEng's with the
select flipped on the lanes in that state (`ns`): `ren ns`.

RTL rules (pe_engine.v as built for piece 3, agent 1 11-22), as `stepBR`:
* the writeback: no flip of the select when `nsw` (the no-swap decision, abstract like `isArm`);
* the load: a buffered word loads into an EMPTY HEAD first, else the spare (`loadToR`); the buffer
  clears exactly when it loads (`bufR`);
* filing a second fetch head-first, the round robin into the head when it is invalid, the
  requester only behind a valid head: BufEng's own functions, read on the RTL state.

`sim_step`: `stepBR (ren ns M) = ren ns' (stepB M)` with `ns' = ns || nw`, under the premises
(P1) branch 1 never targets an `ns` lane (`winq`, the (b') pick: it is not released before its
deadline); (P2) the requester never picks an `ns` lane; (P3) an `ns` lane's head word allows a
prefetch past it (the edge word is not a no-prefetch word); (P4) the dispatcher, the pick, the
requester and `fnpf` do not read the select; plus: `ns` lanes are not dispatched (armed); a no-swap
writeback `nw` is a retiring writeback of a lane not yet in `ns`; BufEng's well-formedness (`WfB`);
and every `ns` lane's BufEng head valid (`hhead`: the edge word captured).

`hhead` leaves one real case out: the edge word still IN FLIGHT at the ARM's writeback (both slots
empty; it then lands in the RTL's spare = BufEng's head, the same physical slot). Owed.

Must-fire `M_LEAN_SWAP_ALWAYS` (gate_lean_build): the RTL step flips the select at every retiring
writeback (the no-swap ignored) -- `sim_step`'s select no longer matches, the tree does not build.

Scope: the buffered engine `stepB`, `ns` held fixed apart from the new no-swap lanes. The armed /
flush run (where the edge's keep ends the renaming: K3 sets the select to the kept word's slot in
both) is the follow-on step.
-/
namespace JLane

/-- The RTL's select: flipped on the lanes in the no-swap state. -/
def renE (ns : Lane → Bool) (e : Engine) : Engine :=
  { e with sel := fun l => if ns l = true then !e.sel l else e.sel l }

def ren (ns : Lane → Bool) (x : EngB) : EngB := { x with e := renE ns x.e }

@[simp] theorem renE_actv (ns : Lane → Bool) (e : Engine) : (renE ns e).actv = e.actv := rfl
@[simp] theorem renE_npf (ns : Lane → Bool) (e : Engine) : (renE ns e).npf = e.npf := rfl
@[simp] theorem renE_st (ns : Lane → Bool) (e : Engine) : (renE ns e).st = e.st := rfl
@[simp] theorem renE_cur (ns : Lane → Bool) (e : Engine) : (renE ns e).cur = e.cur := rfl
@[simp] theorem renE_now (ns : Lane → Bool) (e : Engine) : (renE ns e).now = e.now := rfl
@[simp] theorem renE_ts (ns : Lane → Bool) (e : Engine) : (renE ns e).ts = e.ts := rfl
@[simp] theorem renE_pst (ns : Lane → Bool) (e : Engine) : (renE ns e).pst = e.pst := rfl
@[simp] theorem renE_pl (ns : Lane → Bool) (e : Engine) : (renE ns e).pl = e.pl := rfl
@[simp] theorem renE_prr (ns : Lane → Bool) (e : Engine) : (renE ns e).prr = e.prr := rfl
@[simp] theorem renE_pbr1 (ns : Lane → Bool) (e : Engine) : (renE ns e).pbr1 = e.pbr1 := rfl
@[simp] theorem renE_pslot (ns : Lane → Bool) (e : Engine) : (renE ns e).pslot = e.pslot := rfl
@[simp] theorem renE_winq (ns : Lane → Bool) (e : Engine) : (renE ns e).winq = e.winq := rfl
theorem renE_sel (ns : Lane → Bool) (e : Engine) (l : Lane) :
    (renE ns e).sel l = if ns l = true then !e.sel l else e.sel l := rfl

/-- Off the renamed lanes nothing changes. -/
theorem renE_sel_off (ns : Lane → Bool) (e : Engine) (l : Lane) (h : ns l = false) :
    (renE ns e).sel l = e.sel l := by rw [renE_sel, h]; rfl

theorem renE_sel_on (ns : Lane → Bool) (e : Engine) (l : Lane) (h : ns l = true) :
    (renE ns e).sel l = !e.sel l := by rw [renE_sel, if_pos h]

/-- On a renamed lane the RTL's head is BufEng's spare, and its spare BufEng's head. -/
theorem ren_head_on (ns : Lane → Bool) (e : Engine) (l : Lane) (h : ns l = true) :
    (renE ns e).headValid l = e.spareValid l := by
  unfold Engine.headValid Engine.spareValid; rw [renE_sel_on ns e l h]; rfl

theorem ren_spare_on (ns : Lane → Bool) (e : Engine) (l : Lane) (h : ns l = true) :
    (renE ns e).spareValid l = e.headValid l := by
  unfold Engine.headValid Engine.spareValid; rw [renE_sel_on ns e l h]; simp

theorem ren_head_off (ns : Lane → Bool) (e : Engine) (l : Lane) (h : ns l = false) :
    (renE ns e).headValid l = e.headValid l := by
  unfold Engine.headValid; rw [renE_sel_off ns e l h]; rfl

theorem ren_spare_off (ns : Lane → Bool) (e : Engine) (l : Lane) (h : ns l = false) :
    (renE ns e).spareValid l = e.spareValid l := by
  unfold Engine.spareValid; rw [renE_sel_off ns e l h]; rfl

/-- **The refill slot is the same physical slot.** On a renamed lane whose BufEng head is valid
(the edge word), the RTL's round robin targets its empty head -- BufEng's empty spare. -/
theorem ren_fetchSlot_on (ns : Lane → Bool) (e : Engine) (l : Lane) (h : ns l = true)
    (hv : e.headValid l = true) (hs : e.spareValid l = false) :
    (renE ns e).fetchSlot l = e.fetchSlot l := by
  unfold Engine.fetchSlot
  rw [ren_head_on ns e l h, hs, hv, renE_sel_on ns e l h]
  rfl

theorem ren_fetchSlot_off (ns : Lane → Bool) (e : Engine) (l : Lane) (h : ns l = false) :
    (renE ns e).fetchSlot l = e.fetchSlot l := by
  unfold Engine.fetchSlot
  rw [ren_head_off ns e l h, renE_sel_off ns e l h]

/-- **The refill want agrees** on a renamed lane whose BufEng head is valid, its head word
allowing a prefetch past it (P3). -/
theorem ren_want_on (ns : Lane → Bool) (e : Engine) (l : Lane) (h : ns l = true)
    (hv : e.headValid l = true) (hnpf : e.npf l (e.sel l) = false) :
    (renE ns e).wantFetch l = e.wantFetch l := by
  unfold Engine.wantFetch
  rw [ren_head_on ns e l h, ren_spare_on ns e l h, hv, hnpf]
  cases e.spareValid l <;> rfl

theorem ren_want_off (ns : Lane → Bool) (e : Engine) (l : Lane) (h : ns l = false) :
    (renE ns e).wantFetch l = e.wantFetch l := by
  unfold Engine.wantFetch
  rw [ren_head_off ns e l h, ren_spare_off ns e l h, renE_sel_off ns e l h]
  rfl

/-- **A second fetch files into the same physical place** on a renamed lane whose BufEng head is
valid (SecB: a second fetch lands behind a valid head). -/
theorem ren_capSlot_on (ns : Lane → Bool) (e : Engine) (l : Lane) (h : ns l = true)
    (hv : e.headValid l = true) : capSlot (renE ns e) l = capSlot e l := by
  unfold capSlot
  rw [ren_head_on ns e l h, ren_spare_on ns e l h, hv, renE_sel_on ns e l h]
  cases hs : e.spareValid l <;> simp

theorem ren_capSlot_off (ns : Lane → Bool) (e : Engine) (l : Lane) (h : ns l = false) :
    capSlot (renE ns e) l = capSlot e l := by
  unfold capSlot
  rw [ren_head_off ns e l h, ren_spare_off ns e l h, renE_sel_off ns e l h]

section
variable (P : Program) (usb : Option Lane) (sreq : EngB → Option Lane)

theorem ren_e (ns : Lane → Bool) (x : EngB) : (ren ns x).e = renE ns x.e := rfl

/-- A branch-1 target is the registered target. -/
theorem br1_target (e : Engine) {w : Lane} (h : br1 P e = some w) : e.winq = some w := by
  unfold br1 at h
  cases hq : e.winq with
  | none => rw [hq] at h; cases h
  | some v =>
    rw [hq] at h
    simp only [] at h
    by_cases hc : (P.live v && !e.headValid v) = true
    · rw [if_pos hc] at h; cases h; rfl
    · rw [if_neg hc] at h; cases h

/-- Branch 1 is unchanged when its target is never a renamed lane (P1). -/
theorem ren_br1 (ns : Lane → Bool) (e : Engine)
    (hwinq : ∀ l, ns l = true → e.winq ≠ some l) : br1 P (renE ns e) = br1 P e := by
  unfold br1
  rw [renE_winq]
  cases hw : e.winq with
  | none => rfl
  | some w =>
    have hn : ns w = false := by
      cases h : ns w
      · rfl
      · exact absurd hw (hwinq w h)
    simp only [ren_head_off ns e w hn]

theorem ren_usbFirst (ns : Lane → Bool) (e : Engine)
    (hwinq : ∀ l, ns l = true → e.winq ≠ some l) : usbFirst P usb (renE ns e) = usbFirst P usb e := by
  unfold usbFirst; rw [ren_br1 P ns e hwinq]

theorem ren_portNext_ne (ns : Lane → Bool) (e : Engine) (h : e.pst ≠ .scan) :
    portNext P (renE ns e) = portNext P e := by
  unfold portNext
  simp only [renE_pst, renE_pl, renE_prr, renE_pbr1, renE_pslot]
  cases hp : e.pst with
  | scan => exact absurd hp h
  | req => rfl
  | wait => rfl
  | cap => rfl

/-- The round robin's want and slot on any lane agree (P3 and the renamed lane's head valid). -/
theorem ren_wantM_slot (ns : Lane → Bool) (x : EngB) (l : Lane)
    (hhead : ns l = true → x.e.headValid l = true) (hnpf : ns l = true → x.e.npf l (x.e.sel l) = false) :
    (ren ns x).wantM l = x.wantM l ∧
      (x.wantM l = true → (ren ns x).e.fetchSlot l = x.e.fetchSlot l) := by
  unfold EngB.wantM
  rw [ren_e]
  cases hns : ns l with
  | false =>
    exact ⟨by rw [ren_want_off ns x.e l hns]; rfl, fun _ => ren_fetchSlot_off ns x.e l hns⟩
  | true =>
    have hv := hhead hns
    refine ⟨by rw [ren_want_on ns x.e l hns hv (hnpf hns)]; rfl, fun hw => ?_⟩
    have hs : x.e.spareValid l = false := by
      unfold Engine.wantFetch at hw
      rw [hv] at hw
      cases hsv : x.e.spareValid l <;> simp_all
    exact ren_fetchSlot_on ns x.e l hns hv hs

/-- The masked port agrees on a scan. -/
theorem ren_portNextM (ns : Lane → Bool) (x : EngB) (hp : x.e.pst = .scan)
    (hhead : ∀ l, ns l = true → x.e.headValid l = true)
    (hnpf : ∀ l, ns l = true → x.e.npf l (x.e.sel l) = false)
    (hwinq : ∀ l, ns l = true → x.e.winq ≠ some l) :
    portNextM P (ren ns x) = portNextM P x := by
  have hp' : (ren ns x).e.pst = .scan := by rw [ren_e, renE_pst]; exact hp
  have hb' : br1 P (ren ns x).e = br1 P x.e := by rw [ren_e]; exact ren_br1 P ns x.e hwinq
  cases hb : br1 P x.e with
  | some w =>
    have hn : ns w = false := by
      cases h : ns w
      · rfl
      · exact absurd (br1_target P x.e hb) (hwinq w h)
    rw [portNextM_br1 P x hp hb, portNextM_br1 P (ren ns x) hp' (hb'.trans hb), ren_e,
      renE_prr, renE_sel_off ns x.e w hn]
  | none =>
    obtain ⟨hw, hf⟩ := ren_wantM_slot ns x x.e.prr (hhead _) (hnpf _)
    have hpr : (ren ns x).e.prr = x.e.prr := by rw [ren_e, renE_prr]
    by_cases hc : (P.live x.e.prr && x.wantM x.e.prr) = true
    · have hc' : (P.live (ren ns x).e.prr && (ren ns x).wantM (ren ns x).e.prr) = true := by
        rw [hpr, hw]; exact hc
      have hwm : x.wantM x.e.prr = true := by
        cases h : x.wantM x.e.prr
        · rw [h] at hc; simp at hc
        · rfl
      rw [portNextM_br2 P x hp hb hc, portNextM_br2 P (ren ns x) hp' (hb'.trans hb) hc', hpr,
        hf hwm]
    · have hc' : ¬(P.live (ren ns x).e.prr && (ren ns x).wantM (ren ns x).e.prr) = true := by
        rw [hpr, hw]; exact hc
      rw [portNextM_skip P x hp hb hc, portNextM_skip P (ren ns x) hp' (hb'.trans hb) hc', ren_e,
        renE_pl, renE_prr, renE_pbr1, renE_pslot]

/-- **The port's next state is the same on the RTL state** (P1, P2, P3, P4). -/
theorem ren_portNextB (ns : Lane → Bool) (x : EngB)
    (hhead : ∀ l, ns l = true → x.e.headValid l = true)
    (hnpf : ∀ l, ns l = true → x.e.npf l (x.e.sel l) = false)
    (hwinq : ∀ l, ns l = true → x.e.winq ≠ some l)
    (hsr : sreq (ren ns x) = sreq x) (hsrn : ∀ l, ns l = true → sreq x ≠ some l) :
    portNextB P usb sreq (ren ns x) = portNextB P usb sreq x ∧
      pbNext P usb sreq (ren ns x) = pbNext P usb sreq x := by
  cases hp : x.e.pst with
  | scan =>
    have hp' : (ren ns x).e.pst = .scan := by rw [ren_e, renE_pst]; exact hp
    have hu' : usbFirst P usb (ren ns x).e = usbFirst P usb x.e := by
      rw [ren_e]; exact ren_usbFirst P usb ns x.e hwinq
    cases hu : usbFirst P usb x.e with
    | true =>
      obtain ⟨a1, b1⟩ := portNextB_usb P usb sreq x hp hu
      obtain ⟨a2, b2⟩ := portNextB_usb P usb sreq (ren ns x) hp' (hu'.trans hu)
      rw [a1, a2, b1, b2, ren_portNextM P ns x hp hhead hnpf hwinq]
      exact ⟨rfl, rfl⟩
    | false =>
      cases hs : sreq x with
      | none =>
        obtain ⟨a1, b1⟩ := portNextB_none P usb sreq x hp hu hs
        obtain ⟨a2, b2⟩ := portNextB_none P usb sreq (ren ns x) hp' (hu'.trans hu) (hsr.trans hs)
        rw [a1, a2, b1, b2, ren_portNextM P ns x hp hhead hnpf hwinq]
        exact ⟨rfl, rfl⟩
      | some w =>
        have hn : ns w = false := by
          cases h : ns w
          · rfl
          · exact absurd hs (hsrn w h)
        obtain ⟨a1, b1⟩ := portNextB_slot P usb sreq x hp hu hs
        obtain ⟨a2, b2⟩ := portNextB_slot P usb sreq (ren ns x) hp' (hu'.trans hu) (hsr.trans hs)
        rw [a1, a2, b1, b2, ren_e, renE_prr, ren_fetchSlot_off ns x.e w hn,
          ren_spare_off ns x.e w hn]
        exact ⟨rfl, rfl⟩
  | req | wait | cap =>
    have hne : x.e.pst ≠ .scan := by rw [hp]; decide
    have hne' : (ren ns x).e.pst ≠ .scan := by rw [ren_e, renE_pst]; exact hne
    obtain ⟨a1, b1⟩ := portNextB_of_ne P usb sreq x hne
    obtain ⟨a2, b2⟩ := portNextB_of_ne P usb sreq (ren ns x) hne'
    rw [a1, a2, b1, b2, ren_e, ren_portNext_ne P ns x.e hne]
    exact ⟨rfl, rfl⟩

end

/-! ### The RTL's step -/

/-- The RTL's load: a buffered word loads into an EMPTY HEAD first, else the spare. -/
def loadToR (x : EngB) (l : Lane) (s : Slot) : Bool :=
  x.buf l && !x.e.actv l s &&
    (if x.e.headValid l = true then decide (s = !x.e.sel l) else decide (s = x.e.sel l))

def actvR (P : Program) (x : EngB) (l : Lane) (s : Slot) : Bool :=
  if x.e.st = .wb ∧ l = x.e.cur ∧ s = x.e.sel x.e.cur ∧ P.ret x.e.now x.e.cur = true then false
  else if (capTo x l s || loadToR x l s) = true then true
  else x.e.actv l s

def npfR (P : Program) (x : EngB) (l : Lane) (s : Slot) : Bool :=
  if capTo x l s = true then P.fnpf x.e
  else if loadToR x l s = true then x.bnpf l
  else x.e.npf l s

/-- The buffer clears exactly when its word loads. -/
def bufR (x : EngB) (l : Lane) : Bool :=
  if capBuf x l = true then true
  else if (loadToR x l true || loadToR x l false) = true then false
  else x.buf l

def sqR (x : EngB) (l : Lane) (s : Slot) : Nat :=
  if capTo x l s = true then x.psq
  else if loadToR x l s = true then x.bsq l
  else x.sq l s

/-- The writeback: no flip of the select on a no-swap writeback (`nw`, the RTL's `ft_k6`). -/
def selR (P : Program) (nw : Lane → Bool) (x : EngB) (l : Lane) : Slot :=
  if nw l = true then x.e.sel l else selNext P x.e l

/-- **One cycle of the RTL's buffered engine** (piece 3's rules). -/
def stepBR (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) (nw : Lane → Bool) (x : EngB) : EngB :=
  let p := portNextB P usb sreq x
  let e1 := step P win x.e
  let e2 : Engine :=
    { now := e1.now, actv := actvR P x, sel := selR P nw x, ts := e1.ts,
      pst := p.pst, pl := p.pl, prr := p.prr, pbr1 := p.pbr1, pslot := p.pslot,
      winq := e1.winq, st := e1.st, cur := e1.cur, npf := npfR P x }
  { e := e2, buf := bufR x, bnpf := bnpfB P x, pb := pbNext P usb sreq x,
    sq := sqR x, bsq := bsqB x, psq := psqB P usb sreq x, nr := nrB P x }

theorem Engine.ext' (a b : Engine) (h1 : a.now = b.now) (h2 : a.actv = b.actv) (h3 : a.sel = b.sel)
    (h4 : a.ts = b.ts) (h5 : a.pst = b.pst) (h6 : a.pl = b.pl) (h7 : a.prr = b.prr)
    (h8 : a.pbr1 = b.pbr1) (h9 : a.pslot = b.pslot) (h10 : a.winq = b.winq) (h11 : a.st = b.st)
    (h12 : a.cur = b.cur) (h13 : a.npf = b.npf) : a = b := by
  cases a; cases b; simp_all

theorem EngB.ext' (a b : EngB) (he : a.e = b.e) (h1 : a.buf = b.buf) (h2 : a.bnpf = b.bnpf)
    (h3 : a.pb = b.pb) (h4 : a.sq = b.sq) (h5 : a.bsq = b.bsq) (h6 : a.psq = b.psq)
    (h7 : a.nr = b.nr) : a = b := by
  cases a; cases b; simp_all

/-! ### The simulation -/

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- A capture lands in the same physical place on the RTL state. -/
theorem ren_capTo (ns : Lane → Bool) (x : EngB) (l : Lane) (s : Slot)
    (hhead : ∀ l, ns l = true → x.e.headValid l = true) :
    capTo (ren ns x) l s = capTo x l s := by
  unfold capTo
  rw [ren_e, renE_pst, renE_pl, renE_pslot]
  show (decide (x.e.pst = .cap) && decide (l = x.e.pl) &&
      (if x.pb = true then decide (capSlot (renE ns x.e) l = some s) else decide (s = x.e.pslot)))
    = _
  cases hns : ns l with
  | false => rw [ren_capSlot_off ns x.e l hns]
  | true => rw [ren_capSlot_on ns x.e l hns (hhead l hns)]

theorem ren_capBuf (ns : Lane → Bool) (x : EngB) (l : Lane)
    (hhead : ∀ l, ns l = true → x.e.headValid l = true) :
    capBuf (ren ns x) l = capBuf x l := by
  unfold capBuf
  rw [ren_e, renE_pst, renE_pl]
  show (decide (x.e.pst = .cap) && decide (l = x.e.pl) && x.pb &&
      decide (capSlot (renE ns x.e) l = none)) = _
  cases hns : ns l with
  | false => rw [ren_capSlot_off ns x.e l hns]
  | true => rw [ren_capSlot_on ns x.e l hns (hhead l hns)]

/-- The RTL's head-first load is BufEng's spare load, renamed. -/
theorem ren_loadToR (ns : Lane → Bool) (x : EngB) (hW : WfB x) (l : Lane) (s : Slot) :
    loadToR (ren ns x) l s = loadTo x l s := by
  unfold loadToR loadTo
  rw [ren_e]
  show (x.buf l && !x.e.actv l s &&
      (if (renE ns x.e).headValid l = true then decide (s = !(renE ns x.e).sel l)
        else decide (s = (renE ns x.e).sel l))) = (x.buf l && decide (s = !x.e.sel l) && !x.e.actv l s)
  cases hb : x.buf l with
  | false => simp
  | true =>
    have hv : x.e.headValid l = true := hW.bh l hb
    cases hns : ns l with
    | false =>
      rw [ren_head_off ns x.e l hns, hv, renE_sel_off ns x.e l hns]
      cases hs : decide (s = !x.e.sel l) <;> simp_all
    | true =>
      rw [ren_head_on ns x.e l hns, renE_sel_on ns x.e l hns]
      have hva : x.e.actv l (x.e.sel l) = true := hv
      cases hsv : x.e.spareValid l with
      | true =>
        have hsa : x.e.actv l (!x.e.sel l) = true := hsv
        cases hq : x.e.sel l <;> cases s <;> simp_all
      | false =>
        have hsa : x.e.actv l (!x.e.sel l) = false := hsv
        cases hq : x.e.sel l <;> cases s <;> simp_all

/-- **The simulation, one cycle.** The RTL's step on the renamed state is BufEng's step, renamed
with the no-swap lanes added. -/
theorem sim_step (ns nw : Lane → Bool) (M : EngB) (hW : WfB M)
    (hhead : ∀ l, ns l = true → M.e.headValid l = true)
    (hdisp : ∀ l, ns l = true → ¬(M.e.st ≠ .idle ∧ M.e.cur = l))
    (hnw : ∀ l, nw l = true → M.e.st = .wb ∧ l = M.e.cur ∧ P.ret M.e.now M.e.cur = true ∧ ns l = false)
    (hnpf : ∀ l, ns l = true → M.e.npf l (M.e.sel l) = false)
    (hwinq : ∀ l, ns l = true → M.e.winq ≠ some l)
    (hsr : sreq (ren ns M) = sreq M) (hsrn : ∀ l, ns l = true → sreq M ≠ some l)
    (hwin : win (renE ns M.e) = win M.e) (hwinn : ∀ l, ns l = true → win M.e ≠ some l)
    (hpick : ∀ f, P.pick = some f → f (renE ns M.e) = f M.e ∧ ∀ l, ns l = true → f M.e ≠ some l)
    (hfnpf : P.fnpf (renE ns M.e) = P.fnpf M.e) :
    stepBR P win usb sreq nw (ren ns M)
      = ren (fun l => ns l || nw l) (stepB P win usb sreq M) := by
  obtain ⟨hp1, hp2⟩ := ren_portNextB P usb sreq ns M hhead hnpf hwinq hsr hsrn
  have hcap := fun l s => ren_capTo ns M l s hhead
  have hcb := fun l => ren_capBuf ns M l hhead
  have hld := fun l s => ren_loadToR ns M hW l s
  -- the dispatcher's winner is never renamed: dispatch and the registered target agree
  have hdisp' : dispNext win (renE ns M.e) = dispNext win M.e := by
    unfold dispNext
    rw [renE_st, renE_cur, hwin]
    cases hs : M.e.st with
    | idle =>
      simp only []
      cases hw : win M.e with
      | none => rfl
      | some w =>
        have hn : ns w = false := by
          cases h : ns w
          · rfl
          · exact absurd hw (hwinn w h)
        simp only [ren_head_off ns M.e w hn]
    | drive => rfl
    | wb => rfl
  have hwq : winqNext P win (renE ns M.e) = winqNext P win M.e := by
    unfold winqNext
    cases hpk : P.pick with
    | none => simp only []; exact hwin
    | some f =>
      simp only []
      obtain ⟨hf1, hf2⟩ := hpick f hpk
      unfold pfPick
      rw [hf1, renE_ts, renE_now]
      cases hfe : f M.e with
      | none => rfl
      | some w =>
        have hn : ns w = false := by
          cases h : ns w
          · rfl
          · exact absurd hfe (hf2 w h)
        simp only [ren_head_off ns M.e w hn]
  apply EngB.ext'
  · apply Engine.ext'
    · rfl
    · -- actv
      funext l s
      show actvR P (ren ns M) l s = actvB P M l s
      unfold actvR actvB
      rw [hcap l s, hld l s, ren_e, renE_st, renE_cur, renE_now]
      by_cases hc : M.e.st = .wb ∧ l = M.e.cur
      · have hcn : ns M.e.cur = false := by
          cases h : ns M.e.cur
          · rfl
          · exact absurd ⟨by rw [hc.1]; decide, rfl⟩ (hdisp _ h)
        rw [renE_sel_off ns M.e M.e.cur hcn]
        rfl
      · simp only [show ¬(M.e.st = .wb ∧ l = M.e.cur ∧ s = (renE ns M.e).sel M.e.cur ∧
            P.ret M.e.now M.e.cur = true) from fun h => hc ⟨h.1, h.2.1⟩,
          show ¬(M.e.st = .wb ∧ l = M.e.cur ∧ s = M.e.sel M.e.cur ∧
            P.ret M.e.now M.e.cur = true) from fun h => hc ⟨h.1, h.2.1⟩, if_false]
        rfl
    · -- sel
      funext l
      show selR P nw (ren ns M) l = (renE (fun l => ns l || nw l) (stepB P win usb sreq M).e).sel l
      rw [renE_sel]
      show selR P nw (ren ns M) l =
        if (ns l || nw l) = true then !selNext P M.e l else selNext P M.e l
      unfold selR
      cases hw : nw l with
      | true =>
        obtain ⟨h1, h2, h3, h4⟩ := hnw l hw
        rw [ren_e, renE_sel_off ns M.e l h4]
        have : selNext P M.e l = !M.e.sel l := by
          unfold selNext; rw [if_pos ⟨h1, h2, h3⟩]
        rw [this]
        simp
      | false =>
        simp only [Bool.or_false]
        cases hns : ns l with
        | true =>
          have hnc : ¬(M.e.st = .wb ∧ l = M.e.cur ∧ P.ret M.e.now M.e.cur = true) := by
            rintro ⟨h1, h2, -⟩
            exact hdisp l hns ⟨by rw [h1]; decide, h2.symm⟩
          rw [ren_e, selNext_noret P (renE ns M.e) l (by rw [renE_st, renE_cur, renE_now]; exact hnc),
            renE_sel_on ns M.e l hns, selNext_noret P M.e l hnc]
          rfl
        | false =>
          rw [ren_e]
          unfold selNext
          rw [renE_st, renE_cur, renE_now, renE_sel_off ns M.e l hns]
          rfl
    · rfl
    · show (portNextB P usb sreq (ren ns M)).pst = (portNextB P usb sreq M).pst; rw [hp1]
    · show (portNextB P usb sreq (ren ns M)).pl = (portNextB P usb sreq M).pl; rw [hp1]
    · show (portNextB P usb sreq (ren ns M)).prr = (portNextB P usb sreq M).prr; rw [hp1]
    · show (portNextB P usb sreq (ren ns M)).pbr1 = (portNextB P usb sreq M).pbr1; rw [hp1]
    · show (portNextB P usb sreq (ren ns M)).pslot = (portNextB P usb sreq M).pslot; rw [hp1]
    · show winqNext P win (renE ns M.e) = winqNext P win M.e; exact hwq
    · show (dispNext win (renE ns M.e)).st = (dispNext win M.e).st; rw [hdisp']
    · show (dispNext win (renE ns M.e)).cur = (dispNext win M.e).cur; rw [hdisp']
    · -- npf
      funext l s
      show npfR P (ren ns M) l s = npfB P M l s
      unfold npfR npfB
      rw [hcap l s, hld l s, ren_e, hfnpf]
      rfl
  · -- buf
    funext l
    show bufR (ren ns M) l = bufB M l
    unfold bufR bufB
    rw [hcb l, hld l true, hld l false, show (ren ns M).buf = M.buf from rfl]
    congr 1
    unfold loadTo Engine.spareValid
    cases hq : M.e.sel l <;> cases M.buf l <;> simp
  · funext l
    show bnpfB P (ren ns M) l = bnpfB P M l
    unfold bnpfB
    rw [hcb l, ren_e, hfnpf]
    rfl
  · exact hp2
  · funext l s
    show sqR (ren ns M) l s = sqB M l s
    unfold sqR sqB
    rw [hcap l s, hld l s]
    rfl
  · funext l
    show bsqB (ren ns M) l = bsqB M l
    unfold bsqB
    rw [hcb l]
    rfl
  · show psqB P usb sreq (ren ns M) = psqB P usb sreq M
    unfold psqB
    rw [hp1]
    rfl
  · rfl

end

end JLane
