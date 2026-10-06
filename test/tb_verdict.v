`default_nettype none
`timescale 1ns / 1ps

/* THE ARM-VERDICT PIPELINE, PRICED. This bench exists to FAIL.
 *
 * ⛔⛔ WHY, AND IT IS THE SHARPEST RESULT OF THE WATCHDOG ARC. The sweep's
 * per-arm verdict is a checker like any other, and it was SILENTLY BROKEN for
 * as long as the watchdogs existed. Two independent faults, both mine:
 *
 *   1. the grep wants `*** FAIL`, and `progress.vh`/`clocked_conform.vh`
 *      printed a BARE `FAIL` -- so no watchdog failure ever matched;
 *   2. the log is CUT at the first `$finish`, and both watchdogs report from
 *      `final` blocks, whose output lands AFTER that line -- so every
 *      watchdog summary, including the anti-vacuity one, was discarded before
 *      the grep ran.
 *
 * I had written, in comments and in a commit message, that the watchdogs
 * "print FAIL so the sweep's grep catches it". That was false twice over. The
 * moment both were fixed, FOUR ARMS WENT RED -- every one a refusal test whose
 * quiescence is the claim, which then had to declare itself.
 *
 * ⇒ So the pipeline is now PRICED, permanently and inside the sweep: this
 *   bench prints a watchdog-shaped failure from a `final` block and NOTHING
 *   ELSE. Its arm is declared XFAIL in `test/benchset.py`, so the sweep
 *   REQUIRES it to come out red. If a future change to the log cut or the grep
 *   pattern blinds the verdict again, THIS arm starts "passing" and the sweep
 *   fails on it -- the only way to notice a checker that has stopped checking.
 * ⚠ IT PRICES BOTH FAULTS AT ONCE because it reproduces both conditions
 *   together: the `*** FAIL` prefix AND emission from a `final` block after
 *   `$finish`. Either regression alone turns this arm green, which is a
 *   failure of the sweep.
 *
 * ⭐⭐ BOTH HALVES ARE MEASURED, not asserted. Taking this bench's own log and
 * applying each variant of the cut, with the real grep:
 *
 *     current cut (keeps watchdog lines after $finish)  fail-lines=1 -> RED
 *     old cut     (exits at $finish)                    fail-lines=0 -> GREEN
 *
 * and reverting the grep to a pattern without `\*\*\* FAIL` turned the arm
 * GREEN in a full sweep run, which the sweep then reported as
 * "XFAIL ARM CAME OUT GREEN". Either regression alone blinds the verdict, and
 * either one alone is caught.
 * ⚠ A FIRST ATTEMPT AT THIS MEASUREMENT PROVED NOTHING: the script meant to
 * revert the cut used a regex that did not match, so the "before" case ran
 * the UNCHANGED script and came out red -- which looked like the cut not
 * mattering. It was caught only because the script also printed a grep count
 * showing the revert had not applied. A must-fire that did not fire is
 * indistinguishable from one that cannot.
 *
 * ⛔ IT INSTANTIATES NO DUT. There is nothing to verify here -- the subject is
 * the harness, not the design -- and a DUT would only add ways for this bench
 * to fail for the wrong reason.
 */
module tb_verdict ();

  reg clk = 1'b0;

  always #10 clk = ~clk;

  initial begin
    // a short, bounded run: the point is the verdict, not the simulation
    repeat (20) @(negedge clk);
    $display("  tb_verdict: the run itself is fine; the verdict comes from the");
    $display("              final block below, exactly as a watchdog's does");
    $finish;
  end

  // ⛔ A `final` BLOCK, DELIBERATELY. This is where `progress.vh` and
  // `clocked_conform.vh` report from, and it is the half of the pipeline the
  // log cut used to throw away. The text carries `progress.vh` so the cut's
  // allow-list is exercised too, and the `*** FAIL` prefix so the grep is.
  final begin
    $display("*** FAIL progress.vh: THE VERDICT PIPELINE MUST-FIRE -- this arm is declared XFAIL and must come out RED; if it passes, the sweep has stopped seeing watchdog verdicts");
  end

endmodule
`default_nettype wire
