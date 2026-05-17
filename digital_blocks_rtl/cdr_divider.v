`timescale 1ns/1ps
// CDR Frequency Divider
// Integer divide-by-N with 50% duty cycle (even N).
// Fractional divide-by-(N+F) using first-order sigma-delta dual-modulus prescaler.
// CDRDivider wraps both and selects based on whether frac_word == 0.

// --------------------------------------------------------------------------
// Integer Divider — divides clk_in by N, 50% duty cycle for even N
// --------------------------------------------------------------------------
module integer_divider #(
    parameter N = 4  // divide ratio >= 2
) (
    input  wire clk_in,
    input  wire rst_n,
    output reg  clk_out
);
    localparam CNT_W = $clog2(N);
    reg [CNT_W-1:0] cnt;

    always @(posedge clk_in or negedge rst_n) begin
        if (!rst_n) begin
            cnt     <= 0;
            clk_out <= 0;
        end else begin
            if (cnt == N - 1)
                cnt <= 0;
            else
                cnt <= cnt + 1;
            // Toggle at half-period boundaries for 50% duty cycle
            if (cnt == (N/2) - 1)
                clk_out <= 1'b1;
            if (cnt == N - 1)
                clk_out <= 1'b0;
        end
    end
endmodule

// --------------------------------------------------------------------------
// Fractional Divider — effective ratio = N_INT + FRAC_WORD/2^ACCUM_W
// Uses a first-order sigma-delta accumulator to alternate between ÷N and ÷N+1.
// --------------------------------------------------------------------------
module fractional_divider #(
    parameter N_INT   = 4,           // integer part of divide ratio
    parameter ACCUM_W = 20           // accumulator width; resolution = 1/2^ACCUM_W
) (
    input  wire              clk_in,
    input  wire              rst_n,
    input  wire [ACCUM_W-1:0] frac_word, // fractional part: frac * 2^ACCUM_W
    output reg               clk_out
);
    // Sigma-delta accumulator
    reg [ACCUM_W:0]   accum;
    wire              carry = accum[ACCUM_W]; // overflow → use N+1 this cycle
    reg               modsel;                 // 0 = ÷N, 1 = ÷N+1

    // Prescaler counter (counts up to N or N+1)
    localparam CNT_W = $clog2(N_INT + 2);
    reg [CNT_W-1:0]   cnt;
    reg [CNT_W-1:0]   modulus;

    always @(posedge clk_in or negedge rst_n) begin
        if (!rst_n) begin
            accum   <= 0;
            modsel  <= 0;
            cnt     <= 0;
            modulus <= N_INT[CNT_W-1:0];
            clk_out <= 0;
        end else begin
            if (cnt == modulus - 1) begin
                cnt <= 0;
                // Sigma-delta: update accumulator and pick next modulus
                accum   <= {1'b0, accum[ACCUM_W-1:0]} + {1'b0, frac_word};
                modulus <= carry ? N_INT[CNT_W-1:0] + 1 : N_INT[CNT_W-1:0];
            end else begin
                cnt <= cnt + 1;
            end

            // Toggle output at half-period
            if (cnt == modulus/2 - 1)
                clk_out <= 1'b1;
            if (cnt == modulus - 1)
                clk_out <= 1'b0;
        end
    end
endmodule

// --------------------------------------------------------------------------
// CDR Divider — top-level wrapper
// ratio_int  : integer divide ratio (the N part)
// frac_word  : fractional word = frac * 2^20  (0 = pure integer)
// --------------------------------------------------------------------------
module cdr_divider #(
    parameter N_INT   = 4,
    parameter ACCUM_W = 20
) (
    input  wire              clk_in,
    input  wire              rst_n,
    input  wire [ACCUM_W-1:0] frac_word,
    output wire              clk_out
);
    wire int_out, frac_out;
    wire use_frac = (frac_word != 0);

    integer_divider #(.N(N_INT)) u_int (
        .clk_in  (clk_in),
        .rst_n   (rst_n),
        .clk_out (int_out)
    );

    fractional_divider #(.N_INT(N_INT), .ACCUM_W(ACCUM_W)) u_frac (
        .clk_in   (clk_in),
        .rst_n    (rst_n),
        .frac_word(frac_word),
        .clk_out  (frac_out)
    );

    assign clk_out = use_frac ? frac_out : int_out;
endmodule
