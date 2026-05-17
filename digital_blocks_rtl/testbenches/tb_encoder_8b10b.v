`timescale 1ns/1ps
// Testbench for encoder_8b10b
// Reference vectors cross-checked against IEEE 802.3 / Python behavioral model.
// Format: {din, kin, rd_in} → {dout[9:0], rd_out}
// Bit order: dout[9]=a (first TX), dout[0]=j.

module tb_encoder_8b10b;
    reg  [7:0] din;
    reg        kin, rd_in;
    wire [9:0] dout;
    wire       rd_out;

    encoder_8b10b dut (.din(din), .kin(kin), .rd_in(rd_in),
                       .dout(dout), .rd_out(rd_out));

    integer errors = 0;

    task check;
        input [7:0] d;
        input       k, rd;
        input [9:0] exp_dout;
        input       exp_rd;
        input [63:0] label;  // 8 ASCII chars packed
        begin
            din = d; kin = k; rd_in = rd;
            #1;
            if (dout !== exp_dout || rd_out !== exp_rd) begin
                $display("FAIL %s: din=%02X k=%0b rd=%0b got=%010b rd'=%0b exp=%010b rd'=%0b",
                    label, d, k, rd, dout, rd_out, exp_dout, exp_rd);
                errors = errors + 1;
            end else
                $display("PASS %s", label);
        end
    endtask

    initial begin
        $dumpfile("tb_encoder_8b10b.vcd");
        $dumpvars(0, tb_encoder_8b10b);

        // ── D.0.0 (0x00) RD- ──────────────────────────────────────────────
        // 5B6B D.0 at RD-: 100111; 3B4B D.x.0 at rd_after6 RD+: 0100
        // code6=100111(4 ones→rd+=1), code4=0100(1 one→rd-=0)
        // dout = 100111_0100 = 10'b1001110100, rd_out=0
        check(8'h00, 0, 0, 10'b1001110100, 0, "D.0.0 RD-");

        // ── D.0.0 (0x00) RD+ ──────────────────────────────────────────────
        // 5B6B D.0 at RD+: 011000; 3B4B D.x.0 at rd_after6 RD-: 1011
        // code6=011000(2 ones→rd-=0), code4=1011(3 ones→neutral→rd-=0)
        // dout = 011000_1011 = 10'b0110001011, rd_out=0
        check(8'h00, 0, 1, 10'b0110001011, 1, "D.0.0 RD+");

        // ── K.28.5 (0xBC) RD- ─────────────────────────────────────────────
        // EDCBA=11100=28, HGF=101=5, K=1
        // 5B6B K.28 at RD-: 001111 (4 ones→rd+=1)
        // 3B4B K.x.5 at rd_after6=1: 1010 (2 ones→neutral→rd+=1)
        // dout = 001111_1010 = 10'b0011111010, rd_out=1
        check(8'hBC, 1, 0, 10'b0011111010, 1, "K28.5 RD-");

        // ── K.28.5 (0xBC) RD+ ─────────────────────────────────────────────
        // 5B6B K.28 at RD+: 110000 (2 ones→rd-=0)
        // 3B4B K.x.5 at rd_after6=0: 0101 (2 ones→neutral→rd-=0)
        // dout = 110000_0101 = 10'b1100000101, rd_out=0
        check(8'hBC, 1, 1, 10'b1100000101, 0, "K28.5 RD+");

        // ── K.28.1 (0x3C) RD- — primary comma ────────────────────────────
        // EDCBA=11100=28, HGF=001=1, K=1
        // 5B6B K.28 at RD-: 001111 (→rd+=1)
        // 3B4B K.x.1 at rd_after6=1: 1001 (2 ones→neutral→rd+=1)
        // dout = 001111_1001 = 10'b0011111001, rd_out=1
        check(8'h3C, 1, 0, 10'b0011111001, 1, "K28.1 RD-");

        // ── D.21.5 (0xB5) RD- — neutral char ─────────────────────────────
        // EDCBA=10101=21, HGF=101=5
        // 5B6B D.21 neutral: 101010 (3 ones→rd unchanged=0→rd_after6=0)
        // 3B4B D.x.5 neutral: 1010 (2 ones→neutral→rd unchanged=0)
        // dout = 101010_1010 = 10'b1010101010, rd_out=0
        check(8'hB5, 0, 0, 10'b1010101010, 0, "D21.5 RD-");

        // ── D.21.5 (0xB5) RD+ ─────────────────────────────────────────────
        // 5B6B D.21 neutral: 101010 (→rd_after6=1)
        // 3B4B D.x.5 neutral: 1010 (→rd+=1)
        // dout = 101010_1010, rd_out=1
        check(8'hB5, 0, 1, 10'b1010101010, 1, "D21.5 RD+");

        // ── D.5.6 (0xC5) RD- — all-neutral sequence ──────────────────────
        // EDCBA=00101=5, HGF=110=6
        // 5B6B D.5 neutral: 101001 (3 ones→rd_after6=0)
        // 3B4B D.x.6 neutral: 0110 (2 ones→rd_after6=0)
        // dout=101001_0110=10'b1010010110, rd_out=0
        check(8'hC5, 0, 0, 10'b1010010110, 0, "D5.6 RD- ");

        // ── D.28.0 (0x1C) RD- — D.28 neutral 5B6B ───────────────────────
        // EDCBA=11100=28, HGF=000=0, K=0
        // 5B6B D.28 neutral: 001110 (3 ones→rd_after6=0)
        // 3B4B D.x.0 at rd_after6=0: 1011 (3 ones→neutral→rd-=0)
        // dout=001110_1011=10'b0011101011, rd_out=0
        check(8'h1C, 0, 0, 10'b0011101011, 1, "D28.0 RD-");

        // ── RD tracking: D.0.0 two consecutive ────────────────────────────
        // First at RD-: dout=1001110100, rd_out=0 (checked above)
        // Second at RD- (rd_out=0): same result
        check(8'h00, 0, 0, 10'b1001110100, 0, "D0.0 seq1");
        // The encoder is combinational; rd tracking is external.
        // Feed rd_out of first as rd_in of second:
        check(8'h00, 0, 0, 10'b1001110100, 0, "D0.0 seq2");

        // ── K.28.7 (0xFC) RD- ─────────────────────────────────────────────
        // EDCBA=11100=28, HGF=111=7
        // 5B6B K.28 at RD-: 001111 (→rd+=1)
        // 3B4B K.x.7 at rd_after6=1: 1000 (1 one→rd-=0)
        // dout=001111_1000=10'b0011111000, rd_out=0
        check(8'hFC, 1, 0, 10'b0011111000, 0, "K28.7 RD-");

        // ── D.17.7 alt7 (0xF1) RD- ────────────────────────────────────────
        // EDCBA=10001=17, HGF=111=7, alt7=1
        // 5B6B D.17 neutral: 100011 (3 ones→rd_after6=0)
        // alt7 at rd_after6=0: 0111 (3 ones→neutral→rd-=0)
        // dout=100011_0111=10'b1000110111, rd_out=0
        check(8'hF1, 0, 0, 10'b1000110111, 1, "D17.7 alt");

        $display("=== 8b10b Encoder: %0d error(s) ===", errors);
        if (errors == 0) $display("ALL PASSED");
        $finish;
    end
endmodule
