#!/usr/bin/env bash
# RULING S's MUST-FIRE: a lighter lane set's A2 bound on a heavier program.
#
# ⛔⛔ WHY THIS EXISTS. The single `CK_GAP_SLACK = 8` was derived for the A2
# model's shipped lane set and then enforced on `ckod` -- a DIFFERENT lane set.
# It held only because `ckod`'s measured lateness (7) happened to sit under it,
# so nothing on the bench could ever show that a bound belongs to a program.
# This runs ONE ADMISSIBLE program, `ckheavy` (ruling DT-C: three clocked
# open-drain lanes at 30/31/32 beside two busy push-pull lanes; U = 0.583,
# J = 1, 1.6a met, measured lateness 10/11/13), twice. ⛔ It replaced
# `ckdense`, which fails 1.6a under W1 (DT-B) and so cannot carry a claim:
# a must-fire on a program outside the model proves nothing about the model.
#
#   own    -- with ITS OWN derived per-lane budgets (clocked_a2_bounds.json) -> must PASS
#   light  -- with `corpus_i2c`'s budget (8) on every clocked lane -> must FAIL
#
# If `light` passes, the per-program derivation is indistinguishable on the
# bench from one shared number and ruling S bought nothing. If `own` fails, the
# derivation is unsound for that program.
# ⚠ ~40s for one Verilator build, declared. The gate is RED without the
# measurement rather than skipping.
#
# Usage:  bash test/a2_run.sh [outdir]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
OUT="${1:-$ROOT/probe_a2}"
PY="${PE_PYTHON:-python}"
command -v "$PY" >/dev/null 2>&1 || PY=python3
. "$ROOT/ci/tools.sh"     # ruling V: $VL from PE_VERILATOR, made absolute
command -v "$VL" >/dev/null 2>&1 || { echo "  *** no verilator at $VL"; exit 1; }
tool_banner verilator

rm -rf "$OUT"; mkdir -p "$OUT"
JSON="$OUT/a2.json"

SUBJ=ckheavy_image.hex
"$PY" test/make_smoke_image.py --ckheavy > "$OUT/img.log" 2>&1 || exit 1
"$PY" test/corpus.py >> "$OUT/img.log" 2>&1 || exit 1

# ⛔ BOTH BUDGETS COME FROM THE GENERATED FILE, never typed here: `own` is the
# heavy program's row and `light` is built from the light program's single
# clocked-lane budget, so the must-fire tracks the derivation if it moves.
# ⭐ `light` goes on EXACTLY the subject's clocked lanes (read from its row),
# -1 elsewhere -- the subject has push-pull lanes that carry no A2 budget.
OWN="$("$PY" -c "import sys; sys.path.insert(0,'test'); import benchset as b; print(b.a2_slack_arg('test/$SUBJ').split('=',1)[1])")" || exit 1
LIGHT="$("$PY" -c "
import json; b=json.load(open('test/clocked_a2_bounds.json'))
v=b['corpus_i2c.hex']['lanes']['0']['slack']; ck=b['$SUBJ']['lanes']
print(','.join(str(v) if str(i) in ck else '-1' for i in range(5)))")" || exit 1
echo "  own   budgets ($SUBJ's own lane set) : $OWN"
echo "  light budgets (corpus_i2c's, on its clocked lanes) : $LIGHT"

SRCS="test/tb_trace.v test/fram_i2c.v test/fram_spi.v src/pe_engine.v src/pe_store.v src/project.v"
FLAGS="--cc --exe --main --timing --public-flat-rw -Wno-fatal"
"$VL" $FLAGS +incdir+test +incdir+. -Mdir "$OUT/build" -o a2.sim \
      --top-module tb_trace $SRCS > "$OUT/build.log" 2>&1
make -C "$OUT/build" -f Vtb_trace.mk -j 4 >> "$OUT/build.log" 2>&1
[ -x "$OUT/build/a2.sim" ] || { echo "  *** build failed"
    grep -E '^%Error' "$OUT/build.log" | head -4; exit 1; }

IMG=test/$SUBJ
NB=$(tr -s ' \n' '\n' < "$IMG" | grep -cv '^$')
rc=0
for arm in own light; do
  if [ "$arm" = own ]; then SL="$OWN"; else SL="$LIGHT"; fi
  ( cd "$OUT/build" && ./a2.sim +IMG="$ROOT/$IMG" +NBYTES="$NB" +PEER=none \
      +NCYC=60000 +SCLHOLD=0 +A2SLACK="$SL" +OUT="$OUT/trace_$arm.txt" \
      --x-initial unique +verilator+rand+reset+2 ) > "$OUT/run_$arm.log" 2>&1
  if ! grep -q "clocked_conform\[A2\]" "$OUT/run_$arm.log"; then
    echo "  *** $arm: layer A2 never spoke"
    sed -n '1,12p' "$OUT/run_$arm.log" | sed 's/^/      | /'
    rc=1
  fi
done
[ $rc -eq 0 ] || exit 1

"$PY" - "$OUT" "$JSON" "$OWN" "$LIGHT" <<'PYEOF'
import io, json, re, sys
out, path, own, light = sys.argv[1:5]
res = {}
for arm, sl in (("own", own), ("light", light)):
    t = io.open("%s/run_%s.log" % (out, arm), encoding="utf-8",
                errors="replace").read()
    red = re.search(r"\*\*\* FAIL clocked_conform\[A2\]: (\d+) of (\d+) "
                    r"releases later", t)
    ok = re.search(r"clocked_conform\[A2\]: ok -- (\d+) release", t)
    lanes = re.search(r"clocked_conform\[A2\] lanes: budget ([-\d,]+) "
                      r"widest ([-\d,]+)", t)
    res[arm] = {
        "budget": sl,
        "verdict": "red" if red else ("ok" if ok else None),
        "late": int(red.group(1)) if red else 0,
        "releases": int(red.group(2)) if red else (int(ok.group(1)) if ok
                                                   else None),
        "lane_widest": ([int(x) for x in lanes.group(2).split(",")]
                        if lanes else None),
    }
io.open(path, "w", encoding="utf-8", newline="\n").write(
    json.dumps(res, indent=1, sort_keys=True))
for arm in ("own", "light"):
    r = res[arm]
    print("  %-6s budget %-18s verdict %-5s late %-5s widest per lane %s"
          % (arm, r["budget"], r["verdict"], r["late"], r["lane_widest"]))
PYEOF
echo
echo "  ⇒ measurement written to $JSON"
echo "    PE_A2_JSON=$JSON"
