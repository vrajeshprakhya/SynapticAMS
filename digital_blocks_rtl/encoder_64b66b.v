`timescale 1ns/1ps
// 64b/66b Encoder — IEEE 802.3ae Clause 49
// Self-synchronous PRBS-58 scrambler: G(x) = 1 + x^39 + x^58
// Sync header: 2'b01 = data block, 2'b10 = control (unscrambled).
// Clocked: pipeline registers update scrambler state each cycle.
// Interface: present 64-bit payload, get 66-bit code next cycle.
//   For data blocks: payload is scrambled; for control: passed through.
//
// Scrambler equation (parallel, 64-bit):
//   For bit i of output scrambled[63:0]:
//     s[i] = d[i] ^ sr[57-i] ^ sr[18-i]  (where sr is the 58-bit shift register)
//   After processing 64 bits, sr is updated: new sr[57:0] = {s[63:6], old_sr[57:0]}
//   Actually the feedback is:
//     sr_new[i] = s[i]  for i = 0..63 → shift register captures output

module encoder_64b66b (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [63:0] din,       // 64-bit payload
    input  wire        is_ctrl,   // 0=data (scramble), 1=control (pass-through)
    output reg  [65:0] dout,      // 66-bit code: {sync[1:0], payload[63:0]}
    output reg         valid
);
    // 58-bit scrambler shift register
    reg [57:0] sr;

    // Parallel scramble: compute 64 output bits and new SR in one step.
    // SR notation: sr[57] is oldest, sr[0] is newest.
    // PRBS-58: y[n] = x[n] ^ y[n-39] ^ y[n-58]
    //
    // The 58-bit SR holds the last 58 scrambled output bits:
    //   sr[0] = y[n-1], sr[1] = y[n-2], ..., sr[57] = y[n-58]
    // So at time n:
    //   y[n] = x[n] ^ sr[38] ^ sr[57]   (y[n-39]=sr[38], y[n-58]=sr[57])
    //
    // For parallel 64-bit block (bits 0..63):
    //   y[0]  = x[0]  ^ sr[38]    ^ sr[57]
    //   y[1]  = x[1]  ^ sr[37]    ^ sr[56]  ... but y[0] feeds back
    //   y[1]  = x[1]  ^ sr[37]    ^ sr[56]  (sr still not yet shifted by y[0])
    //   Actually for truly parallel we need to expand using y[n-k] for k<64 as function of y's within the block.
    //
    // Simplified approach: since the SR is 58 bits and block is 64 bits,
    // bits y[0..57] depend only on sr[] (no intra-block feedback within first 58),
    // and bits y[58..63] depend on y[0..5] (intra-block feedback).

    integer j;
    reg [63:0] s;   // scrambled output
    reg [57:0] sr_next;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sr    <= 58'hFF_FFFF_FFFF_FFFF;  // any non-zero init
            dout  <= 66'b0;
            valid <= 1'b0;
        end else begin
            if (is_ctrl) begin
                // Control block: sync=10, payload unscrambled
                dout  <= {2'b10, din};
                valid <= 1'b1;
                // SR does NOT advance for control blocks per 802.3ae
            end else begin
                // Data block: compute scrambled bits
                // Build extended array: ext[i] = y[i] for i in range
                // For i in 0..57: y[i] = din[i] ^ sr[57-i-0] ^ sr[57-i-19] -- need careful indexing
                // Using the recurrence: y[i] = x[i] ^ y_prev[i-39] ^ y_prev[i-58]
                // where y_prev[k] for k<0 comes from sr[-k-1]
                //
                // Let y_ext[i] = y[i] for 0<=i<64, sr[-1-i] for i in [-58..-1]
                // sr[-1] = sr[0], sr[-2] = sr[1], ..., sr[-58] = sr[57]
                begin : _scramble
                    reg [121:0] yext;  // y[-58..-1,0..63] = sr[57..0] concat s[0..63]
                    // Initialize lower 58 bits from SR (y[-58] to y[-1])
                    yext[57:0] = sr;   // yext[k] = sr[k] = y[k-58] for k=0..57
                    // Compute s[0..63] = y[58..121]
                    for (j = 0; j < 64; j = j + 1) begin
                        // y[j] = x[j] ^ y[j-39] ^ y[j-58]
                        // j-39 in yext: index = (j-39)+57 = j+18
                        // j-58 in yext: index = (j-58)+57 = j-1... wait
                        // yext[i] represents y[i-57] so y[j] = yext[j+57]? No...
                        //
                        // Redefine: yext[i] for i=0..57 holds sr[0..57] = y[-58..y[-1]
                        //   i.e. yext[0]=y[-58], yext[1]=y[-57],...,yext[57]=y[-1]
                        // yext[58+j] = y[j] for j=0..63
                        // y[j] = x[j] ^ y[j-39] ^ y[j-58]
                        //      = x[j] ^ yext[(j+58)-39] ^ yext[(j+58)-58]
                        //      = x[j] ^ yext[j+19]     ^ yext[j]
                        yext[58+j] = din[j] ^ yext[j+19] ^ yext[j];
                    end
                    s = yext[121:58];
                    // New SR = last 58 scrambled bits = s[63:6] concat sr_new
                    // Actually new SR holds y[6..63] (most recent 58 of the 64 output bits)
                    // sr_next[57] = s[63] (oldest in new window), sr_next[0] = s[6] (newest)
                    // After emitting 64 bits s[0..63], new sr = {s[63], s[62],...,s[6]}
                    //   sr_next[i] = s[63-i] ... no
                    // SR is a shift register: sr[0] = most recent, sr[57] = oldest
                    //   Before: sr[0]=y[-1], sr[57]=y[-58]
                    //   After 64 bits: sr[0]=y[63], sr[1]=y[62],...,sr[57]=y[6]
                    for (j = 0; j < 58; j = j + 1)
                        sr_next[j] = yext[58 + 63 - j];  // sr[0]=s[63], sr[1]=s[62],...
                end
                sr    <= sr_next;
                dout  <= {2'b01, s};
                valid <= 1'b1;
            end
        end
    end
endmodule
