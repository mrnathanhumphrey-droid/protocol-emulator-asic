/* imgpatch.vh -- a REFUSED word planted into an admissible image AS IT LOADS.
 *
 * ⭐ 11-20 (the coverage sweep's refusal arms). A refusal arm needs the bench to
 * load a word pe_isa refuses, but every image a sweep arm names with `+IMG=` is
 * in the image universe, and gate_admissible_images' HDR check runs
 * `pe_isa.flag_problems` on every one of them -- NOT declarable, by design. So
 * the image ON DISK is the arm's clean twin (admissible), and the refused bytes
 * are written into the bench's copy after `$readmemh`: the same pattern as
 * tb_trace's `+RESOP_AT` (the reserved opcode planted at load). The runner
 * computes the patches from (clean twin, refused image) with
 * `pe_isa.patch_plusargs`, which refuses more than PE_N_PATCH differing bytes.
 *
 * USAGE:  `include "test/imgpatch.vh"   then, right after the load check:
 *         `PE_APPLY_IMG_PATCHES(img)
 *         +PATCH0=<(addr << 8) | byte> ... +PATCH3=...  (absent: no patch)
 * Each applied patch is PRINTED, so a log always says the run was not the
 * on-disk image.
 */
`ifndef PE_IMGPATCH_VH
`define PE_IMGPATCH_VH
`define PE_APPLY_IMG_PATCH1(IMG, NAME) \
    if ($value$plusargs(NAME, pe_pw)) begin \
      $display("PATCH byte %0d: %02h -> %02h (planted at load)", pe_pw >> 8, IMG[pe_pw >> 8], pe_pw[7:0]); \
      IMG[pe_pw >> 8] = pe_pw[7:0]; \
    end
`define PE_APPLY_IMG_PATCHES(IMG) \
    begin : pe_imgpatch \
      integer pe_pw; \
      `PE_APPLY_IMG_PATCH1(IMG, "PATCH0=%d") \
      `PE_APPLY_IMG_PATCH1(IMG, "PATCH1=%d") \
      `PE_APPLY_IMG_PATCH1(IMG, "PATCH2=%d") \
      `PE_APPLY_IMG_PATCH1(IMG, "PATCH3=%d") \
    end
`endif
