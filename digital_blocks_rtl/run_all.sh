#!/bin/bash
# Run all RTL testbenches with iVerilog. Exit 1 if any test fails.
set -euo pipefail

RTL="$(cd "$(dirname "$0")" && pwd)"
TB="$RTL/testbenches"
TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

PASS=0; FAIL=0

run_tb() {
    local name="$1"; shift
    local srcs=("$@")
    local out="$TMP/${name}.out"
    if iverilog -g2012 -o "$out" "${srcs[@]}" 2>/dev/null && \
       vvp "$out" 2>/dev/null | grep -q "ALL PASSED"; then
        echo "PASS  $name"
        ((PASS++)) || true
    else
        echo "FAIL  $name"
        vvp "$out" 2>/dev/null | grep -E "FAIL|error" || true
        ((FAIL++)) || true
    fi
}

run_tb cdr_divider \
    "$RTL/cdr_divider.v" \
    "$TB/tb_cdr_divider.v"

run_tb tx_ffe \
    "$RTL/tx_ffe.v" \
    "$TB/tb_tx_ffe.v"

run_tb encoder_8b10b \
    "$RTL/encoder_8b10b.v" \
    "$TB/tb_encoder_8b10b.v"

run_tb codec_8b10b \
    "$RTL/encoder_8b10b.v" \
    "$RTL/decoder_8b10b.v" \
    "$TB/tb_codec_8b10b.v"

run_tb codec_64b66b \
    "$RTL/encoder_64b66b.v" \
    "$RTL/decoder_64b66b.v" \
    "$TB/tb_codec_64b66b.v"

run_tb mm_ted \
    "$RTL/mm_ted.v" \
    "$TB/tb_mm_ted.v"

run_tb adaptive_engine \
    "$RTL/adaptive_engine.v" \
    "$TB/tb_adaptive_engine.v"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
