import JLane
/-!
# TR-1 replay
`lake exe replay <dir or files>` runs the model's `step` on every recorded cycle and
compares the result with the next recorded cycle. It also checks the theorem's
hypotheses on the trace. Executable conformance check: it adds no axioms to any theorem.
-/
open JLane

structure Row where
  cycle : Nat
  now : Nat
  st : Nat
  cur : Nat
  pst : Nat
  pl : Nat
  prr : Nat
  pbr1 : Nat
  pslot : Nat
  winqv : Nat
  winq : Nat
  winv : Nat
  win : Nat
  wbdly : Nat
  ts : Array Nat
  sel : Nat
  actv : Nat
  oos : Nat
  deriving Inhabited

def parseRow (line : String) : Except String Row := do
  let toks := line.splitOn ","
  if toks.length != 22 then
    throw s!"expected 22 columns, got {toks.length}"
  let mut vs : Array Nat := #[]
  for t in toks do
    match t.toNat? with
    | some v => vs := vs.push v
    | none => throw s!"non-numeric token '{t}'"
  let r : Row :=
    { cycle := vs[0]!, now := vs[1]!, st := vs[2]!, cur := vs[3]!, pst := vs[4]!,
      pl := vs[5]!, prr := vs[6]!, pbr1 := vs[7]!, pslot := vs[8]!, winqv := vs[9]!,
      winq := vs[10]!, winv := vs[11]!, win := vs[12]!, wbdly := vs[13]!,
      ts := #[vs[14]!, vs[15]!, vs[16]!, vs[17]!, vs[18]!],
      sel := vs[19]!, actv := vs[20]!, oos := vs[21]! }
  if r.st > 2 || r.pst > 3 || r.cur ≥ 5 || r.pl ≥ 5 || r.prr ≥ 5 || r.winq ≥ 5
      || r.win ≥ 5 || r.pbr1 > 1 || r.pslot > 1 || r.winqv > 1 || r.winv > 1 then
    throw "field out of range"
  return r

def toLane (n : Nat) : Lane := ⟨n % K, Nat.mod_lt _ (by decide)⟩

def decSt : Nat → DState
  | 0 => .idle
  | 1 => .drive
  | _ => .wb

def decPst : Nat → PState
  | 0 => .scan
  | 1 => .req
  | 2 => .wait
  | _ => .cap

def toEngine (r : Row) : Engine :=
  { now := r.now
    actv := fun l s => r.actv.testBit (2 * l.val + (if s then 1 else 0))
    sel := fun l => r.sel.testBit l.val
    ts := fun l => r.ts.getD l.val 0
    pst := decPst r.pst
    pl := toLane r.pl
    prr := toLane r.prr
    pbr1 := r.pbr1 == 1
    pslot := r.pslot == 1
    winq := if r.winqv == 1 then some (toLane r.winq) else none
    st := decSt r.st
    cur := toLane r.cur }

/-- `a ≥ b` as the RTL's signed 16-bit difference. -/
def ge16 (a b : Nat) : Bool := (a % 65536 + 65536 - b % 65536) % 65536 < 32768

def lanes : List Lane := [L0, L1, L2, L3, L4]

def cmpEngine (a b : Engine) : Option String := Id.run do
  if a.now % 65536 != b.now % 65536 then
    return some s!"now: model {a.now % 65536}, rtl {b.now % 65536}"
  if a.st != b.st then return some s!"st: model {repr a.st}, rtl {repr b.st}"
  if a.cur != b.cur then return some s!"cur: model {a.cur}, rtl {b.cur}"
  if a.pst != b.pst then return some s!"pst: model {repr a.pst}, rtl {repr b.pst}"
  if a.pl != b.pl then return some s!"pl: model {a.pl}, rtl {b.pl}"
  if a.prr != b.prr then return some s!"prr: model {a.prr}, rtl {b.prr}"
  if a.pbr1 != b.pbr1 then return some s!"pbr1: model {a.pbr1}, rtl {b.pbr1}"
  if a.pslot != b.pslot then return some s!"pslot: model {a.pslot}, rtl {b.pslot}"
  if a.winq != b.winq then return some s!"winq: model {a.winq}, rtl {b.winq}"
  for l in lanes do
    if a.ts l % 65536 != b.ts l % 65536 then
      return some s!"ts{l}: model {a.ts l % 65536}, rtl {b.ts l % 65536}"
    if a.sel l != b.sel l then
      return some s!"sel{l}: model {a.sel l}, rtl {b.sel l}"
    for s in [false, true] do
      if a.actv l s != b.actv l s then
        return some s!"actv{l}.{s}: model {a.actv l s}, rtl {b.actv l s}"
  return none

structure Report where
  path : String
  checked : Nat := 0
  oosAt : Option Nat := none
  mismatch : Option String := none
  parseErr : Option String := none
  notReady : Nat := 0
  wcViol : Nat := 0
  stalls : Nat := 0
  br1 : Nat := 0
  startOk : Bool := true
  startMsg : String := ""

def Report.failed (r : Report) : Bool :=
  r.parseErr.isSome || r.mismatch.isSome || r.notReady > 0 || r.wcViol > 0
    || r.stalls > 0 || !r.startOk

def Report.line (r : Report) : String :=
  let status := if r.failed then "FAIL" else "ok"
  let oos := match r.oosAt with
    | some k => s!"{k}"
    | none => "never"
  s!"{status} {r.path}: checked={r.checked} oos_at={oos} " ++
  s!"mismatch={r.mismatch.getD "none"} parse={r.parseErr.getD "none"} " ++
  s!"not_ready={r.notReady} wc_viol={r.wcViol} stalls={r.stalls} br1_issues={r.br1} " ++
  s!"start={if r.startOk then "ok" else r.startMsg}"

def parseLive (hdr : String) : Nat := Id.run do
  for tok in (hdr.replace "\r" "").splitOn " " do
    if tok.startsWith "live=" then
      return ((tok.drop 5).toNat?).getD 0
  return 0

def replayFile (path : String) : IO Report := do
  let lines ← IO.FS.lines path
  let mut rep : Report := { path := path }
  if lines.size < 3 then
    return { rep with parseErr := some "fewer than 3 lines" }
  let liveMask := parseLive lines[0]!
  let live : Lane → Bool := fun l => liveMask.testBit l.val
  let mut rows : Array Row := #[]
  for i in [2:lines.size] do
    let ln := lines[i]!.replace "\r" ""
    if ln.isEmpty then continue
    match parseRow ln with
    | .ok r => rows := rows.push r
    | .error msg => return { rep with parseErr := some s!"line {i + 1}: {msg}" }
  if rows.size < 2 then
    return { rep with parseErr := some "fewer than 2 data rows" }
  -- start conditions (row 0)
  let r0 := rows[0]!
  let e0 := toEngine r0
  let mut startMsg := ""
  if r0.pst != 0 then startMsg := startMsg ++ "pst!=SCAN "
  if r0.st != 0 then startMsg := startMsg ++ "st!=IDLE "
  for l in lanes do
    if live l then
      if !(e0.actv l false && e0.actv l true) then
        startMsg := startMsg ++ s!"lane{l}-not-full "
    else
      if e0.actv l false || e0.actv l true then
        startMsg := startMsg ++ s!"dead-lane{l}-not-empty "
    if !(ge16 (e0.ts l) e0.now) then
      startMsg := startMsg ++ s!"lane{l}-overdue "
  rep := { rep with startOk := startMsg.isEmpty, startMsg := startMsg }
  -- replay
  for i in [0:rows.size - 1] do
    let r := rows[i]!
    if r.oos != 0 then
      rep := { rep with oosAt := some i }
      break
    let e := toEngine r
    let P : Program := { live := live, dly := fun _ => r.wbdly }
    let w : Option Lane := if r.winv == 1 then some (toLane r.win) else none
    -- hypotheses: winner ready, work conservation, no stall
    match w with
    | some wl =>
      if !(live wl && ge16 e.now (e.ts wl)) then
        rep := { rep with notReady := rep.notReady + 1 }
      if r.st == 0 && !(e.headValid wl) then
        rep := { rep with stalls := rep.stalls + 1 }
    | none =>
      if lanes.any (fun l => live l && ge16 e.now (e.ts l)) then
        rep := { rep with wcViol := rep.wcViol + 1 }
    -- conformance: the model's step against the next recorded cycle
    let nxt := rows[i + 1]!
    if r.pst == 0 && nxt.pst == 1 && nxt.pbr1 == 1 then
      rep := { rep with br1 := rep.br1 + 1 }
    match cmpEngine (step P (fun _ => w) e) (toEngine nxt) with
    | some msg =>
      rep := { rep with mismatch := some s!"row {i} -> {i + 1}: {msg}" }
      break
    | none => rep := { rep with checked := rep.checked + 1 }
  return rep

def main (args : List String) : IO UInt32 := do
  let mut files : Array String := #[]
  for a in args do
    if (← System.FilePath.isDir a) then
      for ent in (← System.FilePath.readDir a) do
        if ent.fileName.startsWith "trace_" && ent.fileName.endsWith ".csv" then
          files := files.push ent.path.toString
    else
      files := files.push a
  files := files.qsort (· < ·)
  let mut fails := 0
  for path in files do
    let rep ← replayFile path
    IO.println rep.line
    if rep.failed then fails := fails + 1
  IO.println s!"{files.size} traces, {fails} with failures"
  return (if fails == 0 then 0 else 1)
