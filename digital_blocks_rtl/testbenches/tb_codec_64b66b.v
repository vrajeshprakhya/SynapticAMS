`timescale 1ns/1ps
// 64b/66b round-trip testbench.
// Encoder feeds decoder (1-cycle pipeline): check data/ctrl after 2 cycles.

module tb_codec_64b66b;
    reg         clk = 0;
    reg         rst_n = 0;
    always #5 clk = ~clk;

    // Encoder
    reg  [63:0] enc_din;
    reg         enc_ctrl;
    wire [65:0] enc_dout;
    wire        enc_valid;
    encoder_64b66b enc (.clk(clk), .rst_n(rst_n),
                        .din(enc_din), .is_ctrl(enc_ctrl),
                        .dout(enc_dout), .valid(enc_valid));

    // Decoder
    wire [63:0] dec_dout;
    wire        dec_ctrl, dec_sync_err, dec_valid;
    decoder_64b66b dec (.clk(clk), .rst_n(rst_n),
                        .din(enc_dout), .din_valid(enc_valid),
                        .dout(dec_dout), .is_ctrl(dec_ctrl),
                        .sync_err(dec_sync_err), .valid(dec_valid));

    // Pipeline delay: enc captures din at posedge, dec captures enc_dout at next posedge.
    // So dec_dout is valid 2 cycles after enc_din was presented.
    // We queue inputs and compare 2 cycles later.
    reg [63:0] q [0:3];
    reg [3:0]  q_ctrl;
    integer    head = 0, tail = 0;

    integer errors = 0;
    integer i;

    task feed;
        input [63:0] d;
        input        ctrl;
        begin
            @(negedge clk);
            enc_din  = d;
            enc_ctrl = ctrl;
            q[head % 4]    = d;
            q_ctrl[head % 4] = ctrl;
            head = head + 1;
        end
    endtask

    task check_one;
        begin
            @(posedge clk); #1;
            if (dec_valid) begin
                if (dec_dout !== q[tail % 4]) begin
                    $display("FAIL round-trip: exp=%016X got=%016X ctrl=%0b",
                        q[tail % 4], dec_dout, dec_ctrl);
                    errors = errors + 1;
                end
                if (dec_ctrl !== q_ctrl[tail % 4]) begin
                    $display("FAIL ctrl flag: exp=%0b got=%0b", q_ctrl[tail%4], dec_ctrl);
                    errors = errors + 1;
                end
                if (dec_sync_err) begin
                    $display("FAIL sync_err on iteration %0d", tail);
                    errors = errors + 1;
                end
                tail = tail + 1;
            end
        end
    endtask

    initial begin
        enc_din = 64'h0; enc_ctrl = 0;
        #20 rst_n = 1;

        // ── Feed 20 data blocks ──────────────────────────────────────────
        // Pipeline: need to prime with 1 word before reading
        @(negedge clk); enc_din = 64'hDEADBEEF_CAFEBABE; enc_ctrl = 0;
        q[0] = 64'hDEADBEEF_CAFEBABE; q_ctrl[0] = 0; head = 1;
        @(negedge clk); enc_din = 64'h0123456789ABCDEF; enc_ctrl = 0;
        q[1] = 64'h0123456789ABCDEF; q_ctrl[1] = 0; head = 2;

        // After 2 posedges, first output is ready. Read while feeding.
        for (i = 2; i < 20; i = i + 1) begin
            @(posedge clk); #1;
            if (i >= 2 && dec_valid) begin
                if (dec_dout !== q[(i-2) % 4] || dec_ctrl !== 1'b0 || dec_sync_err) begin
                    $display("FAIL data word %0d: exp=%016X got=%016X sync_err=%0b",
                        i-2, q[(i-2)%4], dec_dout, dec_sync_err);
                    errors = errors + 1;
                end
            end
            @(negedge clk);
            enc_din  = $random ^ ({$random, $random} << 32);
            enc_ctrl = 0;
            q[i % 4] = enc_din;
            q_ctrl[i % 4] = 0;
        end

        // Drain last 2
        repeat (2) begin
            @(posedge clk); #1;
            if (dec_valid && dec_sync_err) begin
                $display("FAIL sync_err during drain"); errors=errors+1;
            end
        end

        // ── Control block pass-through ─────────────────────────────────
        @(negedge clk); enc_din = 64'hFFFF_0000_AAAA_5555; enc_ctrl = 1;
        @(posedge clk); @(posedge clk); #1;
        if (dec_dout !== 64'hFFFF_0000_AAAA_5555 || dec_ctrl !== 1'b1) begin
            $display("FAIL ctrl pass-through: got=%016X ctrl=%0b", dec_dout, dec_ctrl);
            errors = errors + 1;
        end else
            $display("PASS ctrl pass-through");

        // ── All-zeros payload ──────────────────────────────────────────
        @(negedge clk); enc_din = 64'h0; enc_ctrl = 0;
        @(posedge clk); @(posedge clk); #1;
        if (dec_dout !== 64'h0 || dec_ctrl || dec_sync_err) begin
            $display("FAIL all-zeros: got=%016X", dec_dout);
            errors = errors + 1;
        end else
            $display("PASS all-zeros data");

        // ── All-ones payload ──────────────────────────────────────────
        @(negedge clk); enc_din = 64'hFFFF_FFFF_FFFF_FFFF; enc_ctrl = 0;
        @(posedge clk); @(posedge clk); #1;
        if (dec_dout !== 64'hFFFF_FFFF_FFFF_FFFF || dec_ctrl || dec_sync_err) begin
            $display("FAIL all-ones: got=%016X", dec_dout);
            errors = errors + 1;
        end else
            $display("PASS all-ones data");

        $display("=== 64b/66b Codec: %0d error(s) ===", errors);
        if (errors == 0) $display("ALL PASSED");
        $finish;
    end
endmodule
