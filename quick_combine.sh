#!/bin/bash
# One-liner to combine all .py files

cd ~/circuit_preprocess && \
echo '#!/usr/bin/env python3' > circuit_analyzer.py && \
echo '"""Combined Circuit Analyzer"""' >> circuit_analyzer.py && \
echo 'import networkx as nx' >> circuit_analyzer.py && \
echo 'import re' >> circuit_analyzer.py && \
for f in *.py; do 
    [ "$f" != "circuit_analyzer.py" ] && [ "$f" != "combine_modules.py" ] && \
    echo -e "\n# === FROM: $f ===" >> circuit_analyzer.py && \
    grep -v "^import\|^#!" "$f" >> circuit_analyzer.py
done && \
chmod +x circuit_analyzer.py && \
echo "✓ Created circuit_analyzer.py"
