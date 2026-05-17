`timescale 1ns/1ps
// 8b/10b Encoder — IBM Widmer-Franaszek / IEEE 802.3
// Combinational. Tables match the verified Python reference implementation.
// rd_in : 0=RD-, 1=RD+.  dout[9:0] = abcdei|fghj (bit9=a, bit0=j)

module encoder_8b10b (
    input  wire [7:0] din,
    input  wire       kin,
    input  wire       rd_in,
    output reg  [9:0] dout,
    output reg        rd_out
);
    wire [4:0] edcba = din[4:0];
    wire [2:0] hgf   = din[7:5];
    wire alt7 = !kin && (hgf == 3'd7) &&
                (edcba == 5'd17 || edcba == 5'd18 || edcba == 5'd20);

    reg [5:0] code6;
    reg [3:0] code4;
    reg       rd_after6;

    always @(*) begin
        // ── 5B6B: code6 = rd_in ? rdplus : rdminus ───────────────────────
        case ({kin, edcba})
            6'd0:            code6 = rd_in ? 6'b011000 : 6'b100111;
            6'd1:            code6 = rd_in ? 6'b100010 : 6'b011101;
            6'd2:            code6 = rd_in ? 6'b010010 : 6'b101101;
            6'd3:            code6 = 6'b110001;
            6'd4:            code6 = rd_in ? 6'b001010 : 6'b110101;
            6'd5:            code6 = 6'b101001;
            6'd6:            code6 = 6'b011001;
            6'd7:            code6 = rd_in ? 6'b000111 : 6'b111000;
            6'd8:            code6 = rd_in ? 6'b000110 : 6'b111001;
            6'd9:            code6 = 6'b100101;
            6'd10:           code6 = 6'b010101;
            6'd11:           code6 = 6'b110100;
            6'd12:           code6 = 6'b001101;
            6'd13:           code6 = 6'b101100;
            6'd14:           code6 = 6'b011100;
            6'd15:           code6 = rd_in ? 6'b101000 : 6'b010111;
            6'd16:           code6 = rd_in ? 6'b100100 : 6'b011011;
            6'd17:           code6 = 6'b100011;
            6'd18:           code6 = 6'b010011;
            6'd19:           code6 = 6'b110010;
            6'd20:           code6 = 6'b001011;
            6'd21:           code6 = 6'b101010;
            6'd22:           code6 = 6'b011010;
            6'd23:           code6 = rd_in ? 6'b000101 : 6'b111010;
            6'd24:           code6 = rd_in ? 6'b001100 : 6'b110011;
            6'd25:           code6 = 6'b100110;
            6'd26:           code6 = 6'b010110;
            6'd27:           code6 = rd_in ? 6'b001001 : 6'b110110;
            6'd28:           code6 = 6'b001110;
            6'd29:           code6 = rd_in ? 6'b010001 : 6'b101110;
            6'd30:           code6 = rd_in ? 6'b100001 : 6'b011110;
            6'd31:           code6 = rd_in ? 6'b010100 : 6'b101011;
            {1'b1,5'd28}:    code6 = rd_in ? 6'b110000 : 6'b001111;
            {1'b1,5'd23}:    code6 = rd_in ? 6'b000101 : 6'b111010;
            {1'b1,5'd27}:    code6 = rd_in ? 6'b001001 : 6'b110110;
            {1'b1,5'd29}:    code6 = rd_in ? 6'b010001 : 6'b101110;
            {1'b1,5'd30}:    code6 = rd_in ? 6'b100001 : 6'b011110;
            default:         code6 = 6'b000000;
        endcase

        // ── rd_after6 via popcount ────────────────────────────────────────
        begin : _rd6
            reg [2:0] n;
            n = code6[5]+code6[4]+code6[3]+code6[2]+code6[1]+code6[0];
            rd_after6 = (n > 3) ? 1'b1 : (n < 3) ? 1'b0 : rd_in;
        end

        // ── 3B4B ─────────────────────────────────────────────────────────
        if (kin) begin
            // K character 3B4B table (differs from data at y=1,2,4,5,6,7)
            case ({rd_after6, hgf})
                4'b0_000: code4 = 4'b1011;  // K.x.0 rd-
                4'b1_000: code4 = 4'b0100;  // K.x.0 rd+
                4'b0_001: code4 = 4'b0110;  // K.x.1 rd- (inverted vs D.x.1)
                4'b1_001: code4 = 4'b1001;  // K.x.1 rd+
                4'b0_010: code4 = 4'b1010;  // K.x.2 rd-
                4'b1_010: code4 = 4'b0101;  // K.x.2 rd+
                4'b0_011: code4 = 4'b1100;  // K.x.3 rd-
                4'b1_011: code4 = 4'b0011;  // K.x.3 rd+
                4'b0_100: code4 = 4'b0100;  // K.x.4 rd- (inverted vs D.x.4)
                4'b1_100: code4 = 4'b1011;  // K.x.4 rd+
                4'b0_101: code4 = 4'b0101;  // K.x.5 rd-
                4'b1_101: code4 = 4'b1010;  // K.x.5 rd+
                4'b0_110: code4 = 4'b1001;  // K.x.6 rd-
                4'b1_110: code4 = 4'b0110;  // K.x.6 rd+
                4'b0_111: code4 = 4'b0111;  // K.x.7 rd-
                4'b1_111: code4 = 4'b1000;  // K.x.7 rd+
                default:  code4 = 4'b0000;
            endcase
        end else if (alt7) begin
            // D.17/18/20 with y=7: use alt code (same as K.x.7)
            code4 = rd_after6 ? 4'b1000 : 4'b0111;
        end else begin
            // Data character 3B4B (neutral entries use same code both ways)
            case ({rd_after6, hgf})
                4'b0_000: code4 = 4'b1011;
                4'b1_000: code4 = 4'b0100;
                4'b0_001: code4 = 4'b1001;  // D.x.1 neutral
                4'b1_001: code4 = 4'b1001;
                4'b0_010: code4 = 4'b0101;  // D.x.2 neutral
                4'b1_010: code4 = 4'b0101;
                4'b0_011: code4 = 4'b1100;
                4'b1_011: code4 = 4'b0011;
                4'b0_100: code4 = 4'b1101;
                4'b1_100: code4 = 4'b0010;
                4'b0_101: code4 = 4'b1010;  // D.x.5 neutral
                4'b1_101: code4 = 4'b1010;
                4'b0_110: code4 = 4'b0110;  // D.x.6 neutral
                4'b1_110: code4 = 4'b0110;
                4'b0_111: code4 = 4'b1110;  // D.x.7 normal rd-
                4'b1_111: code4 = 4'b0001;  // D.x.7 normal rd+
                default:  code4 = 4'b0000;
            endcase
        end

        // ── rd_out via popcount of code4 ──────────────────────────────────
        begin : _rd4
            reg [2:0] n;
            n = code4[3]+code4[2]+code4[1]+code4[0];
            rd_out = (n > 2) ? 1'b1 : (n < 2) ? 1'b0 : rd_after6;
        end

        dout = {code6, code4};
    end
endmodule
