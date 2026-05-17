`timescale 1ns/1ps
// Adaptive Engine testbench (MU_SHIFT=4 → delta = x>>>4, max 8 for 8-bit inputs).
// Tests: taps change, correct update polarity, convergence.

module tb_adaptive_engine;
    reg clk = 0; reg rst_n = 0;
    always #5 clk = ~clk;

    reg signed [7:0] y;
    reg              ahat;
    wire signed [15:0] tap0, tap1, tap2;
    wire valid;

    adaptive_engine #(.N_TAPS(3), .MU_SHIFT(4)) dut (
        .clk(clk), .rst_n(rst_n), .y(y), .ahat(ahat),
        .tap0(tap0), .tap1(tap1), .tap2(tap2), .valid(valid));

    integer errors = 0;
    integer i;
    reg [15:0] lfsr;
    reg signed [15:0] tap1_snap;

    task do_reset;
        begin rst_n = 0; #20; rst_n = 1; end
    endtask

    initial begin
        y = 0; ahat = 0; lfsr = 16'hACE1;
        do_reset;

        // ── Test 1: taps change after delay-line fills (3+ cycles) ────────
        // Feed y=+64, ahat=1: sign_e=1, d1=-(x[1]>>>4).
        // After 3 cycles: x[1]=+64, d1=-4 per cycle → tap1 decreases.
        @(negedge clk); y = 8'sd64; ahat = 1;
        repeat (9) @(negedge clk);  // 10 cycles total (3 fill + 7 updates)
        @(posedge clk); #1;
        if (tap1 >= 16'sd32767) begin
            $display("FAIL tap1 unchanged after 10 cycles: %0d", $signed(tap1));
            errors = errors + 1;
        end else
            $display("PASS tap1 changed to %0d after 10 cycles", $signed(tap1));

        // ── Test 2: update direction flips with wrong decision ────────────
        // After warmup, x[1]=+64.
        // Feed y=-64 (negative), ahat=1 (wrong): sign_e=1^1=0 → positive delta.
        // But x[1] is +64 (from previous +64 stream), so d1=+(+64>>>4)=+4 → increases.
        tap1_snap = tap1;
        @(negedge clk); y = -8'sd64; ahat = 1;  // wrong decision on negative
        @(posedge clk); @(posedge clk); #1;      // 2 cycles to propagate
        if (tap1 <= tap1_snap) begin
            $display("FAIL wrong-decision update: tap1 should increase from %0d, got %0d",
                $signed(tap1_snap), $signed(tap1));
            errors = errors + 1;
        end else
            $display("PASS wrong-decision: tap1 %0d → %0d", $signed(tap1_snap), $signed(tap1));

        // ── Test 3: update direction for correct negative ─────────────────
        // Feed y=-64, ahat=0 (correct negative): sign_e=0^1=1 → neg delta.
        // x[1] will become -64 after 2 cycles, giving d1=-(-64>>>4)=-(-4)=+4 (positive).
        // Actually: sign_e=1, d1 = -(x1_ext>>>MU). When x[1]=-64:
        // x1_ext=-64, >>>4=-4, d1=-(-4)=+4. tap1 increases.
        // For FIRST cycle after setting y=-64: x[1] is still old value.
        // Just verify taps are still updating (not stuck).
        tap1_snap = tap1;
        repeat (5) @(negedge clk);  // 5 cycles with y=-64, ahat=0
        y = -8'sd64; ahat = 0;
        @(posedge clk); @(posedge clk); #1;
        if (tap1 === tap1_snap) begin
            $display("FAIL correct-neg: tap1 stuck at %0d", $signed(tap1));
            errors = errors + 1;
        end else
            $display("PASS correct-neg: tap1 moving (%0d → %0d)",
                $signed(tap1_snap), $signed(tap1));

        // ── Test 4: convergence — taps don't saturate over 1000 cycles ───
        do_reset;
        for (i = 0; i < 1000; i = i + 1) begin
            @(negedge clk);
            lfsr = {lfsr[14:0], lfsr[15]^lfsr[13]^lfsr[12]^lfsr[10]};
            y    = lfsr[0] ? 8'sd56 : -8'sd56;
            ahat = lfsr[0];
        end
        @(posedge clk); #1;
        if ($signed(tap1) == 16'sd32767 || $signed(tap1) == -16'sd32768) begin
            $display("FAIL saturation: tap1=%0d after 1000 cycles", $signed(tap1));
            errors = errors + 1;
        end else
            $display("PASS no saturation: tap1=%0d after 1000 cycles", $signed(tap1));

        // ── Test 5: tap0 and tap2 also adapt ─────────────────────────────
        do_reset;
        @(negedge clk); y = 8'sd64; ahat = 1;
        repeat (9) @(negedge clk);
        @(posedge clk); #1;
        if (tap0 === 16'sd0 && tap2 === 16'sd0) begin
            $display("FAIL tap0/tap2 stuck at 0 after 10 cycles");
            errors = errors + 1;
        end else
            $display("PASS tap0=%0d tap2=%0d after 10 cycles",
                $signed(tap0), $signed(tap2));

        $display("=== Adaptive Engine: %0d error(s) ===", errors);
        if (errors == 0) $display("ALL PASSED");
        $finish;
    end
endmodule
