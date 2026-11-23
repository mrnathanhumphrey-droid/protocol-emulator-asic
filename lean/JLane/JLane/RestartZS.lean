import JLane.ComposeB
/-!
# Brick C3i — the restart's start conditions established (`slot_on_composition`, hZS, 11-22)

`GapRunT`'s certificate from a restart (`H0 = 1`) asks two start conditions of the stretch's
first retirement `w₀` (`CertT.hZS0`, `CertT.hHS0`):
* `hZS0`: `now₀ + D* + B ≤ ts w₀ + Z w₀ + 3`;
* `hHS0`: `now₀ + HEAD_SLACK + B ≤ ts w₀ + gp w₀ + L w₀ + 3`.
Until now they were gate-checked only (lane-cert check 20, `lane_cert.restart_margins`:
`Z[c2] ≥ D* + B - 1`, `lat[c3] + gp[c2] ≥ HEAD_SLACK + B - 1`). Here they are derived on the flush
run from those margins:

* `start_rel_runBK` -- on the stretch from `f + 3` after `y`'s last flush `f` (edge word present),
  `y`'s release (`EngBK.rel`) is never below `now₀ - 2`: the flush released `y` at `now_f + 1`
  (K4: `ts` = the edge cycle `now_f`, the rebase bit set; `restart_rel_runBK`) and the stretch
  starts at `now_f + 3` (`restart_runBK`), and releases never fall on an unflushed run
  (`rel_mono_winBK`);
* `hZS0_runBK` / `hHS0_runBK` -- the two start conditions, from check 20's margins at the first
  retirement: `D* + B ≤ Z w₀ + 1` and `HEAD_SLACK + B ≤ gp w₀ + L w₀ + 1`, each one more when the
  first retirement's `ts` is a rebase (`CertT` is `ts`-anchored, `lane_cert` release-anchored:
  there the certificate's `Z`, `L` are `lane_cert`'s plus one).
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- **The release at the restart**: on `y`'s stretch from `f + 3`, its release (`EngBK.rel`)
is at least the stretch's start less 2 (released at `now_f + 1`, the stretch starting at
`now_f + 3`). -/
theorem start_rel_runBK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (f t : Nat) (y : Lane) (hft : f + 3 ≤ t)
    (hF : ∀ j, j < t → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hfl : fl (runBK P win usb sreq fl k f X0).x.e.now y = true)
    (hedge : (runBK P win usb sreq fl k f X0).base.hasEdge y
      (k (runBK P win usb sreq fl k f X0).x.e.now y) = true)
    (hlast : ∀ j, f < j → j < t → fl (runBK P win usb sreq fl k j X0).x.e.now y = false) :
    ∀ w, w ≤ t - (f + 3) →
      (runBK P win usb sreq fl k (f + 3) X0).base.e.now
        ≤ (runBK P win usb sreq fl k (f + 3 + w) X0).rel y + 2 := by
  intro w hw
  obtain ⟨-, -, -, -, hnow⟩ := restart_runBK P win usb sreq hok fl k X0 hI f y
    (fun j hj => hF j (by omega)) hfl hedge (hlast (f + 1) (by omega) (by omega))
    (hlast (f + 2) (by omega) (by omega))
  have hr := restart_rel_runBK P win usb sreq fl k X0 f y (hF f (by omega)) hfl
    (hlast (f + 1) (by omega) (by omega)) (hlast (f + 2) (by omega) (by omega))
  have hm := rel_mono_winBK P win usb sreq fl k y X0 (f + 3) w
    (fun j hj => hlast (f + 3 + j) (by omega) (by omega))
  rw [hnow]
  omega

/-- **`hZS0` on the flush run**, from check 20's margin `D* + B ≤ Z w₀ + 1` at the stretch's
first retirement. -/
theorem hZS0_runBK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (f t : Nat) (y : Lane) (hft : f + 3 ≤ t)
    (hF : ∀ j, j < t → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hfl : fl (runBK P win usb sreq fl k f X0).x.e.now y = true)
    (hedge : (runBK P win usb sreq fl k f X0).base.hasEdge y
      (k (runBK P win usb sreq fl k f X0).x.e.now y) = true)
    (hlast : ∀ j, f < j → j < t → fl (runBK P win usb sreq fl k j X0).x.e.now y = false)
    (B : Nat) (Z : Nat → Nat)
    (hzm : ∀ w0, w0 < t - (f + 3) →
      IsRet P y ((fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) w0).e →
      cntT (fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base)
        (fun z => IsRet P y z.e) w0 = 0 →
      DSTAR + B + (if (runBK P win usb sreq fl k (f + 3 + w0) X0).reb y = true then 1 else 0) ≤ Z w0 + 1) :
    ∀ w0, w0 < t - (f + 3) →
      IsRet P y ((fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) w0).e →
      cntT (fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base)
        (fun z => IsRet P y z.e) w0 = 0 →
      ((fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) 0).held y = 1 →
      ((fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) 0).e.now + DSTAR + B
        ≤ ((fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) w0).e.ts y + Z w0 + 3 := by
  intro w0 hw0 hret hc _
  have hr := start_rel_runBK P win usb sreq hok fl k X0 hI f t y hft hF hfl hedge hlast w0
    (by omega)
  have hz := hzm w0 hw0 hret hc
  show (runBK P win usb sreq fl k (f + 3 + 0) X0).base.e.now + DSTAR + B
    ≤ (runBK P win usb sreq fl k (f + 3 + w0) X0).base.e.ts y + Z w0 + 3
  rw [Nat.add_zero]
  unfold EngBK.rel at hr
  simp only [base_e] at hr ⊢
  omega

/-- **`hHS0` on the flush run**, from check 20's margin `HEAD_SLACK + B ≤ gp w₀ + L w₀ + 1` at
the stretch's first retirement. -/
theorem hHS0_runBK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (f t : Nat) (y : Lane) (hft : f + 3 ≤ t)
    (hF : ∀ j, j < t → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hfl : fl (runBK P win usb sreq fl k f X0).x.e.now y = true)
    (hedge : (runBK P win usb sreq fl k f X0).base.hasEdge y
      (k (runBK P win usb sreq fl k f X0).x.e.now y) = true)
    (hlast : ∀ j, f < j → j < t → fl (runBK P win usb sreq fl k j X0).x.e.now y = false)
    (B : Nat) (L : Nat → Nat)
    (hhm : ∀ w0, w0 < t - (f + 3) →
      IsRet P y ((fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) w0).e →
      cntT (fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base)
        (fun z => IsRet P y z.e) w0 = 0 →
      HEAD_SLACK + B + (if (runBK P win usb sreq fl k (f + 3 + w0) X0).reb y = true then 1 else 0)
        ≤ gpT P y (fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) w0 + L w0 + 1) :
    ∀ w0, w0 < t - (f + 3) →
      IsRet P y ((fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) w0).e →
      cntT (fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base)
        (fun z => IsRet P y z.e) w0 = 0 →
      ((fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) 0).held y = 1 →
      ((fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) 0).e.now + HEAD_SLACK + B
        ≤ ((fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) w0).e.ts y
          + gpT P y (fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) w0 + L w0 + 3 := by
  intro w0 hw0 hret hc _
  have hr := start_rel_runBK P win usb sreq hok fl k X0 hI f t y hft hF hfl hedge hlast w0
    (by omega)
  have hh := hhm w0 hw0 hret hc
  show (runBK P win usb sreq fl k (f + 3 + 0) X0).base.e.now + HEAD_SLACK + B
    ≤ (runBK P win usb sreq fl k (f + 3 + w0) X0).base.e.ts y
      + gpT P y (fun n => (runBK P win usb sreq fl k (f + 3 + n) X0).base) w0 + L w0 + 3
  rw [Nat.add_zero]
  unfold EngBK.rel at hr
  simp only [base_e] at hr ⊢
  omega

end

end JLane
