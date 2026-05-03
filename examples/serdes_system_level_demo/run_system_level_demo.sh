#!/bin/bash
export ANTHROPIC_API_KEY=$(cat /home/vrajeshprakhya/ANTHROPIC_KEY)
export PYTHONPATH=/home/vrajeshprakhya/SynapticAMS:$PYTHONPATH
cd /home/vrajeshprakhya/SynapticAMS
python3 /tmp/demo_system_level_refinement.py /tmp/flattened_serdes.cir --output-dir /tmp/serdes_final_model
