/* imgload.vh -- an image that did not load is a FAILURE, said by the bench.
 *
 * ⛔⛔ WHY (ruling CI3). A Verilog string reg SILENTLY TRUNCATES a longer
 * `$value$plusargs("IMG=%s")` value, and `$readmemh` on a path it cannot open
 * only WARNS. `tb_trace` was bitten exactly this way: a 64-byte name buffer, a
 * 99-byte CI checkout path, no trace, a clean `$finish` and exit 0 -- five
 * consecutive commits red in CI while green on the development box, whose
 * path happened to be short. Every other bench declared the same 64 bytes and
 * was safe ONLY because `test/benchset.py` passes short relative paths.
 *
 * ⇒ Every bench now has a 256-byte name buffer, and this macro, run right
 *   after the load, FAILS LOUDLY on either of:
 *     (a) a name that FILLS the buffer -- its top byte is non-zero, so it may
 *         have been truncated, and a truncated name can even open a DIFFERENT
 *         file that happens to exist;
 *     (b) a file that cannot be OPENED -- missing, or a truncated name.
 *
 * ⛔⛔ THE FIRST VERSION TESTED `^img[0] === 1'bx` AND IT COULD NOT FIRE UNDER
 * VERILATOR. Verilator is two-state: with `+verilator+rand+reset+2` an
 * unloaded store holds RANDOM bits, never X. MEASURED: a 299-byte path was
 * truncated, `$readmem file not found` was printed, and the macro stayed
 * silent while the bench ran on an empty store. That is the
 * check-that-could-not-fire class appearing inside the fix for it. Both tests
 * below are about the NAME and the FILE, so they mean the same thing in a
 * two-state and a four-state simulator.
 * ⚠ THE OLDER X-SCAN IN `tb_smoke` (deriving the loaded length from the first
 * X) has the same blind spot under Verilator; this macro now covers that
 * bench in both simulators, and the X-scan is left as the iverilog-side
 * length measurement it effectively always was.
 *
 * ⭐ ONE DEFINITION, used by every bench, rather than a line pasted into
 * thirteen: a guard that exists thirteen times can be fixed in twelve.
 * ⭐ `FNAME[8*256-1 -: 8]` ALSO TIES THE MACRO TO THE BUFFER WIDTH: a bench
 * that declared a narrower name buffer would index out of range here.
 *
 * USAGE:  `include "test/imgload.vh"   then, right after `$readmemh`:
 *         `PE_REQUIRE_IMG_LOADED(imgfile)
 */
`ifndef PE_IMGLOAD_VH
`define PE_IMGLOAD_VH
`define PE_REQUIRE_IMG_LOADED(FNAME) \
    begin : pe_imgload_check \
      integer pe_imgfd; \
      if (FNAME[8*256-1 -: 8] != 8'h00) begin \
        $display("*** FAIL %m: +IMG fills the whole 256-byte name buffer, so it may have been TRUNCATED -- Verilog does that to a long plusarg silently. Use a shorter path."); \
        $finish; \
      end \
      pe_imgfd = $fopen(FNAME, "r"); \
      if (pe_imgfd == 0) begin \
        $display("*** FAIL %m: +IMG=%0s cannot be opened, so the image did not load -- $readmemh only warns and the bench would run on an empty store.", FNAME); \
        $finish; \
      end \
      $fclose(pe_imgfd); \
    end
`endif
