`timescale 1ns/1ps
// Mueller-Müller Timing Error Detector (Sign-MM variant)
//
// Sign-MM: e[k] = sign(y[k-1])·â[k] − sign(y[k])·â[k-1]
//   where y = ADC samples (8-bit signed), â = hard decisions (1-bit, 0/1).
//   sign(y) = y[7] (MSB) for two's complement: 1→negative, 0→positive.
//   Output error: +1, 0, or -1 encoded as 2-bit signed.
//
// Pipeline: registered output, 1-cycle latency.
// error_out: 2'b01=+1, 2'b00=0, 2'b11=-1 (signed 2-bit)

module mm_ted (
    input  wire        clk,
    input  wire        rst_n,
    input  wire signed [7:0] y,      // ADC sample (Q1.6 signed)
    input  wire        ahat,          // hard decision: 1=positive, 0=negative
    output reg  signed [1:0] error,   // timing error: +1/0/-1
    output reg               valid
);
    reg signed [7:0] y_prev;
    reg              ahat_prev;
    reg              vsr;             // valid shift register

    // sign_y: 1 if y is negative (y[7]=1 in two's complement), -1 if positive
    // Sign-MM using only MSB: sign(y[k]) = y[7] ? -1 : +1
    // e[k] = sign(y[k-1])·â[k] - sign(y[k])·â[k-1]
    // With â ∈ {0,1} mapped to {-1,+1} via (2*ahat-1):
    //   e[k] = sign(y_prev) * (2*ahat-1) - sign(y) * (2*ahat_prev-1)
    // But sign_mm simplification: e[k] = sgn(y[k-1])·d[k] - sgn(y[k])·d[k-1]
    // where d = (ahat ? +1 : -1)
    // Result is in {-2,-1,0,+1,+2}; clamp to {-1,0,+1} for loop filter.

    reg signed [2:0] raw_e;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            y_prev    <= 8'sd0;
            ahat_prev <= 1'b0;
            error     <= 2'sd0;
            vsr       <= 1'b0;
            valid     <= 1'b0;
        end else begin
            // Update delay elements
            y_prev    <= y;
            ahat_prev <= ahat;

            // Compute error (combinational in this cycle for registered output)
            // sign(y) = 1 if y>=0, -1 if y<0
            // sign_y = y[7] ? -1 : +1  → factor out as 1 if ahat matches sign
            // e = sign(y_prev)*(ahat? 1:-1) - sign(y)*(ahat_prev? 1:-1)
            // Represent: sp_prev = y_prev[7] ? -1 : +1, sp = y[7] ? -1 : +1
            // d = ahat ? 1 : -1,  d_prev = ahat_prev ? 1 : -1
            // e = sp_prev*d - sp*d_prev
            // All four products are ±1. Compute as:
            //   term_a = (y_prev[7] == ahat)    ? -1 : +1   (sp_prev XOR d sign)
            //   Actually sp_prev*d = (y_prev is negative)*(-d) + (y_prev is positive)*(d)
            //   = y_prev[7] ? -(2*ahat-1) : (2*ahat-1)
            //   = y_prev[7] ? (ahat ? -1 : +1) : (ahat ? +1 : -1)
            //   = (y_prev[7] ^ ahat) ? -1 : +1
            // So: sp_prev*d = ((y_prev[7] ^ ahat) ? -1 : +1) → sign: y_prev[7]^ahat
            // sp*d_prev = (y[7] ^ ahat_prev) ? -1 : +1
            // e = sp_prev*d - sp*d_prev
            //   where each is ±1
            // e ∈ {-2,-1,0,+1,+2} → {-2,+2} occur, clamp to ±1
            begin : _e
                reg term_a, term_b;  // 1=negative, 0=positive
                term_a = y_prev[7] ^ ahat;       // 1 → sp_prev*d = -1
                term_b = y[7]      ^ ahat_prev;  // 1 → sp*d_prev = -1
                // raw_e = (term_a?-1:+1) - (term_b?-1:+1)
                // = {-1,-1}→0, {-1,+1}→-2, {+1,-1}→+2, {+1,+1}→0
                // sp*d = (XOR)?+1:-1, so raw_e = (ta?+1:-1) - (tb?+1:-1)
                if (term_a == term_b)
                    raw_e = 3'sd0;
                else if (term_a && !term_b)   // +1 - (-1) = +2 → clamp +1
                    raw_e = 3'sd2;
                else                          // -1 - (+1) = -2 → clamp -1
                    raw_e = -3'sd2;
                // Clamp ±2 to ±1
                error <= (raw_e > 0) ? 2'sd1 : (raw_e < 0) ? -2'sd1 : 2'sd0;
            end

            vsr   <= 1'b1;
            valid <= vsr;
        end
    end
endmodule
