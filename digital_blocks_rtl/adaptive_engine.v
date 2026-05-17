`timescale 1ns/1ps
// Sign-LMS Adaptive FFE Engine — 3 taps, 16-bit Q1.15 coefficients
//
// Update rule: w[k+1] = w[k] + mu * sign(e[k]) * x[k]
// mu implemented as right-shift: mu = 2^(-MU_SHIFT).
// Inputs: 8-bit signed ADC samples, 1-bit decision.
// Error: hard-decision error = (decision==positive ? +1 : -1) - sample
//   Simplified sign-LMS: sign(e) = decide whether sample is on wrong side of threshold.
//   sign(e[k]) = (ahat[k] ? +1 : -1) * (-sign(y[k]))  ... only when error exists
//   Actually simplest: e = (ahat ? 64 : -64) - y[k], sign(e) = MSB(e).
//   But for Sign-LMS we only need sign: sign(e) = (ahat ? (y<64) : (y>-64))
//   → just: ahat ^ y[7] when |y| < threshold (simplified to always adapt)
//
// For SerDes: sign(e[k]) = ahat[k] XOR (y[k] < 0):
//   if ahat=1 (decided +) but y<0: sign(e)=positive (tap too small)
//   if ahat=0 (decided -) but y>0: sign(e)=negative

module adaptive_engine #(
    parameter N_TAPS   = 3,
    parameter MU_SHIFT = 4   // mu = 2^(-4) = 1/16; for 8-bit inputs max delta=8
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire signed [7:0] y,       // ADC sample
    input  wire              ahat,    // hard decision: 1=positive
    output reg  signed [15:0] tap0,   // Q1.15 coefficients
    output reg  signed [15:0] tap1,
    output reg  signed [15:0] tap2,
    output reg               valid
);
    // Delay line: x[0]=current, x[1]=previous, x[2]=two-prev
    reg signed [7:0] x [0:N_TAPS-1];
    integer k;

    // sign(e) = ahat XOR (y < 0) = ahat XOR y[7]
    wire sign_e = ahat ^ y[7];   // 0=positive error, 1=negative error

    // Signed 16-bit extended samples for update
    wire signed [15:0] x0_ext = {{8{x[0][7]}}, x[0]};
    wire signed [15:0] x1_ext = {{8{x[1][7]}}, x[1]};
    wire signed [15:0] x2_ext = {{8{x[2][7]}}, x[2]};

    // Update delta: sign(e) * x[k] >> MU_SHIFT
    // sign_e=0 → +1, sign_e=1 → -1
    wire signed [15:0] d0 = sign_e ? -(x0_ext >>> MU_SHIFT) : (x0_ext >>> MU_SHIFT);
    wire signed [15:0] d1 = sign_e ? -(x1_ext >>> MU_SHIFT) : (x1_ext >>> MU_SHIFT);
    wire signed [15:0] d2 = sign_e ? -(x2_ext >>> MU_SHIFT) : (x2_ext >>> MU_SHIFT);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            x[0]  <= 8'sd0;  x[1] <= 8'sd0;  x[2] <= 8'sd0;
            // Initialize: center tap = 1.0 in Q1.15 = 32767, others = 0
            tap0  <= 16'sd0;
            tap1  <= 16'sd32767;
            tap2  <= 16'sd0;
            valid <= 1'b0;
        end else begin
            // Shift delay line
            x[2] <= x[1];
            x[1] <= x[0];
            x[0] <= y;
            // Coefficient update
            tap0  <= tap0 + d0;
            tap1  <= tap1 + d1;
            tap2  <= tap2 + d2;
            valid <= 1'b1;
        end
    end
endmodule
