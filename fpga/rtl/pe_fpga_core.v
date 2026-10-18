// pe_fpga_core.v -- the protocol emulator on an FPGA, board-agnostic.
//
// FPGA BRING-UP, PHASE 0 (Wilson): the chip RTL runs UNCHANGED
// (`tt_um_protocol_emulator`) at its design clock, 50 MHz. Around it:
//
//   LOADER   the FPGA stand-in for the real chip's host, the Pico 2: writes the
//            program image (a BRAM ROM) through the chip's REAL host interface
//            -- PROG / PTR_RST / WR on ui_in, the byte on uio -- with the same
//            cycle counts as every testbench (HOST_INTERFACE: prog >= 3 cycles
//            before ptr/wr, ptr >= 3 wide, data held around WR).
//   PADS     the uio bus resolved as a real pad would be: a pin the chip drives
//            (uio_oe) reads back its own value; an undriven pin reads the
//            outside world -- the load byte while loading, then the board UART
//            on uio[3] (P_RX) and idle-high (pull-up) everywhere else.
//   HOST_RX  decodes the chip's 3-pin host stream (uo_out[4] data, [5] strobe,
//            [6] valid): 12-bit frames, LSB first, {marker, kind[2:0], data}.
//            Lane-0 RX payload bytes go to a FIFO and out of the board UART to
//            the PC, RAW -- data byte and stop byte both -- so the PC, not this
//            glue, judges every byte. Status frames light LEDs.
//
//   OW = 1   (1-Wire on J11, Wilson 10-17) -- the default build (OW = 0) is
//            unchanged. DQ = uio[2] (the chip pulls it low or releases it),
//            sensed back on uio[3]; uio[4] is the program's spare clock pin,
//            left unconnected. The PC UART no longer reaches uio[3].
//            * J11 IS RELEASED whenever the chip is loading, held in reset or
//              held for the loader: on the real chip the host's load bytes
//              ride the uio pins, so a peer there would see them. Here they
//              never reach J11, by construction. ISO_MF = 1 (test only) copies
//              the load bytes onto J11 the way the real chip's pads would.
//            * THE FEEDER is the host's byte channel (HOST_INTERFACE "TX
//              nibble channel"), PACED BY A FIXED TIMER, because the chip has
//              no back-pressure pin: the program's symbol period P is exact,
//              a byte is 2 symbols, so byte k is pushed at
//                 t0 + (k - 2) * PER2 + MARGIN       (PER2 = 2P)
//              where t0 is the FIRST DQ FALL THE CHIP SHOWS -- not the reset
//              release, whose distance to the first slot depends on the program
//              (header load + priming). Bytes 0 and 1 are pushed before the
//              chip starts, filling the 2-deep queue. A wrong schedule is
//              reported by the chip itself (underrun / TX-full status bits).
//            * THE POLL READS BEFORE IT DECIDES: after a poll group's 4 bytes,
//              the next byte waits for that group's reply byte; non-zero = done.
//            * 'G' from the PC starts one run (load, prefill, feed). The chip
//              is held in reset until then. Lane-0 bytes are forwarded to the
//              PC until the feed's own replies are all out.
//
// ⛔ THE GLUE CHECKS NOTHING. The judge is the PC: it knows what it sent.
`default_nettype none
module pe_fpga_core #(
    parameter IMG      = "uart_rx_434.hex",   // 256-byte store image
    parameter integer UART_DIV = 434,         // 50 MHz / 115200 = 434.03
    // PC-UART LOADER (Wilson: the FPGA stand-in for the Pico 2's role). A line
    // held low this long is "enter the loader" -- 20 ms at 50 MHz, ten times
    // the 2 ms break the UART-rx test sends as a framing frame.
    parameter integer BRK_CYC  = 1000000,
    // ---- OW = 1 only (see above) ----
    parameter integer OW       = 0,
    parameter FEED             = "",          // 12-bit words: 0xx byte, 1xx poll group
    parameter integer NFEED    = 0,
    parameter integer POLLIDX  = 0,           // rx index of the first poll reply
    parameter integer PER2     = 12800,       // byte time = 2 symbols (P = 6400)
    parameter integer MARGIN   = 6400,        // push offset after the pop it follows
    // TEST KNOBS (simulation must-fires; 0 / -1 in every real build)
    parameter integer BAD_AT   = -1,          // byte index pushed off-schedule ...
    parameter integer BAD_SHIFT = 0,          // ... by this many cycles
    parameter integer LATE     = 0,           // poll decision delayed by this
    parameter integer ISO_MF   = 0            // copy load bytes onto J11
) (
    input  wire       clk,          // 50 MHz
    input  wire       rst_n,        // synchronous to clk, active low
    input  wire       uart_rx,      // from the PC (board USB-UART)
    output wire       uart_tx,      // to the PC
    output wire [5:0] led,
    output wire       running,      // program loaded, chip running
    input  wire       dq_in,        // OW: J11 DQ pad, raw (synchronised here)
    output wire       dq_low        // OW: 1 = pull J11 DQ low
);
  localparam integer P_RX = 3;
  localparam integer P_DQ = 2, P_DQS = 3;

  // ---------------------------------------------------------------- loader
  // Boot loads the BRAM ROM (as before). The PC-UART loader (below) fills
  // `lbuf` and restarts this same sequence from it: ONE load path, two sources.
  reg  [7:0] rom [0:255];
  initial $readmemh(IMG, rom);
  reg  [7:0] lbuf [0:255];
  reg        use_buf;
  reg        relo;          // pulse: restart the load from `lbuf`
  reg        hold;          // level: hold the chip in reset (listening)
  reg        go_ld;         // OW: pulse, 'G' -- restart the load as it stands

  localparam [2:0] L_RST = 3'd0, L_PROG = 3'd1, L_PTR = 3'd2, L_PTR0 = 3'd3,
                   L_BYTE = 3'd4, L_DONE = 3'd5, L_HOLD = 3'd6;
  reg  [2:0]  lst;
  reg  [7:0]  lcnt;
  reg  [8:0]  laddr;
  reg  [2:0]  lph;          // per-byte phase counter
  reg         chip_rst_n, prog, ptr, wr;
  reg  [7:0]  ldata;
  reg         loading;

  always @(posedge clk) begin
    if (!rst_n) begin
      lst <= L_RST; lcnt <= 8'd0; laddr <= 9'd0; lph <= 3'd0;
      chip_rst_n <= 1'b0; prog <= 1'b0; ptr <= 1'b0; wr <= 1'b0;
      ldata <= 8'hFF; loading <= 1'b1; use_buf <= 1'b0;
    end else if (hold) begin
      // listening: chip in reset, the uio bus idle (pull-ups)
      lst <= L_HOLD; chip_rst_n <= 1'b0; prog <= 1'b0; ptr <= 1'b0;
      wr <= 1'b0; ldata <= 8'hFF; loading <= 1'b1;
    end else if (relo || go_ld) begin
      lst <= L_RST; lcnt <= 8'd0; chip_rst_n <= 1'b0;
      if (relo) use_buf <= 1'b1;
      prog <= 1'b0; ptr <= 1'b0; wr <= 1'b0; ldata <= 8'hFF; loading <= 1'b1;
    end else begin
      lcnt <= lcnt + 8'd1;
      case (lst)
        // reset held 16 cycles, then released; PROG raised one cycle later
        L_RST:  if (lcnt == 8'd15) begin chip_rst_n <= 1'b1; end
                else if (lcnt == 8'd17) begin prog <= 1'b1; lst <= L_PROG; lcnt <= 8'd0; end
        // prog >= 3 cycles before ptr; ptr 3 wide; 3 more before the first WR
        L_PROG: if (lcnt == 8'd3) begin ptr <= 1'b1; lst <= L_PTR;  lcnt <= 8'd0; end
        L_PTR:  if (lcnt == 8'd3) begin ptr <= 1'b0; lst <= L_PTR0; lcnt <= 8'd0; end
        L_PTR0: if (lcnt == 8'd3) begin lst <= L_BYTE; lph <= 3'd0; laddr <= 9'd0; end
        // per byte, as the benches: data, 2 cycles, WR 3 cycles, 1 more
        L_BYTE: begin
          lph <= lph + 3'd1;
          case (lph)
            3'd0: ldata <= use_buf ? lbuf[laddr[7:0]] : rom[laddr[7:0]];
            3'd2: wr <= 1'b1;
            3'd5: wr <= 1'b0;
            3'd6: begin
              lph <= 3'd0;
              if (laddr == 9'd255) begin
                lst <= L_DONE; lcnt <= 8'd0;
              end
              laddr <= laddr + 9'd1;
            end
            default: ;
          endcase
        end
        L_DONE: begin
          prog <= 1'b0; ldata <= 8'hFF;
          if (lcnt == 8'd4) loading <= 1'b0;   // byte held >= 4 cycles past WR
        end
        L_HOLD: ;                              // left only by `relo`
        default: lst <= L_RST;
      endcase
    end
  end

  // ----------------------------------------------------------------- chip
  wire [7:0] uo_out, uio_out, uio_oe;
  // ui[7] PROG, [6] WR, [5] PTR in load mode. In run mode (OW only) the
  // feeder's push: [6] PUSH, [4:1] nibble, {[5], [0]} the queue tag (0).
  // With OW = 0, p_wr / p_nib are constant 0: the original {prog, wr, ptr, 0}.
  reg        p_wr;
  reg  [3:0] p_nib;
  wire [7:0] ui_in = {prog, wr | p_wr, ptr, p_nib, 1'b0};
  // J11 DQ pad, 2 flops (the chip synchronises its pins again, as a real pad)
  (* ASYNC_REG = "TRUE" *) reg [1:0] dqs;
  always @(posedge clk) dqs <= {dqs[0], dq_in};
  wire       dq_s = dqs[1];
  // the outside world on each uio pin: the load byte, then UART on P_RX, else
  // a pull-up. OW: DQ (and its sense pin) read J11 instead, and no UART.
  wire [7:0] ext   = loading ? ldata
                   : (OW != 0) ? (8'hFF & ~((8'h01 << P_DQ) | (8'h01 << P_DQS)))
                                 | ({7'd0, dq_s} << P_DQ) | ({7'd0, dq_s} << P_DQS)
                   : (8'hFF & ~(8'h01 << P_RX)) | ({7'd0, uart_rx} << P_RX);
  wire [7:0] uio_in = (uio_oe & uio_out) | (~uio_oe & ext);

  // ⛔ J11 RELEASED UNLESS THE PROGRAM IS RUNNING (Wilson 10-17): loading,
  // chip reset and loader hold all release it. Registered, so it never
  // glitches on the AND of independent flops.
  reg dq_low_q;
  always @(posedge clk)
    dq_low_q <= (OW != 0) && (
        (!loading && !hold && chip_rst_n && uio_oe[P_DQ] && !uio_out[P_DQ])
      // ISO_MF (test only): what the real chip's pads would put on the bus
      || (ISO_MF != 0 && loading && chip_rst_n && !ldata[P_DQ]));
  assign dq_low = dq_low_q;

  tt_um_protocol_emulator chip (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(1'b1), .clk(clk), .rst_n(chip_rst_n)
  );

  // --------------------------------------------------------------- host rx
  wire       ser_d = uo_out[4], ser_s = uo_out[5], ser_v = uo_out[6];
  reg [11:0] fsh;
  reg [3:0]  fcnt;
  reg        v_q;
  reg        f_ok;
  reg [11:0] frame;
  always @(posedge clk) begin
    f_ok <= 1'b0;
    if (!rst_n) begin
      fsh <= 12'd0; fcnt <= 4'd0; v_q <= 1'b0;
    end else begin
      v_q <= ser_v;
      if (ser_v && ser_s) begin
        fsh  <= {ser_d, fsh[11:1]};
        fcnt <= fcnt + 4'd1;
      end
      if (!ser_v && v_q) begin
        if (fcnt == 4'd12) begin f_ok <= 1'b1; frame <= fsh; end
        fcnt <= 4'd0;
      end
    end
  end
  wire       f_marker = frame[11];
  wire [2:0] f_kind   = frame[10:8];
  wire [7:0] f_data   = frame[7:0];

  // ------------------------------------------------- PC-UART loader (glue)
  // A BREAK of BRK_CYC cycles enters the loader: the chip is held in reset and
  // the glue listens for  A5 5A <256 image bytes> <ck>,  where ck makes the
  // sum of the 256 image bytes and ck equal 0 mod 256. Good frame: the load
  // path restarts from `lbuf` (the same PROG/PTR/WR sequence as boot) and the
  // board replies 'K'. Bad header or checksum: reply 'E', keep listening.
  // ⛔ The glue judges only the FRAME (header, checksum) -- whether the chip
  // then runs the program is judged by the PC, as before.
  reg  [15:0] rdiv;
  reg  [3:0]  rbit;
  reg  [7:0]  rsh;
  reg         rbusy, rx_q, rx_v;
  reg  [7:0]  rx_b;
  always @(posedge clk) begin
    rx_v <= 1'b0;
    rx_q <= uart_rx;
    if (!rst_n) begin
      rbusy <= 1'b0; rx_q <= 1'b1;
    end else if (!rbusy) begin
      if (rx_q && !uart_rx) begin           // start-bit fall
        rbusy <= 1'b1; rbit <= 4'd0; rdiv <= UART_DIV + UART_DIV / 2 - 1;
      end
    end else if (rdiv != 16'd0) begin
      rdiv <= rdiv - 16'd1;
    end else if (rbit != 4'd8) begin         // mid-bit sample of a data bit
      rsh <= {uart_rx, rsh[7:1]}; rbit <= rbit + 4'd1; rdiv <= UART_DIV - 1;
    end else begin                           // the stop bit
      rbusy <= 1'b0;
      if (uart_rx) begin rx_v <= 1'b1; rx_b <= rsh; end
    end
  end

  reg  [23:0] lowc;          // saturates at BRK_CYC: `brk` fires once per break
  wire        brk = !uart_rx && lowc == BRK_CYC - 1;
  always @(posedge clk) begin
    if (!rst_n || uart_rx) lowc <= 24'd0;
    else if (lowc != BRK_CYC) lowc <= lowc + 24'd1;
  end

  localparam [2:0] S_RUN = 3'd0, S_H1 = 3'd1, S_H2 = 3'd2, S_DATA = 3'd3,
                   S_CK = 3'd4;
  reg  [2:0]  ls;
  reg  [8:0]  lidx;
  reg  [7:0]  lsum;
  reg         rp_push;
  reg  [7:0]  rp_data;
  reg  [7:0]  nloads;        // PC loads accepted (LED / debug)
  always @(posedge clk) begin
    relo <= 1'b0; rp_push <= 1'b0; go_ld <= 1'b0;
    if (!rst_n) begin
      // OW: the chip waits in reset (J11 released) until the PC says 'G'
      ls <= S_RUN; hold <= (OW != 0); nloads <= 8'd0;
    end else if (brk) begin
      ls <= S_H1; hold <= 1'b1;
    end else if (rx_v) begin
      case (ls)
        // OW: 'G' = one run -- load (BRAM, or the last PC load), prefill, feed
        S_RUN:  if (OW != 0 && rx_b == "G") begin hold <= 1'b0; go_ld <= 1'b1; end
        S_H1:   if (rx_b == 8'hA5) ls <= S_H2;
        S_H2:   if (rx_b == 8'h5A) begin ls <= S_DATA; lidx <= 9'd0; lsum <= 8'd0; end
                else ls <= S_H1;
        S_DATA: begin
          lbuf[lidx[7:0]] <= rx_b; lsum <= lsum + rx_b; lidx <= lidx + 9'd1;
          if (lidx == 9'd255) ls <= S_CK;
        end
        S_CK: begin
          rp_push <= 1'b1;
          if (lsum + rx_b == 8'd0) begin
            rp_data <= "K"; ls <= S_RUN; hold <= 1'b0; relo <= 1'b1;
            nloads <= nloads + 8'd1;
          end else begin
            rp_data <= "E"; ls <= S_H1;
          end
        end
        default: ;
      endcase
    end
  end

  // ------------------------------------------------------- feeder (OW = 1)
  // The host's TX channel, paced by a FIXED TIMER (see the header). Push
  // shape = test/host_feed.vh's hf_push_nib: nibble set, 2 cycles, PUSH high
  // 3 cycles, low 1 -- 6 cycles per nibble, HIGH nibble first, tag 0.
  reg  [11:0] feedm [0:1023];
  generate if (OW != 0) begin : g_feedrom
    initial $readmemh(FEED, feedm, 0, NFEED - 1);
  end endgenerate

  localparam [2:0] F_OFF = 3'd0, F_WAIT = 3'd1, F_PRE = 3'd2, F_ANCH = 3'd3,
                   F_DUE = 3'd4, F_PUSH = 3'd5, F_REPLY = 3'd6;
  reg  [2:0]  fst, fret;       // state, and where F_PUSH returns
  reg  [3:0]  fph;             // push phase, 0..11
  reg  [7:0]  fbyte;           // the byte being pushed
  reg  [10:0] fi;              // feed word index
  reg  [1:0]  gi;              // byte within a poll group
  reg         in_poll;
  reg  [31:0] now, due, tgt;   // free-running cycle count; schedule
  reg  [15:0] kb;              // bytes pushed since the load (byte index k)
  reg  [15:0] nfed;            // bytes pushed while the feed lasted
  reg         feed_done;
  reg  [15:0] rx_cnt;          // lane-0 payload bytes received since the load
  reg  [15:0] pg;              // poll groups pushed
  reg  [7:0]  reply;
  reg  [31:0] late_c;
  reg         dq_q;
  wire        pay = f_ok && !f_marker && f_kind == 3'd0 && !loading;

  // the next byte to push, and what follows it
  wire [11:0] fw = feedm[fi + gi];
  always @(posedge clk) begin
    now  <= now + 32'd1;
    dq_q <= dq_low_q;
    if (!rst_n || go_ld || relo || OW == 0) begin
      fst <= (OW != 0) ? F_WAIT : F_OFF; fph <= 4'd0; p_wr <= 1'b0;
      p_nib <= 4'd0; fi <= 11'd0; gi <= 2'd0; in_poll <= 1'b0; kb <= 16'd0;
      nfed <= 16'd0; feed_done <= 1'b0; rx_cnt <= 16'd0; pg <= 16'd0;
      if (!rst_n) now <= 32'd0;
    end else begin
      if (pay) rx_cnt <= rx_cnt + 16'd1;
      case (fst)
        F_OFF: ;
        // CDC3: PROG low >= 3 cycles before the first PUSH edge
        F_WAIT: if (!loading && !hold) begin fst <= F_PRE; late_c <= 32'd3; end
        F_PRE: if (late_c != 0) late_c <= late_c - 32'd1;
               else if (kb == 16'd2) fst <= F_ANCH;
               else begin fbyte <= fw[7:0]; fret <= F_PRE; fst <= F_PUSH; end
        // t0 = the FIRST DQ FALL the chip shows
        F_ANCH: if (dq_low_q && !dq_q) begin
                  due <= now + MARGIN; fst <= F_DUE;
                end
        F_DUE: begin
          tgt = (kb == BAD_AT) ? due + BAD_SHIFT : due;
          if ($signed(now - tgt) >= 0) begin
            fbyte <= feed_done ? 8'hFF : fw[7:0];
            fret  <= F_DUE;
            fst   <= F_PUSH;
          end
        end
        // ⭐ THE POLL READS BEFORE IT DECIDES: the reply for group pg is rx
        // index POLLIDX + pg (one reply per 8 symbols = per 4 pushed bytes)
        F_REPLY: begin
          if (pay && rx_cnt == POLLIDX + pg) begin reply <= f_data; late_c <= LATE; end
          if (rx_cnt > POLLIDX + pg && !pay) begin
            if (late_c != 0) late_c <= late_c - 32'd1;
            else begin
              pg <= pg + 16'd1;
              if (reply != 8'h00) begin in_poll <= 1'b0; fi <= fi + 11'd4; end
              fst <= F_DUE;
            end
          end
        end
        F_PUSH: begin
          fph <= fph + 4'd1;
          case (fph)
            4'd0:  p_nib <= fbyte[7:4];
            4'd2:  p_wr  <= 1'b1;
            4'd5:  p_wr  <= 1'b0;
            4'd6:  p_nib <= fbyte[3:0];
            4'd8:  p_wr  <= 1'b1;
            4'd11: begin
              p_wr <= 1'b0; fph <= 4'd0; kb <= kb + 16'd1;
              if (fret == F_DUE) due <= due + PER2;
              fst <= fret;
              if (!feed_done) begin
                nfed <= nfed + 16'd1;
                // advance through the feed: a poll group is 4 words, pushed
                // whole, then the reply decides (repeat it, or move on)
                if (fw[8] || in_poll) begin
                  in_poll <= 1'b1;
                  if (gi == 2'd3) begin gi <= 2'd0; fst <= F_REPLY; end
                  else gi <= gi + 2'd1;
                end else if (fi + 11'd1 >= NFEED) feed_done <= 1'b1;
                else fi <= fi + 11'd1;
              end
            end
            default: ;
          endcase
        end
        default: fst <= F_OFF;
      endcase
    end
  end
  // forward the chip's bytes to the PC until the feed's own replies are out:
  // one reply per 4 bytes fed (every block is a multiple of 8 symbols)
  wire fwd = (OW == 0) || !feed_done || (rx_cnt < (nfed >> 2));

  // ------------------------------------------------------------- the FIFO
  reg [7:0]  fifo [0:1023];
  reg [9:0]  wp, rp;
  reg        ovf;
  wire       f_chip  = f_ok && !f_marker && f_kind == 3'd0 && !loading && fwd;
  // the loader's reply shares the FIFO; it never coincides with a chip byte
  // (the chip is in reset while the loader listens)
  wire       f_push  = f_chip || rp_push;
  wire [7:0] f_in    = rp_push ? rp_data : f_data;
  wire       f_empty = (wp == rp);
  wire       f_full  = ((wp + 10'd1) == rp);
  reg  [7:0] f_q;
  reg        tx_go;
  wire       tx_busy;
  always @(posedge clk) begin
    tx_go <= 1'b0;
    if (!rst_n) begin
      wp <= 10'd0; rp <= 10'd0; ovf <= 1'b0;
    end else begin
      if (f_push) begin
        if (f_full) ovf <= 1'b1;
        else begin fifo[wp] <= f_in; wp <= wp + 10'd1; end
      end
      if (!f_empty && !tx_busy && !tx_go) begin
        f_q <= fifo[rp]; rp <= rp + 10'd1; tx_go <= 1'b1;
      end
    end
  end

  // ------------------------------------------------------------- UART tx
  reg [9:0]  tsh;
  reg [3:0]  tbits;
  reg [15:0] tdiv;
  reg        tx_out;
  reg        tx_arm;
  assign tx_busy = (tbits != 4'd0) || tx_arm;
  assign uart_tx = tx_out;
  always @(posedge clk) begin
    if (!rst_n) begin
      tbits <= 4'd0; tdiv <= 16'd0; tx_out <= 1'b1; tx_arm <= 1'b0;
    end else begin
      if (tx_go) tx_arm <= 1'b1;
      if (tx_arm && tbits == 4'd0) begin            // load {stop, data, start}
        tsh <= {1'b1, f_q, 1'b0}; tbits <= 4'd10; tdiv <= 16'd0; tx_arm <= 1'b0;
      end else if (tbits != 4'd0) begin
        if (tdiv == 16'd0) begin
          tx_out <= tsh[0]; tsh <= {1'b1, tsh[9:1]};
        end
        if (tdiv == UART_DIV - 1) begin
          tdiv <= 16'd0; tbits <= tbits - 4'd1;
        end else tdiv <= tdiv + 16'd1;
      end
    end
  end

  // ----------------------------------------------------------------- LEDs
  reg [24:0] hb;
  reg        st_err, rx_tog;
  reg  [7:0] st_or;         // every status bit seen since the load (the host's view)
  always @(posedge clk) begin
    if (!rst_n) begin hb <= 25'd0; st_err <= 1'b0; rx_tog <= 1'b0; st_or <= 8'd0; end
    else begin
      hb <= hb + 25'd1;
      if (OW != 0 && (go_ld || relo)) begin st_err <= 1'b0; st_or <= 8'd0; end
      if (f_ok && f_marker) st_or <= st_or | f_data;
      // status frame (marker 1): any error bit (7..1; bit 0 is "alive")
      if (f_ok && f_marker && |f_data[7:1]) st_err <= 1'b1;
      if (f_push) rx_tog <= ~rx_tog;
    end
  end
  assign running = !loading;
  assign led = {rx_tog, ovf, st_err, !loading, 1'b1, hb[24] & !loading};
endmodule
`default_nettype wire
