#!/bin/bash
export ANTHROPIC_API_KEY=$(cat /home/vrajeshprakhya/ANTHROPIC_KEY)
cd /home/vrajeshprakhya/SynapticAMS
rm -rf /tmp/serdes_system_output
python3 demo_warmstart_validated.py /tmp/serdes_system.cir --output-dir /tmp/serdes_system_output 2>&1 | tail -80
echo ""
echo "===================="
echo "Models generated:"
ls -1 /tmp/serdes_system_output/nonai/*.va 2>/dev/null | wc -l
ls -1 /tmp/serdes_system_output/nonai/*.va 2>/dev/null
