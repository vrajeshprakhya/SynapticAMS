`timescale 1ns/1ps
// TX Feed-Forward Equalizer — 3-tap signed FIR pre-emphasis filter
//
// Fixed-point format: Q1.6 signed 8-bit (LSB = 1/64; range ≈ -2.0 to +1.98)
// Pipeline: 2 clock cycles
//   Stage 1: delay line update + multiply
//   Stage 2: accumulate and truncate → dout
//
// Tap order: c_pre=c[-1] (oldest), c_cur=c[0] (main), c_post=c[+1] (newest)
// y[n] = c_pre·x[n-2] + c_cur·x[n-1] + c_post·x[n]  (causal; 2-cycle latency)
//
// PCIe Gen3/4 coefficients (multiply float by 64 for Q1.6):
//   P0 (pass-through)  : c_pre=0,   c_cur=64, c_post=0
//   P1 (light de-emph) : c_pre=0,   c_cur=51, c_post=-13
//   P5 (3-tap)         : c_pre=-11, c_cur=43, c_post=-11
//   P8 (max 3-tap)     : c_pre=-16, c_cur=32, c_post=-16

module tx_ffe (
    input  wire        clk,
    input  wire        rst_n,
    input  wire signed [7:0] din,       // Q1.6 signed input symbol
    input  wire signed [7:0] c_pre,     // precursor coefficient (c[-1])
    input  wire signed [7:0] c_cur,     // cursor coefficient    (c[0])
    input  wire signed [7:0] c_post,    // postcursor coefficient(c[+1])
    output reg  signed [7:0] dout,      // Q1.6 signed output
    output reg               valid      // high after 2-cycle pipeline fill
);
    // Delay line
    reg signed [7:0]  x1, x2;           // x1=x[n-1], x2=x[n-2]

    // Stage-1 registers: products (16-bit signed)
    reg signed [15:0] p_pre, p_cur, p_post;

    // Valid shift register: asserts valid after 2 cycles
    reg vsr;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            x1     <= 8'sd0;  x2     <= 8'sd0;
            p_pre  <= 16'sd0; p_cur  <= 16'sd0; p_post <= 16'sd0;
            dout   <= 8'sd0;
            vsr    <= 1'b0;   valid  <= 1'b0;
        end else begin
            // ── Stage 1: delay line + multiply ─────────────────────────
            x1    <= din;
            x2    <= x1;
            p_pre  <= c_pre  * x1;    // x[n-1] (1-cycle old input)
            p_cur  <= c_cur  * x2;    // x[n-2] (2-cycle old input)
            p_post <= c_post * din;   // x[n]   (current input = postcursor)
            // ── Stage 2: accumulate + truncate ─────────────────────────
            // Sum three 16-bit Q2.12 products → 18-bit result
            // Truncate to 8-bit Q1.6: take bits [13:6] (right-shift by 6)
            begin : _acc
                reg signed [17:0] sum;
                sum  = $signed({{2{p_pre[15]}},  p_pre})  +
                       $signed({{2{p_cur[15]}},  p_cur})  +
                       $signed({{2{p_post[15]}}, p_post});
                dout <= sum[13:6];
            end
            // Valid pipeline
            vsr   <= 1'b1;
            valid <= vsr;
        end
    end
endmodule
