`timescale 1ns/1ps
// MM-TED testbench. Verifies sign-MM error output for known symbol sequences.
// Convention: ahat=1 means +1 decision, ahat=0 means -1.
// error: 2'b01=+1 (late), 2'b11=-1 (early), 2'b00=zero.

module tb_mm_ted;
    reg clk = 0; reg rst_n = 0;
    always #5 clk = ~clk;

    reg signed [7:0] y;
    reg              ahat;
    wire signed [1:0] error;
    wire valid;

    mm_ted dut (.clk(clk), .rst_n(rst_n), .y(y), .ahat(ahat),
                .error(error), .valid(valid));

    integer errors = 0;

    task apply;
        input signed [7:0] sample;
        input              decision;
        begin
            @(negedge clk); y = sample; ahat = decision;
        end
    endtask

    task check_e;
        input signed [1:0] exp;
        input [63:0]        label;
        begin
            @(posedge clk); #1;
            if (error !== exp) begin
                $display("FAIL %s: error=%0d exp=%0d", label, $signed(error), $signed(exp));
                errors = errors + 1;
            end else
                $display("PASS %s (error=%0d)", label, $signed(error));
        end
    endtask

    initial begin
        y = 0; ahat = 0;
        #20 rst_n = 1;

        // Pipeline fill: apply 2 samples before checking
        // Test 1: correct timing — consecutive same-polarity
        // y_prev=+64, ahat=+, y=+64, ahat_prev=+ → e=0
        apply(8'sd64,  1); apply(8'sd64,  1);
        check_e(2'sd0, "correct+");

        // Test 2: correct timing negative
        apply(-8'sd64, 0); apply(-8'sd64, 0);
        check_e(2'sd0, "correct-");

        // Test 3: early sample — y_prev positive, ahat=+ BUT y is transitioning
        // sign(y_prev)=+1, ahat=+1 → term_a=y_prev[7]^ahat=0^1=1 → sp_prev*d=-1
        // sign(y)=+1,  ahat_prev=+ → term_b=y[7]^ahat_prev=0^1=1 → sp*d_prev=-1
        // e = -1 - (-1) = 0 (for same polarity pair, always 0 with sign-MM)
        apply(8'sd64, 1); apply(8'sd64, 1);
        check_e(2'sd0, "same_pol+");

        // Test 4: transition +1→-1: y_prev=+64 ahat=0 (decided -), y=-64 ahat_prev=+1
        // term_a = y_prev[7]^ahat = 0^0 = 0 → sp_prev*d = +1
        // term_b = y[7]^ahat_prev = 1^1 = 0 → sp*d_prev = +1
        // e = +1 - +1 = 0 → no timing error on clean transition
        apply(8'sd64, 0); apply(-8'sd64, 1);
        check_e(2'sd0, "clean_trans");

        // Test 5: late sample — small y before transition
        // y_prev=+8 (small pos), ahat=0 (decided -)
        // y=-64, ahat_prev=+1
        // term_a = 0^0=0 → sp_prev*d = +1
        // term_b = 1^1=0 → sp*d_prev = +1
        // e = 0
        apply(8'sd8, 0); apply(-8'sd64, 1);
        check_e(2'sd0, "small_trans");

        // Test 6: ISI error — y_prev=+64 ahat=+1, y=+64 ahat_prev=0 (wrong decision)
        // This simulates where ahat_prev was a wrong decision
        // term_a = 0^1=1 → sp_prev*d=-1
        // term_b = 0^0=0 → sp*d_prev=+1
        // e = -1 - (+1) = -2 → clamped to -1
        apply(8'sd64, 1); apply(8'sd64, 0);
        check_e(-2'sd1, "isi_early");

        // Test 7: opposite — y_prev=+64 ahat=0, y=-64 ahat_prev=1
        // term_a = 0^0=0 → sp_prev*d=+1
        // term_b = 1^1=0 → sp*d_prev=+1
        // e = +1 - +1 = 0
        apply(8'sd64, 0); apply(-8'sd64, 1);
        check_e(2'sd0, "opposite");

        // Test 8: late clock — y_prev=+8 (crossed zero), ahat_prev=0 (neg decision)
        // y=+64 (strong pos), ahat=+1 (correct pos decision)
        // term_a = y_prev[7]^ahat = 0^1=1 → sp_prev*d=+1
        // term_b = y[7]^ahat_prev = 0^0=0 → sp*d_prev=-1
        // e = +1 - (-1) = +2 → clamped +1
        apply(8'sd8, 0); apply(8'sd64, 1);
        check_e(2'sd1, "isi_late");

        $display("=== MM-TED: %0d error(s) ===", errors);
        if (errors == 0) $display("ALL PASSED");
        $finish;
    end
endmodule
