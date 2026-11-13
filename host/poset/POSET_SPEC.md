# The poset spec language — reference (DRAFT v0, for Wilson's ruling)

A **poset spec** says which wire events happen, in what order, and within what time bounds.
It is what the PIT emits after sniffing a bus (emitter v2), what the host compiler turns into a
chip program, and what the validator checks against the live bus (guiding doc, steps 4–6).

It extends the RPL spec of emitter v1 (`model/pit_emit.py`, Wilson 11-06 D1). **Every v1 spec stays a
valid v2 spec.** The pattern operators are Rapide's (LRM vol. 5, *Patterns*, §2.4), restricted
to the ones a chip or a host can check, plus vol. 5's `Timing` macro in its `during` form (§2.6).

## 1. File shape (v1, unchanged)

```
spec <name> is
  <statement> ;
  ...
end <name> ;
```
One statement per line, each ending in `;`. `--` starts a comment, which parsers drop. Real time
everywhere: bounds are in ns, and the target clock is applied by the compiler (v1 D1 change 1).

## 2. Grammar (EBNF)

```
spec        ::= 'spec' NAME 'is' { statement ';' } 'end' NAME ';'
statement   ::= v1_statement                       -- captured, partial, wire, crc, bus, '? unknown'
              | 'pattern' pattern [ timing ] { clause }
              | 'never'   pattern [ timing ] { clause }

pattern     ::= term { binop term }                -- one precedence level, left-associative (vol5 §2.1)
term        ::= event | '(' pattern ')' | repeat
binop       ::= '->'                               -- sequence            (vol5 §2.4.1)
              | '|>'                               -- immediate sequence  (vol5 §2.4.2)
              | '||'                               -- independence        (vol5 §2.4.4)
              | '~'                                -- join                (vol5 §2.4.3)
              | 'or'                               -- disjunction         (vol5 §2.4.5)
              | 'and'                              -- conjunction         (vol5 §2.4.6)
repeat      ::= '[' INT '->' ']' term              -- bounded iteration, '->' only (vol5 §2.4.8, bounded form)

event       ::= KIND '(' WIRE { ',' WIRE } ')'
KIND        ::= 'Rise' | 'Fall' | 'Edge'           -- raw pin events
              | 'Start' | 'Stop'                   -- I2C conditions on (sda, scl)
              | 'Frame' | 'Byte'                   -- decoded, on a data wire (v1's Frame)
WIRE        ::= 'uio' DIGIT                        -- v1's wire names

timing      ::= 'during' '(' TIME ',' TIME ')'     -- vol5 Timing macro, as v1 already parses
TIME        ::= NUMBER 'ns'
clause      ::= 'observed' INT                     -- the bound and the order were seen in INT instances
              | 'given' NAME                       -- the order holds only under a stated condition (v1 style)
              | 'source' ( 'data' | 'datasheet' STRING )
```

Dropped from vol. 5, with the reasons:
- **Placeholders and guards** (`(?x : T)`, `where`) need value matching. The chip validator's predicates are order, window, membership and integrity (guiding doc step 4), and none of them bind variables.
- **`union`** is redundant with `and` for checking.
- **Unbounded iteration**: the compiler needs a static instance count.

v1's stray `<` operator (in `_PAT`) is **not** in v2. It has no meaning in vol. 5. v1 text never emits it.

## 3. Meaning

**Events and their instants.** An event is an instance seen on the capture, stamped at the capture's resolution.

| kind | instant |
|---|---|
| `Rise(w)`, `Fall(w)`, `Edge(w)` | the sampled transition on `w` |
| `Start(sda, scl)`, `Stop(sda, scl)` | the `sda` transition while `scl` is high |
| `Frame(w)` | the first edge of a frame on data wire `w` (v1) |
| `Byte(w)` | the sample instant of the byte's last data bit |

Instances of one kind are numbered in time order: the 1st, 2nd, … instance.

**Operators.** These are checked on instance numbers, the way the validator's ordering predicate is: "the nth A before the nth B".

| pattern | holds when |
|---|---|
| `A -> B` | every instance of A is followed, later, by its matching instance of B |
| `A \|> B` | as `->`, and no other event *of the kinds this pattern names* falls between them (vol5's "no intervening event", scoped to the pattern's own alphabet) |
| `A \|\| B` | both orders occur among the instance pairs (§4: only ever emitted when both were seen) |
| `A ~ B` | both occur; their order is not constrained |
| `A or B`, `A and B` | either / both of the sub-patterns hold |
| `[n ->] A` | n instances of A in sequence |

**Timing.** `P during (lo, hi)` means: for every match of `P`, (last instant − first instant) ∈ [lo, hi]. Comparison uses the tolerance in guiding doc §7 step 6: ±J (J = 2 cycles), plus 1 sync cycle, plus the capture resolution, converted at the target clock. A bound tighter than ±J is refused by the compiler.

**`never P`**: no match of `P` occurs. Validator verdicts are VIOLATION or ABSTAIN. "Conforms" means every armed check passed **on positive evidence** (guiding doc §5).

## 4. What the PIT is allowed to emit (inference rules, guiding doc step 6)
- `->` when A preceded B in every one of n ≥ 1 observed instance pairs. The statement carries `observed n`, and its confidence is the rule of three (3/n), stated in the clause and never rounded up.
- `||` only when **both** orders were observed. Otherwise the order stays `->` with `observed n` ("ordered-as-observed").
- **Every bound the PIT emits is `observed`**: `during (min seen, max seen)`. A datasheet bound is `source datasheet "<part>"`, written by a person, never by the PIT.
- Unknowns stay v1's `? unknown <field> -- <reason>;` lines. Nothing is inferred on the host.

## 5. Examples (the golden model's three known buses)

```
-- SPI: chip select falls before the first clock edge (the "lead" time)
pattern Fall(uio3) |> Rise(uio1) during (83.3 ns, 2083.3 ns) observed 37;
-- I2C: START before the first SCL fall (t_HD;STA), and before the first data byte
pattern Start(uio2, uio1) |> Fall(uio1) during (600.0 ns, 900.0 ns) observed 12;
pattern Start(uio2, uio1) -> Byte(uio2) observed 12;
-- UART: the start bit before the byte's last data bit. Frame, not Fall: a raw Fall(uio0) also
-- matches the data bits' falling edges inside the frame, so `Fall(uio0) |> Byte(uio0)` does not hold
pattern Frame(uio0) |> Byte(uio0) during (30000.0 ns, 31000.0 ns) observed 64;
```
These numbers are **placeholders that show the shape**. The golden model generates the real ones (operating rule: numbers are generated, never typed).

## 6. Open decisions (for Wilson)
1. **The event vocabulary.** A closed set (above, 7 kinds), or open, with the kinds declared in the spec? Closed keeps the compiler and the validator total. **Recommend closed for v2.**
2. **`|>` scoped to the pattern's own alphabet.** vol. 5 scopes it to the whole match set S, which on a sniffed bus is every edge on every wire, so the pattern would almost never hold. **Recommend the pattern's alphabet.**
3. **Placeholders and guards dropped** for v2, as above.
4. **`observed n` on every inferred statement**, with the rule-of-three confidence in the clause.
5. **Instance matching for `->`:** nth-to-nth (the validator's ordering predicate). The alternative is Rapide's "some match exists", which is weaker and isn't checkable causally. **Recommend nth-to-nth.**
