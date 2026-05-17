`timescale 1ns/1ps

module tb_tx_ffe;
    reg clk   = 0;
    reg rst_n = 0;
    always #5 clk = ~clk;

    reg  signed [7:0] din;
    reg  signed [7:0] c_pre, c_cur, c_post;
    wire signed [7:0] dout;
    wire              valid;

    tx_ffe dut (.clk(clk), .rst_n(rst_n), .din(din),
                .c_pre(c_pre), .c_cur(c_cur), .c_post(c_post),
                .dout(dout), .valid(valid));

    integer errors = 0;
    integer i;
    // Steady-state helper: apply N identical samples then read output
    // After 5 identical samples the 2-stage pipeline is fully filled.
    task steady;
        input signed [7:0] sample;
        integer k;
        begin
            for (k = 0; k < 5; k = k + 1) begin
                @(negedge clk); din = sample;
            end
            @(posedge clk); #1;
        end
    endtask

    initial begin
        $dumpfile("tb_tx_ffe.vcd");
        $dumpvars(0, tb_tx_ffe);
        din = 8'sd0; c_pre = 8'sd0; c_cur = 8'sd0; c_post = 8'sd0;
        #20 rst_n = 1;

        // ── Test 1: P0 pass-through — constant +1 input ─────────────────
        // c_cur = 64 (= +1.0 in Q1.6), others = 0
        // Steady-state: dout = c_cur * x[n-1] / 64 → in Q1.6: dout = 64
        c_pre = 8'sd0; c_cur = 8'sd64; c_post = 8'sd0;
        steady(8'sd64);   // feed +1.0 = 64 until settled
        if (dout !== 8'sd64) begin
            $display("FAIL P0 pass-through: got %0d, expected 64", $signed(dout));
            errors = errors + 1;
        end else $display("PASS P0 pass-through (dout=%0d)", $signed(dout));

        // ── Test 2: P0 pass-through — constant -1 input ─────────────────
        steady(-8'sd64);
        if (dout !== -8'sd64) begin
            $display("FAIL P0 neg pass-through: got %0d, expected -64", $signed(dout));
            errors = errors + 1;
        end else $display("PASS P0 neg pass-through (dout=%0d)", $signed(dout));

        // ── Test 3: De-emphasis P1 — run of +1s ──────────────────────────
        // c_cur=51 (~0.8), c_post=-13 (~-0.2); all +1 input
        // Steady-state cursor path: c_cur * x[n-1] = 51*64 = 3264
        // Postcursor path:          c_post * x[n]  = -13*64 = -832
        // Sum = 2432, dout = 2432 >> 6 = 38
        c_pre = 8'sd0; c_cur = 8'sd51; c_post = -8'sd13;
        steady(8'sd64);
        if (dout !== 8'sd38) begin
            $display("FAIL P1 de-emph: got %0d, expected 38", $signed(dout));
            errors = errors + 1;
        end else $display("PASS P1 de-emphasis steady-state (dout=%0d)", $signed(dout));

        // ── Test 4: Inverting cursor ──────────────────────────────────────
        c_pre = 8'sd0; c_cur = -8'sd64; c_post = 8'sd0;
        steady(8'sd64);
        if (dout !== -8'sd64) begin
            $display("FAIL negate: got %0d, expected -64", $signed(dout));
            errors = errors + 1;
        end else $display("PASS negate cursor (dout=%0d)", $signed(dout));

        // ── Test 5: Valid signal asserts after 2 cycles ───────────────────
        rst_n = 0; #20; rst_n = 1;
        c_pre = 8'sd0; c_cur = 8'sd64; c_post = 8'sd0;
        @(negedge clk); din = 8'sd64;
        @(posedge clk); #1;  // after 1 cycle: valid should still be 0
        if (valid !== 1'b0) begin
            $display("FAIL valid too early (cycle 1): valid=%0b", valid);
            errors = errors + 1;
        end
        @(negedge clk); din = 8'sd64;
        @(posedge clk); #1;  // after 2 cycles: valid should be 1
        if (valid !== 1'b1) begin
            $display("FAIL valid not asserted after 2 cycles: valid=%0b", valid);
            errors = errors + 1;
        end else $display("PASS valid asserted after 2 cycles");

        // ── Test 6: 3-tap pre+post cursor cancellation ───────────────────
        // P8: c_pre=-16, c_cur=32, c_post=-16 → steady +1: (-16+32-16)*64 = 0
        c_pre = -8'sd16; c_cur = 8'sd32; c_post = -8'sd16;
        steady(8'sd64);
        if (dout !== 8'sd0) begin
            $display("FAIL P8 cancel: got %0d, expected 0", $signed(dout));
            errors = errors + 1;
        end else $display("PASS P8 tap cancellation (dout=%0d)", $signed(dout));

        $display("=== TX FFE: %0d error(s) ===", errors);
        if (errors == 0) $display("ALL PASSED");
        $finish;
    end
endmodule
