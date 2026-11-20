"""symgen_model -- THE GOLDEN MODEL of the symbol generator, option (c) K = 4
(Wilson 11-17; the spare codes 5-7 in, 11-19). The RTL (`pe_symgen` in
src/pe_engine.v) is judged against it cycle for cycle by test/run_symgen.py.
Moved from agent 1's 11-17 study, where the prototype matched it bit for bit.

One dispatch hands the generator ONE BYTE. The generator emits `nbits` bits, each bit
a SYMBOL of K slots; slot j lasts len[j] cycles and drives two pins (A = data, B = a
second pin: clock, strobe or the complement) with a 3-bit code each:
    0 LOW   1 HIGH   2 D (the bit)   3 ~D   4 HOLD (keep the pin's current level)
A ONE-BYTE HOLDING REGISTER decouples the dispatch from the waveform: the generator
starts LAT cycles after the first load and then runs bytes back to back; a byte
whose slot comes up with the holding register empty is an UNDERRUN -- the generator
stops, both pins go to their idle levels, and the next load restarts it (+LAT).
Options (a) pulse width and (b) Manchester are TABLE INSTANCES of this (below).

The model is cycle-exact and is the reference the Verilog prototype must match.
"""
from __future__ import annotations

LOW, HIGH, D, ND, HOLD = 0, 1, 2, 3, 4
# the spare codes (Wilson 11-17: modelled, then decoded in the prototype, then synthesised)
TOG, TOG_D, TOG_ND = 5, 6, 7        # invert; invert if the bit is 1; invert if the bit is 0


class Cfg:
    def __init__(self, lens, code_a, code_b, nbits=8, msb=True, idle_a=0, idle_b=0, lat=4):
        assert len(lens) == len(code_a) == len(code_b) and 1 <= len(lens) <= 4
        assert all(1 <= n <= 63 for n in lens)
        self.lens, self.code_a, self.code_b = list(lens), list(code_a), list(code_b)
        self.nbits, self.msb, self.idle_a, self.idle_b, self.lat = nbits, msb, idle_a, idle_b, lat

    @property
    def bit_cycles(self):
        return sum(self.lens)

    @property
    def byte_cycles(self):
        return self.bit_cycles * self.nbits


def _lvl(code, d, cur):
    return {LOW: 0, HIGH: 1, D: d, ND: 1 - d, HOLD: cur,
            TOG: 1 - cur, TOG_D: cur ^ d, TOG_ND: cur ^ (1 - d)}[code]


def run(cfg, loads, ncyc):
    """loads: {cycle: byte} -- the dispatches (one byte each). Returns per-cycle
    [(a, b, running)], plus the underrun count. Semantics are those of symgen.v:
    every register updates on the cycle edge; a load at cycle t is visible at t+1."""
    a, b = cfg.idle_a, cfg.idle_b
    hv, hb = 0, 0                 # holding register
    run_, sr, bit, slot, cnt = 0, 0, 0, 0, 0
    wait = -1                     # start countdown (LAT) after a load while stopped
    und = 0
    ovr = 0
    out = []
    for t in range(ncyc):
        out.append((a, b, run_))
        # ---- next state (all from the CURRENT registers) ----
        n_a, n_b, n_hv, n_hb = a, b, hv, hb
        n_run, n_sr, n_bit, n_slot, n_cnt, n_wait = run_, sr, bit, slot, cnt, wait
        load = t in loads
        if run_:
            last_cyc = cnt == cfg.lens[slot] - 1
            if last_cyc:
                last_slot = slot == len(cfg.lens) - 1
                if last_slot:
                    if bit == cfg.nbits - 1:            # byte boundary
                        if hv:
                            n_sr, n_hv, n_bit, n_slot, n_cnt = hb, 0, 0, 0, 0
                            d = (hb >> (cfg.nbits - 1)) & 1 if cfg.msb else hb & 1
                            n_a, n_b = _lvl(cfg.code_a[0], d, a), _lvl(cfg.code_b[0], d, b)
                        else:                           # underrun: stop, idle
                            n_run, n_a, n_b = 0, cfg.idle_a, cfg.idle_b
                            und += 1
                    else:
                        n_bit, n_slot, n_cnt = bit + 1, 0, 0
                        d = (sr >> (cfg.nbits - 2 - bit)) & 1 if cfg.msb else (sr >> (bit + 1)) & 1
                        n_a, n_b = _lvl(cfg.code_a[0], d, a), _lvl(cfg.code_b[0], d, b)
                else:
                    n_slot, n_cnt = slot + 1, 0
                    d = (sr >> (cfg.nbits - 1 - bit)) & 1 if cfg.msb else (sr >> bit) & 1
                    n_a, n_b = _lvl(cfg.code_a[slot + 1], d, a), _lvl(cfg.code_b[slot + 1], d, b)
            else:
                n_cnt = cnt + 1
        elif wait >= 0:
            if wait == 0:                               # start the first byte
                n_run, n_sr, n_hv, n_bit, n_slot, n_cnt, n_wait = 1, hb, 0, 0, 0, 0, -1
                d = (hb >> (cfg.nbits - 1)) & 1 if cfg.msb else hb & 1
                n_a, n_b = _lvl(cfg.code_a[0], d, a), _lvl(cfg.code_b[0], d, b)
            else:
                n_wait = wait - 1
        if load:                                        # a dispatch fills the holding register
            if hv and n_hv:                             # still holding an unconsumed byte: OVERRUN
                ovr += 1
            n_hv, n_hb = 1, loads[t]
            if not run_ and wait < 0:
                n_wait = cfg.lat - 1
        a, b, hv, hb = n_a, n_b, n_hv, n_hb
        run_, sr, bit, slot, cnt, wait = n_run, n_sr, n_bit, n_slot, n_cnt, n_wait
    return out, und, ovr


def runs(seq):
    """[(level, length)] run-length of a 0/1 sequence"""
    r = []
    for v in seq:
        if r and r[-1][0] == v:
            r[-1][1] += 1
        else:
            r.append([v, 1])
    return [tuple(x) for x in r]


# ---------------------------------------------------------------------------
# the three targets as table instances
# ---------------------------------------------------------------------------
def ws2812(L=19):
    """(a) pulse width as a table: 4 slots of L; bit 0 = 1000, bit 1 = 1100."""
    return Cfg([L] * 4, [HIGH, D, LOW, LOW], [LOW] * 4, idle_a=0, idle_b=0)


def manchester():
    """(b) 10BASE-T Manchester at 60 MHz: 2 half-bits of 3 cycles; IEEE 802.3: a 1 is
    low-then-high at the bit centre. Pin B = the complement (the differential pair).
    LSB first (802.3 sends each octet LSB first). Idle: both LOW (zero differential)."""
    return Cfg([3, 3], [ND, D], [D, ND], msb=False, idle_a=0, idle_b=0)


def spi_dirty(mode, half=30):
    """the data-phase case: data changes ONE cycle before the leading clock edge, i.e.
    late in the level BEFORE it (pit-clk dirty_rise = mode 1, dirty_fall = mode 3).
    B = SCK, A = MOSI. Slot lengths [half-1, 1, half-1, 1]."""
    idle = 0 if mode in (0, 1) else 1
    ck = [idle, idle, 1 - idle, 1 - idle]
    return Cfg([half - 1, 1, half - 1, 1], [HOLD, D, D, D], ck, idle_a=0, idle_b=idle)


def nrzi(bit=5):
    """NRZI as USB sends it: a 0 toggles the line, a 1 holds it. One slot per bit, LSB first."""
    return Cfg([bit], [TOG_ND], [LOW], msb=False, idle_a=1, idle_b=0)


def diff_manchester(half=3):
    """differential Manchester (IEEE 802.5): always a transition at the bit centre; a 0
    also has one at the bit start."""
    return Cfg([half, half], [TOG_ND, TOG], [LOW, LOW], idle_a=0, idle_b=0)


def biphase_mark(half=3):
    """biphase-mark (AES3 / S/PDIF data coding): always a transition at the bit start; a 1
    also has one at the bit centre."""
    return Cfg([half, half], [TOG, TOG_D], [LOW, LOW], idle_a=0, idle_b=0)
