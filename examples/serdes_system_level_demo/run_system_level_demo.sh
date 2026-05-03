#!/usr/bin/env bash
# run_system_level_demo.sh
# Run the SerDes system-level model extraction + AI refinement pipeline.
# Works on Linux (Docker) or macOS (Python steps only; OpenVAF needs Linux).
#
# Usage:
#   ./run_system_level_demo.sh [output_dir]
#
# ANTHROPIC_API_KEY must be set in the environment:
#   export ANTHROPIC_API_KEY=sk-ant-...
#   Docker: docker run -e ANTHROPIC_API_KEY=... synapticams-demo

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "[warn] ANTHROPIC_API_KEY not set — AI refinement pass will be skipped"
fi

export PYTHONPATH="$REPO_DIR:${PYTHONPATH:-}"

OUTPUT_DIR="${1:-$SCRIPT_DIR/serdes_final_model}"

echo "==================================================================="
echo "  SynapticAMS — SerDes System-Level Demo"
echo "==================================================================="
echo "  Repo:    $REPO_DIR"
echo "  Input:   $SCRIPT_DIR/flattened_serdes.cir"
echo "  Output:  $OUTPUT_DIR"
echo "==================================================================="

python3 "$SCRIPT_DIR/demo_system_level_refinement.py" \
    "$SCRIPT_DIR/flattened_serdes.cir" \
    --output-dir "$OUTPUT_DIR"
