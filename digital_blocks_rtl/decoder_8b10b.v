`timescale 1ns/1ps
// 8b/10b Decoder — combinational
// din[9:0] = abcdei|fghj (bit9=a). rd_in: current RD before this symbol.
// Outputs: dout[7:0]=HGFEDCBA, k_out=K flag, disp_err, code_err, rd_out.

module decoder_8b10b (
    input  wire [9:0] din,
    input  wire       rd_in,
    output reg  [7:0] dout,
    output reg        k_out,
    output reg        disp_err,
    output reg        code_err,
    output reg        rd_out
);
    wire [5:0] code6 = din[9:4];
    wire [3:0] code4 = din[3:0];

    // ── 5B6B → EDCBA ─────────────────────────────────────────────────────
    reg [4:0] edcba;
    reg       valid6, is_k28;

    always @(*) begin
        valid6 = 1'b1; is_k28 = 1'b0;
        case (code6)
            6'b110001:           edcba = 5'd3;
            6'b101001:           edcba = 5'd5;
            6'b011001:           edcba = 5'd6;
            6'b100101:           edcba = 5'd9;
            6'b010101:           edcba = 5'd10;
            6'b110100:           edcba = 5'd11;
            6'b001101:           edcba = 5'd12;
            6'b101100:           edcba = 5'd13;
            6'b011100:           edcba = 5'd14;
            6'b100011:           edcba = 5'd17;
            6'b010011:           edcba = 5'd18;
            6'b110010:           edcba = 5'd19;
            6'b001011:           edcba = 5'd20;
            6'b101010:           edcba = 5'd21;
            6'b011010:           edcba = 5'd22;
            6'b100110:           edcba = 5'd25;
            6'b010110:           edcba = 5'd26;
            6'b001110:           edcba = 5'd28;
            6'b100111, 6'b011000: edcba = 5'd0;
            6'b011101, 6'b100010: edcba = 5'd1;
            6'b101101, 6'b010010: edcba = 5'd2;
            6'b110101, 6'b001010: edcba = 5'd4;
            6'b111000, 6'b000111: edcba = 5'd7;
            6'b111001, 6'b000110: edcba = 5'd8;
            6'b010111, 6'b101000: edcba = 5'd15;
            6'b011011, 6'b100100: edcba = 5'd16;
            6'b111010, 6'b000101: edcba = 5'd23;
            6'b110011, 6'b001100: edcba = 5'd24;
            6'b110110, 6'b001001: edcba = 5'd27;
            6'b101110, 6'b010001: edcba = 5'd29;
            6'b011110, 6'b100001: edcba = 5'd30;
            6'b101011, 6'b010100: edcba = 5'd31;
            6'b001111, 6'b110000: begin edcba = 5'd28; is_k28 = 1'b1; end
            default: begin edcba = 5'd0; valid6 = 1'b0; end
        endcase
    end

    // ── Popcount / rd_after6 ──────────────────────────────────────────────
    reg [2:0] ones6, ones4;
    reg       rd_a6;

    always @(*) begin
        ones6 = code6[5]+code6[4]+code6[3]+code6[2]+code6[1]+code6[0];
        ones4 = code4[3]+code4[2]+code4[1]+code4[0];
        rd_a6 = (ones6 > 3) ? 1'b1 : (ones6 < 3) ? 1'b0 : rd_in;
    end

    // ── K flag: is this a K character? ───────────────────────────────────
    // K.28.x: code6 was the comma.  K.23/27/29/30.7: code4 must be K.x.7.
    // K.x.7 code4: 0111 or 1000 (the alt7 codes).
    wire code4_is_k7 = (code4 == 4'b0111 || code4 == 4'b1000);
    wire is_k = is_k28 ||
                ((edcba == 5'd23 || edcba == 5'd27 ||
                  edcba == 5'd29 || edcba == 5'd30) && code4_is_k7);

    // ── 3B4B → HGF ───────────────────────────────────────────────────────
    // Data and K have different 3B4B tables; K y=2/y=5 need rd_a6 to disambiguate.
    reg [2:0] hgf;
    reg       valid4;

    always @(*) begin
        valid4 = 1'b1;
        if (is_k) begin
            // K 3B4B: keyed on {rd_a6, code4}
            case ({rd_a6, code4})
                5'b0_1011: hgf = 3'd0;  // K.x.0 rd-
                5'b1_0100: hgf = 3'd0;  // K.x.0 rd+
                5'b0_0110: hgf = 3'd1;  // K.x.1 rd-
                5'b1_1001: hgf = 3'd1;  // K.x.1 rd+
                5'b0_1010: hgf = 3'd2;  // K.x.2 rd-
                5'b1_0101: hgf = 3'd2;  // K.x.2 rd+
                5'b0_1100: hgf = 3'd3;  // K.x.3 rd-
                5'b1_0011: hgf = 3'd3;  // K.x.3 rd+
                5'b0_0100: hgf = 3'd4;  // K.x.4 rd-
                5'b1_1011: hgf = 3'd4;  // K.x.4 rd+
                5'b0_0101: hgf = 3'd5;  // K.x.5 rd-
                5'b1_1010: hgf = 3'd5;  // K.x.5 rd+
                5'b0_1001: hgf = 3'd6;  // K.x.6 rd-
                5'b1_0110: hgf = 3'd6;  // K.x.6 rd+
                5'b0_0111: hgf = 3'd7;  // K.x.7 rd-
                5'b1_1000: hgf = 3'd7;  // K.x.7 rd+
                default: begin hgf = 3'd0; valid4 = 1'b0; end
            endcase
        end else begin
            // Data 3B4B: code4 unambiguous for D chars
            case (code4)
                4'b1011, 4'b0100: hgf = 3'd0;  // D.x.0
                4'b1001:          hgf = 3'd1;   // D.x.1 neutral
                4'b0101:          hgf = 3'd2;   // D.x.2 neutral
                4'b1100, 4'b0011: hgf = 3'd3;   // D.x.3
                4'b1101, 4'b0010: hgf = 3'd4;   // D.x.4
                4'b1010:          hgf = 3'd5;   // D.x.5 neutral
                4'b0110:          hgf = 3'd6;   // D.x.6 neutral
                4'b1110, 4'b0001: hgf = 3'd7;   // D.x.7 normal
                4'b0111, 4'b1000: hgf = 3'd7;   // D.x.7 alt (D.17/18/20)
                default: begin hgf = 3'd0; valid4 = 1'b0; end
            endcase
        end
    end

    // ── Disparity error ───────────────────────────────────────────────────
    // code6: wrong if 4 ones arrived at RD+ or 2 ones at RD-
    // code4: wrong if 3 ones at rd_a6=RD+ or 1 one at rd_a6=RD-
    always @(*) begin
        disp_err = ((ones6 == 4 && rd_in  == 1'b1) ||
                    (ones6 == 2 && rd_in  == 1'b0) ||
                    (ones4 == 3 && rd_a6  == 1'b1) ||
                    (ones4 == 1 && rd_a6  == 1'b0));
        rd_out   = (ones4 > 2) ? 1'b1 : (ones4 < 2) ? 1'b0 : rd_a6;
        code_err = !valid6 || !valid4;
        k_out    = is_k && !code_err;
        dout     = {hgf, edcba};
    end
endmodule
