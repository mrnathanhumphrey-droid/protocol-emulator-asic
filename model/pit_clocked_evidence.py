"""MODEL-SIDE EVIDENCE for stage 3 on a clocked bus, the sampled second capture
(Wilson 11-06): the frozen golden's clocked_bus / sampled_capture /
stage3_clocked on synthetic SPI (modes 0-3) and I2C buses -- data changing at
the shift edge, +1, +3 cycles or mid-level, half-periods 20 and 64, CRC-8
SMBus / CRC-16 XMODEM / CCITT-FALSE frames of 1-2 data bytes, re-armed
mid-frame. Checks per case: the inferred sample edge (modes 0, 3 rise; 1, 2
fall; I2C rise), the decoded frames = the sent ones from the first whole frame
after re-arm, >= 8 frames, the poly, and an init / xorout that reproduces
every frame. Then the frame-length limit stage 0 imposes (the first capture
must type the bus). Exit 1 on any miss. Run: python model/pit_clocked_evidence.py"""
import random, sys, zlib, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pit_s0_golden as S0

G = S0.frozen_model()


def crc_msb(data, w, poly, init, xorout):
    r = init
    for b in data:
        for i in range(7, -1, -1):
            top = (r >> (w - 1)) & 1
            r = ((r << 1) & ((1 << w) - 1)) ^ (poly if top ^ ((b >> i) & 1) else 0)
    return r ^ xorout


def frames(rnd, n, lens, w, poly, init, xorout):
    out = []
    for k in range(n):
        L = lens[k % len(lens)]
        d = [rnd.randrange(256) for _ in range(L)]
        c = crc_msb(d, w, poly, init, xorout)
        out.append(d + [(c >> (8 * i)) & 0xFF for i in range(w // 8 - 1, -1, -1)])
    return out


class Wave:
    def __init__(s, lv):
        s.ev, s.lv = {}, dict(lv)

    def set(s, t, w, v):
        if s.lv[w] != v:
            s.ev[t] = s.ev.get(t, 0) ^ (1 << w)
            s.lv[w] = v


def spi(msgs, mode, H, skew, gap, CK=0, DO=1, CS=2):
    cpol, cpha = mode >> 1, mode & 1
    wv = Wave({CK: cpol, DO: 0, CS: 1})
    t, starts = 100, []
    for m in msgs:
        bits = [(b >> (7 - i)) & 1 for b in m for i in range(8)]
        starts.append(t)
        wv.set(t, CS, 0)
        t += H
        for i, b in enumerate(bits):
            # shift edge -> data (skew); sample edge H later
            if cpha == 0:
                wv.set(t - H // 2 if skew == "mid" else (t - H + skew if i else t - H + 1), DO, b)
                wv.set(t, CK, 1 - cpol); wv.set(t + H, CK, cpol)
            else:
                wv.set(t, CK, 1 - cpol)
                wv.set(t + (H // 2 if skew == "mid" else skew), DO, b)
                wv.set(t + H, CK, cpol)
            t += 2 * H
        t += H
        wv.set(t, CS, 1)
        t += gap
    return sorted(wv.ev.items()), t, starts, {CK: cpol, DO: 0, CS: 1}


def i2c(msgs, H, skew, gap, CK=0, DA=1, sr_every=0):
    wv = Wave({CK: 1, DA: 1})
    t, starts = 100, []
    for k, m in enumerate(msgs):
        starts.append(t)
        wv.set(t, DA, 0); t += H                       # START
        for b in m:
            for bit in [(b >> (7 - i)) & 1 for i in range(8)] + [0]:
                wv.set(t, CK, 0)
                wv.set(t + (H // 2 if skew == "mid" else skew), DA, bit)
                wv.set(t + H, CK, 1); t += 2 * H
        wv.set(t, CK, 0); wv.set(t + H // 2, DA, 0); wv.set(t + H, CK, 1); wv.set(t + 2 * H, DA, 1)
        t += 3 * H                                      # STOP
        t += gap
    return sorted(wv.ev.items()), t, starts, {CK: 1, DA: 1}


def lv_word(d):
    return sum(v << w for w, v in d.items())


def run(kind, mode, skew, H, cat, seed):
    rnd = random.Random(seed)
    w, poly, init, xorout = cat
    msgs = frames(rnd, 120, (1, 2), w, poly, init, xorout)
    if kind == "SPI":
        log, T, starts, lv0d = spi(msgs, mode, H, skew, 30 * H)
    else:
        log, T, starts, lv0d = i2c(msgs, H, skew, 30 * H)
    lv0 = lv_word(lv0d)
    cap = S0.stored_capture(log, lv0, None, T)
    if cap is None:
        return "first capture never stopped"
    cls = G.classify_bus(cap, lv0)
    bus = G.clocked_bus(cap, lv0, cls)
    # re-arm at T2 = 2/5 of the way in (mid-frame on purpose)
    T2 = T * 2 // 5 + 7
    lv2, log2 = lv0, []
    for t, m in log:
        if t < T2:
            lv2 ^= m
        else:
            log2.append((t - T2 + 1, m))
    rec, out = G.stage3_clocked_rc(cap, lv0, cls, log2, lv2, 1 << 30, T - T2 + 10)
    want_edge = None
    if kind == "SPI":
        want_edge = 1 - ((mode >> 1) ^ (mode & 1))     # modes 0, 3 sample on the rise
    else:
        want_edge = 1
    first = next(i for i, s in enumerate(starts) if s > T2)
    got = out.get("msgs", [])
    exp = msgs[first:first + len(got)]
    io = out.get("io", {})
    ok = (bus.get("edge") == want_edge and got == exp and len(got) >= 8 and out.get("status") == "OK"
          and out["poly"]["poly"] == poly and io.get("init") is not None
          and all(crc_msb(m[:-w // 8], w, poly, io["init"], io["xorout"]) ==
                  int.from_bytes(bytes(m[-w // 8:]), "big") for m in got))
    return ("ok  " if ok else "BAD ") + "edge=%s want=%s frames=%d match=%s stop=%s status=%s poly=%s init=%s xorout=%s %s" % (
        bus.get("edge"), want_edge, len(got), got == exp, out.get("stop"), out.get("status"),
        hex(out.get("poly", {}).get("poly", -1)) if isinstance(out.get("poly"), dict) and "poly" in out["poly"] else "-",
        hex(io["init"]) if io.get("init") is not None else "-", hex(io["xorout"]) if io.get("init") is not None else "-",
        bus.get("why", "") or out.get("why", "") or "")


CATS = {"CRC-8 SMBus": (8, 0x07, 0x00, 0x00), "CRC-16/XMODEM": (16, 0x1021, 0, 0),
        "CRC-16/CCITT-FALSE": (16, 0x1021, 0xFFFF, 0)}
bad = 0
for H in (20, 64):
    for skew in (0, 1, 3, "mid"):
        for mode in range(4):
            for name, cat in CATS.items():
                r = run("SPI", mode, skew, H, cat, zlib.crc32(repr((H, skew, mode, name)).encode()))
                bad += r.startswith("BAD")
                if r.startswith("BAD") or name == "CRC-16/CCITT-FALSE":
                    print("SPI H=%-3d skew=%-4s mode %d %-19s %s" % (H, skew, mode, name, r))
        for name, cat in CATS.items():
            r = run("I2C", 0, skew, H, cat, zlib.crc32(repr((H, skew, name)).encode()))
            bad += r.startswith("BAD")
            print("I2C H=%-3d skew=%-4s        %-19s %s" % (H, skew, name, r))
print("cases BAD:", bad, "of 120")
# the limit stage 0 imposes: frame bytes (incl. a 2-byte CRC) the first capture still types
print("stage 0 typing limit (frame bytes incl. CRC: ok / -- = no clocked bus with frame markers)")
for kind in ("SPI", "I2C"):
    for H in (20, 64):
        row = []
        for L in range(1, 9):
            rnd = random.Random(L)
            msgs = frames(rnd, 60, (L,), 16, 0x1021, 0xFFFF, 0)
            log, T, starts, lv0d = spi(msgs, 0, H, 1, 30 * H) if kind == "SPI" else i2c(msgs, H, 1, 30 * H)
            lv0 = lv_word(lv0d)
            cap = S0.stored_capture(log, lv0, None, T)
            bus = G.clocked_bus(cap, lv0, G.classify_bus(cap, lv0))
            row.append("%d:%s" % (L + 2, "ok" if "why" not in bus else "--"))
        print("  %s H=%-3d %s" % (kind, H, " ".join(row)))
print("GATE pit-clocked-evidence: %s" % ("PASSED" if bad == 0 else "FAILED"))
sys.exit(1 if bad else 0)
