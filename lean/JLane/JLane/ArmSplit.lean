import JLane.ArmFTClose
/-!
# Brick W — an ARM word's lateness does not move its successor (Wilson 11-14, the word-class split)

A2 quotes one dispatch jitter per lane; on the USB lane that is 26, set by an ARM word (the SE0
wait after a FALLTHROUGH edge) whose own check -- armed before the reply can end -- is separate.
Splitting J by word class needs this as a theorem: **an ARM word's lateness is fully covered by
its arming check and does not feed the timing of any later word.**

The model's edge input `edge t l` is "the edge an ARM written back at `t` waits for" -- a free
input indexed by the writeback time. Here the bus is made explicit: `bus s l` = a qualifying edge
at cycle `s`, and the edge an ARM sees is the FIRST bus edge after its writeback (`IsFirst`).

* `first_stable` — every writeback time in `[t₀, E)`, `E` the first bus edge after `t₀`, sees the
  same first edge `E`;
* `arm_release_bus` / `arm_release_T_bus` — so the word after an ARM (plain, HALF via `halfEdge`,
  or FALLTHROUGH) is released at a time set by the bus edge alone (`E + 1`; FALLTHROUGH:
  `min (E + 1) D`, `D` the deadline from the ARM's own release), **whatever the ARM's writeback
  time before `E`** -- i.e. whatever its lateness, as long as its arming check holds (writeback
  before the edge: `hedge`, the certificate's gated premise).

The certificate then computes each later word's lateness from that release, so the USB lane's
receive words carry their own J (`j_rx`), and an ARM word's lateness appears only in its arming
check's margin.
-/
namespace JLane

/-- `e` is the first bus edge on lane `l` strictly after cycle `t`. -/
def IsFirst (bus : Nat → Lane → Bool) (t : Nat) (l : Lane) (e : Nat) : Prop :=
  t < e ∧ bus e l = true ∧ ∀ s, t < s → s < e → bus s l = false

/-- **The first edge is stable** over every writeback time before it. -/
theorem first_stable (bus : Nat → Lane → Bool) (l : Lane) (t₀ t E e : Nat)
    (hE : IsFirst bus t₀ l E) (ht0 : t₀ ≤ t) (htE : t < E) (he : IsFirst bus t l e) : e = E := by
  obtain ⟨hlt, hbE, hnoE⟩ := hE
  obtain ⟨hlt', hbe, hnoe⟩ := he
  rcases Nat.lt_trichotomy e E with h | h | h
  · -- an edge at e in (t₀, E): impossible
    have := hnoE e (by omega) h
    rw [hbe] at this
    cases this
  · exact h
  · -- an edge at E in (t, e): impossible
    have := hnoe E htE h
    rw [hbE] at this
    cases this

/-- **The word after a plain (or HALF) ARM is released by the bus edge alone.** If the ARM's
edge input is the first bus edge after its writeback, and that writeback is anywhere in
`[t₀, E)` (`E` the first bus edge after `t₀`), the successor's release is `E + 1`. -/
theorem arm_release_bus (P : Program2) (Wn : Nat) (fw : Engine2 → Word)
    (edge : Nat → Lane → Nat) (bus : Nat → Lane → Bool)
    (hfirst : ∀ t l, IsFirst bus t l (edge t l))
    (w : Option Lane) (X : Engine3) (h : ArmInv Wn X) (harm : X.armWB P = true)
    (t₀ E : Nat) (hE : IsFirst bus t₀ X.x.e.cur E) (ht0 : t₀ ≤ X.x.e.now) (htE : X.x.e.now < E) :
    (πE (step3 P fw edge w X)).ts X.x.e.cur = E + 1 := by
  rw [arm_release P Wn fw edge w X h harm,
    first_stable bus X.x.e.cur t₀ X.x.e.now E _ hE ht0 htE (hfirst X.x.e.now X.x.e.cur)]

/-- **FALLTHROUGH: the successor's release is set by the bus edge and the deadline alone.** The
deadline `D = ts + a_dly` is fixed by the ARM's own release, not its writeback time; the edge is
the first bus edge, the same for every writeback time before it. -/
theorem arm_release_T_bus (P : Program2) (Wn : Nat) (fw : Engine2 → Word)
    (edge : Nat → Lane → Nat) (bus : Nat → Lane → Bool)
    (hfirst : ∀ t l, IsFirst bus t l (edge t l))
    (w : Option Lane) (X : EngineT) (h : InvT Wn X) (harm : X.armWB P = true)
    (t₀ E : Nat) (hE : IsFirst bus t₀ X.x.e.cur E) (ht0 : t₀ ≤ X.x.e.now) (htE : X.x.e.now < E) :
    relT (step3T P fw edge w X) X.x.e.cur =
      (if 0 < (X.x.head X.x.e.cur).dly ∧
          X.x.e.ts X.x.e.cur + (X.x.head X.x.e.cur).dly ≤ E
       then X.x.e.ts X.x.e.cur + (X.x.head X.x.e.cur).dly
       else E + 1) := by
  rw [arm_release_T P Wn fw edge w X h harm,
    first_stable bus X.x.e.cur t₀ X.x.e.now E _ hE ht0 htE (hfirst X.x.e.now X.x.e.cur)]

#print axioms first_stable
#print axioms arm_release_bus
#print axioms arm_release_T_bus

end JLane
