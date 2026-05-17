`timescale 1ns/1ps

module tb_cdr_divider;

    reg clk  = 0;
    reg rst_n = 0;
    always #5 clk = ~clk;   // 100 MHz, period = 10 ns

    wire clk_div4, clk_div8, clk_frac;

    integer_divider  #(.N(4))             u_div4  (.clk_in(clk), .rst_n(rst_n), .clk_out(clk_div4));
    integer_divider  #(.N(8))             u_div8  (.clk_in(clk), .rst_n(rst_n), .clk_out(clk_div8));
    // ÷4.5: frac_word = 0.5 × 2^20 = 524288
    fractional_divider #(.N_INT(4),.ACCUM_W(20)) u_frac (
        .clk_in(clk), .rst_n(rst_n), .frac_word(20'd524288), .clk_out(clk_frac));

    // Transition counters
    integer tr4 = 0, tr8 = 0, trf = 0;
    reg p4 = 0, p8 = 0, pf = 0;
    always @(posedge clk) if (rst_n) begin
        if (clk_div4 !== p4) begin tr4 <= tr4+1; p4 <= clk_div4; end
        if (clk_div8 !== p8) begin tr8 <= tr8+1; p8 <= clk_div8; end
        if (clk_frac !== pf)  begin trf <= trf+1; pf <= clk_frac;  end
    end

    integer errors = 0;

    initial begin
        $dumpfile("tb_cdr_divider.vcd");
        $dumpvars(0, tb_cdr_divider);
        #20 rst_n = 1;
        repeat (4000) @(posedge clk);
        @(negedge clk);

        $display("=== CDR Divider ===");

        // ÷4: 4000 cycles / 4 = 1000 full periods → 2000 transitions
        $display("div4  transitions=%0d (expect ~2000)", tr4);
        if (tr4 < 1990 || tr4 > 2010) begin $display("FAIL div4");  errors=errors+1; end
        else $display("PASS div4");

        // ÷8: 4000/8 = 500 → 1000 transitions
        $display("div8  transitions=%0d (expect ~1000)", tr8);
        if (tr8 < 995 || tr8 > 1005) begin $display("FAIL div8");  errors=errors+1; end
        else $display("PASS div8");

        // ÷4.5: 4000/4.5 ≈ 888.9 → ~1778 transitions
        $display("frac  transitions=%0d (expect ~1778)", trf);
        if (trf < 1760 || trf > 1796) begin $display("FAIL frac");  errors=errors+1; end
        else $display("PASS frac (div-by-4.5)");

        if (errors == 0) $display("ALL PASSED");
        else             $display("%0d FAILED", errors);
        $finish;
    end
endmodule
