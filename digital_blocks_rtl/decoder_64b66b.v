`timescale 1ns/1ps
// 64b/66b Decoder — IEEE 802.3ae Clause 49
// Self-synchronous descrambler: x[n] = y[n] ^ y[n-39] ^ y[n-58]
// Sync header: 01=data (descramble), 10=control (pass through).
// sync_err asserted when header is neither 01 nor 10.

module decoder_64b66b (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [65:0] din,        // 66-bit: {sync[1:0], payload[63:0]}
    input  wire        din_valid,  // gate: only process when asserted
    output reg  [63:0] dout,
    output reg         is_ctrl,
    output reg         sync_err,
    output reg         valid
);
    wire [1:0]  sync    = din[65:64];
    wire [63:0] payload = din[63:0];

    reg [57:0] sr;  // holds last 58 RECEIVED (scrambled) bits

    integer j;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sr       <= 58'hFF_FFFF_FFFF_FFFF;
            dout     <= 64'b0;
            is_ctrl  <= 1'b0;
            sync_err <= 1'b0;
            valid    <= 1'b0;
        end else if (din_valid) begin
            sync_err <= (sync != 2'b01 && sync != 2'b10);
            if (sync == 2'b10) begin
                // Control block: pass through unmodified, SR not updated
                dout    <= payload;
                is_ctrl <= 1'b1;
                valid   <= 1'b1;
            end else begin
                // Data block: descramble x[n] = y[n] ^ y[n-39] ^ y[n-58]
                // yext[i] for i=0..57 = sr[0..57] = y[-58..y[-1]
                // yext[58+j] = payload[j] = y[j]
                // x[j] = y[j] ^ y[j-39] ^ y[j-58]
                //      = yext[58+j] ^ yext[58+j-39] ^ yext[58+j-58]
                //      = yext[58+j] ^ yext[j+19]    ^ yext[j]
                begin : _descramble
                    reg [121:0] yext;
                    reg [63:0]  x;
                    reg [57:0]  sr_n;
                    yext[57:0] = sr;
                    for (j = 0; j < 64; j = j + 1) begin
                        yext[58+j] = payload[j];
                        x[j]       = yext[58+j] ^ yext[j+19] ^ yext[j];
                    end
                    // Update SR: new sr[i] = payload[63-i]
                    for (j = 0; j < 58; j = j + 1)
                        sr_n[j] = yext[58 + 63 - j];
                    dout    <= x;
                    sr      <= sr_n;
                end
                is_ctrl <= 1'b0;
                valid   <= 1'b1;
            end
        end
    end
endmodule
