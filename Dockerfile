# SynapticAMS — SerDes pipeline Docker image
# Pinned to linux/amd64 so the pre-built OpenVAF x86_64 binary works both on
# real Linux servers and on Apple Silicon Macs (Docker Desktop runs via Rosetta).
FROM --platform=linux/amd64 ubuntu:22.04

# ── System packages ─────────────────────────────────────────────────────────
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ngspice \
        python3 \
        python3-pip \
        python3-venv \
        curl \
        jq \
        ca-certificates \
        bash \
    && rm -rf /var/lib/apt/lists/*

# ── OpenVAF (Linux x86_64 binary, fetched from GitHub releases) ─────────────
# OpenVAF compiles Verilog-AMS (.va) → OSDI shared libs (.osdi) for ngspice.
# This step is intentionally non-fatal: if GitHub is unreachable or no binary
# is available the pipeline still runs — the validation pass is simply skipped.
RUN bash -c ' \
    echo "==> Attempting OpenVAF install from GitHub releases..." ; \
    DOWNLOAD_URL=$(curl -fsSL --connect-timeout 15 \
        "https://api.github.com/repos/pascalkuthe/OpenVAF/releases" \
        2>/dev/null \
        | python3 -c " \
import sys, json; \
try: \
    releases = json.load(sys.stdin); \
    url = next((a[\"browser_download_url\"] for r in releases for a in r.get(\"assets\",[]) if \"x86_64\" in a[\"name\"] and \"linux\" in a[\"name\"]), None); \
    print(url or \"\") \
except Exception: \
    print(\"\") \
" 2>/dev/null) ; \
    if [ -n "$DOWNLOAD_URL" ]; then \
        echo "==> Downloading: $DOWNLOAD_URL" ; \
        curl -fsSL "$DOWNLOAD_URL" -o /usr/local/bin/openvaf && \
        chmod +x /usr/local/bin/openvaf && \
        openvaf --version && \
        echo "==> OpenVAF installed successfully" || \
        echo "==> [warn] Downloaded binary failed — OSDI compilation skipped" ; \
    else \
        echo "==> [warn] No OpenVAF x86_64 binary found — OSDI compilation skipped" ; \
    fi ; \
    exit 0 \
'

# ── Python dependencies ──────────────────────────────────────────────────────
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# ── Application code ─────────────────────────────────────────────────────────
WORKDIR /app
COPY . /app

ENV PYTHONPATH=/app

# ── Default entrypoint: run the SerDes system-level demo ────────────────────
# Pass ANTHROPIC_API_KEY at runtime:
#   docker run -e ANTHROPIC_API_KEY=sk-ant-... synapticams-demo
# Persist output by mounting a volume:
#   docker run -v /host/output:/app/examples/serdes_system_level_demo/serdes_final_model \
#              -e ANTHROPIC_API_KEY=... synapticams-demo
CMD ["bash", "examples/serdes_system_level_demo/run_system_level_demo.sh"]
