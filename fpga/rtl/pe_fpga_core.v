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
// ⛔ THE GLUE CHECKS NOTHING. The judge is the PC: it knows what it sent.
`default_nettype none
module pe_fpga_core #(
    parameter IMG      = "uart_rx_434.hex",   // 256-byte store image
    parameter integer UART_DIV = 434,         // 50 MHz / 115200 = 434.03
    // PC-UART LOADER (Wilson: the FPGA stand-in for the Pico 2's role). A line
    // held low this long is "enter the loader" -- 20 ms at 50 MHz, ten times
    // the 2 ms break the UART-rx test sends as a framing frame.
    parameter integer BRK_CYC  = 1000000
) (
    input  wire       clk,          // 50 MHz
    input  wire       rst_n,        // synchronous to clk, active low
    input  wire       uart_rx,      // from the PC (board USB-UART)
    output wire       uart_tx,      // to the PC
    output wire [5:0] led,
    output wire       running       // program loaded, chip running
);
  localparam integer P_RX = 3;

  // ---------------------------------------------------------------- loader
  // Boot loads the BRAM ROM (as before). The PC-UART loader (below) fills
  // `lbuf` and restarts this same sequence from it: ONE load path, two sources.
  reg  [7:0] rom [0:255];
  initial $readmemh(IMG, rom);
  reg  [7:0] lbuf [0:255];
  reg        use_buf;
  reg        relo;          // pulse: restart the load from `lbuf`
  reg        hold;          // level: hold the chip in reset (listening)

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
    end else if (relo) begin
      lst <= L_RST; lcnt <= 8'd0; use_buf <= 1'b1; chip_rst_n <= 1'b0;
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
  wire [7:0] ui_in = {prog, wr, ptr, 5'b00000};      // ui[7] PROG, [6] WR, [5] PTR
  // the outside world on each uio pin: the load byte, then UART on P_RX, else
  // a pull-up
  wire [7:0] ext   = loading ? ldata
                             : (8'hFF & ~(8'h01 << P_RX)) | ({7'd0, uart_rx} << P_RX);
  wire [7:0] uio_in = (uio_oe & uio_out) | (~uio_oe & ext);

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
    relo <= 1'b0; rp_push <= 1'b0;
    if (!rst_n) begin
      ls <= S_RUN; hold <= 1'b0; nloads <= 8'd0;
    end else if (brk) begin
      ls <= S_H1; hold <= 1'b1;
    end else if (rx_v) begin
      case (ls)
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

  // ------------------------------------------------------------- the FIFO
  reg [7:0]  fifo [0:1023];
  reg [9:0]  wp, rp;
  reg        ovf;
  wire       f_chip  = f_ok && !f_marker && f_kind == 3'd0 && !loading;
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
  always @(posedge clk) begin
    if (!rst_n) begin hb <= 25'd0; st_err <= 1'b0; rx_tog <= 1'b0; end
    else begin
      hb <= hb + 25'd1;
      // status frame (marker 1): any error bit (7..1; bit 0 is "alive")
      if (f_ok && f_marker && |f_data[7:1]) st_err <= 1'b1;
      if (f_push) rx_tog <= ~rx_tog;
    end
  end
  assign running = !loading;
  assign led = {rx_tog, ovf, st_err, !loading, 1'b1, hb[24] & !loading};
endmodule
`default_nettype wire
