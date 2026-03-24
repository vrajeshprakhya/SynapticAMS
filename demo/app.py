"""
SynapticAMS Demo UI
===================
Streamlit app for VP / investor demos.

NOTE: This is a demo-only UI. Production usage is via the CLI:
    python pipeline.py <netlist.cir>
    python pipeline.py --vco <vco.cir>

Run (free, using local Ollama):
    ollama serve
    streamlit run demo/app.py

Run (with Claude):
    export ANTHROPIC_API_KEY=sk-ant-...
    streamlit run demo/app.py
"""

import sys
import os
import time
import tempfile
from pathlib import Path

import numpy as np
import streamlit as st
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import run_pipeline, parse_netlist, vco_tran_sweep, run_vco_pipeline
from ai_agent import generate_vco_va, OllamaAgent, ClaudeAgent

EXAMPLES_DIR = Path(__file__).parent.parent / "examples" / "netlists"

# ── Page config ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SynapticAMS",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────
st.markdown("""
<style>
  .block-label { font-size:11px; color:#888; margin-bottom:2px; }
  .serdes-box  { border:2px solid #444; border-radius:8px; padding:12px 8px;
                 text-align:center; background:#1a1a2e; }
  .serdes-active { border-color:#00bcd4; background:#0d2137; }
  .arrow       { font-size:22px; color:#666; text-align:center; padding-top:18px; }
  div[data-testid="metric-container"] { background:#0d1117; border-radius:8px;
                                        padding:8px; border:1px solid #21262d; }
</style>
""", unsafe_allow_html=True)


# ── Sidebar — AI backend ───────────────────────────────────────────────
with st.sidebar:
    st.title("⚡ SynapticAMS")
    st.caption("SPICE → Verilog-AMS, automatically.")
    st.divider()

    st.markdown("**AI Backend**")

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    ollama_up = OllamaAgent.is_available()

    if has_key:
        default_backend = "Claude (Anthropic)"
    else:
        default_backend = "Ollama — free, local"

    backend = st.radio(
        "",
        ["Ollama — free, local", "Claude (Anthropic)"],
        index=0 if default_backend == "Ollama — free, local" else 1,
        label_visibility="collapsed",
    )

    if backend == "Ollama — free, local":
        if ollama_up:
            models = OllamaAgent.available_models()
            model_name = st.selectbox("Model", models if models else ["qwen2.5-coder:7b"])
            st.success(f"✓ Ollama running  ({model_name})")
            ai_kwargs = {"provider": "ollama", "model": model_name}
        else:
            st.error("Ollama not running. In a terminal:")
            st.code("ollama serve", language="bash")
            st.info("Then refresh this page.")
            ai_kwargs = {"provider": "ollama"}
    else:
        if has_key:
            st.success("✓ ANTHROPIC_API_KEY set")
        else:
            st.warning("Set ANTHROPIC_API_KEY env var, then restart:")
            st.code("export ANTHROPIC_API_KEY=sk-ant-...\nstreamlit run demo/app.py")
        ai_kwargs = {}

    st.divider()
    st.markdown("**CLI (production)**")
    st.code(
        "# Data path\npython pipeline.py serdes_cml.cir\n\n"
        "# VCO / clock\npython pipeline.py --vco vco_ring5.cir",
        language="bash",
    )


# ══════════════════════════════════════════════════════════════════════
# SerDes block diagram  (always visible, orients the VP)
# ══════════════════════════════════════════════════════════════════════

st.markdown("## SerDes Analog Front-End")
st.markdown(
    "A SerDes (Serializer/Deserializer) transmits data over a physical channel at Gbps speeds. "
    "The **analog blocks** — TX driver, channel, RX amplifier, and VCO/PLL clock recovery — "
    "each need a Verilog-AMS behavioral model for system-level simulation. "
    "SynapticAMS generates these models automatically from SPICE netlists."
)

# Draw the chain as a matplotlib figure
fig_chain, ax = plt.subplots(figsize=(13, 2.2))
ax.set_xlim(0, 13)
ax.set_ylim(0, 2.2)
ax.axis("off")
fig_chain.patch.set_facecolor("#0e1117")

BLOCKS = [
    # (x_center, label_top, label_bot, color, tab_hint)
    (1.1,  "TX CML",      "Driver",        "#1565C0", "Tab 1"),
    (3.3,  "PCB",         "Channel",       "#37474F", "Tab 1"),
    (5.5,  "RX CML",      "Amplifier",     "#1565C0", "Tab 1"),
    (7.7,  "Slicer /",    "Sampler",       "#37474F", ""),
    (9.9,  "VCO /",       "PLL CDR",       "#1B5E20", "Tab 2"),
    (12.1, "÷N",          "Divider",       "#37474F", ""),
]

W, H = 1.6, 1.2
Y = 0.5

for xc, top, bot, col, hint in BLOCKS:
    rect = FancyBboxPatch((xc - W/2, Y), W, H,
                          boxstyle="round,pad=0.05",
                          linewidth=1.5,
                          edgecolor="#00bcd4" if hint else "#555",
                          facecolor=col,
                          alpha=0.9)
    ax.add_patch(rect)
    ax.text(xc, Y + H*0.65, top, ha="center", va="center",
            color="white", fontsize=8.5, fontweight="bold")
    ax.text(xc, Y + H*0.28, bot, ha="center", va="center",
            color="#ccc", fontsize=7.5)
    if hint:
        ax.text(xc, Y - 0.22, hint, ha="center", va="center",
                color="#00bcd4", fontsize=7, style="italic")

# Arrows between blocks
arrow_xs = [1.9, 4.1, 6.3, 8.5, 10.7]
for ax_x in arrow_xs:
    ax.annotate("", xy=(ax_x + 0.3, Y + H/2),
                xytext=(ax_x, Y + H/2),
                arrowprops=dict(arrowstyle="->", color="#666", lw=1.5))

# Feedback arrow (VCO back to Slicer) — top arc
ax.annotate("", xy=(7.7, Y + H + 0.12),
            xytext=(9.9, Y + H + 0.12),
            arrowprops=dict(arrowstyle="->", color="#4CAF50",
                            lw=1.2, connectionstyle="arc3,rad=-0.3"))
ax.text(8.8, Y + H + 0.28, "recovered clock", ha="center",
        color="#4CAF50", fontsize=6.5, style="italic")

# Feedback divider → VCO
ax.annotate("", xy=(9.9, Y - 0.12),
            xytext=(12.1, Y - 0.12),
            arrowprops=dict(arrowstyle="->", color="#888",
                            lw=1.0, connectionstyle="arc3,rad=0.3"))

# Legend
legend = [
    mpatches.Patch(facecolor="#1565C0", label="Analog — DC/AC pipeline (Tab 1)"),
    mpatches.Patch(facecolor="#1B5E20", label="Analog — VCO/TRAN pipeline (Tab 2)"),
    mpatches.Patch(facecolor="#37474F", label="Digital / behavioral — not modeled here"),
]
ax.legend(handles=legend, loc="upper right", fontsize=7,
          facecolor="#1a1a1a", labelcolor="white",
          edgecolor="#444", framealpha=0.9)

fig_chain.tight_layout(pad=0.3)
st.pyplot(fig_chain, use_container_width=True)
plt.close(fig_chain)

st.divider()

# ══════════════════════════════════════════════════════════════════════
# Tabs
# ══════════════════════════════════════════════════════════════════════
tab1, tab2, tab3 = st.tabs([
    "📡  Tab 1 — SerDes Data Path  (TX → Channel → RX)",
    "🔄  Tab 2 — Clock Recovery  (VCO / PLL)",
    "ℹ️  About",
])


# ══════════════════════════════════════════════════════════════════════
# TAB 1 — SerDes Data Path
# ══════════════════════════════════════════════════════════════════════
with tab1:
    st.header("SerDes Data Path: TX Driver → PCB Channel → RX Amplifier")
    st.markdown(
        "This is the **analog data path** of the SerDes. "
        "The TX driver converts digital bits into a differential CML voltage swing. "
        "The PCB channel attenuates and low-pass filters the signal. "
        "The RX amplifier restores the signal level before the slicer makes the 1/0 decision. "
        "\n\n"
        "SynapticAMS sweeps the input from 0.6 V → 1.2 V in ngspice, captures the "
        "S-curve transfer characteristic and AC Bode response, then asks the LLM to "
        "produce a `laplace_nd` Verilog-AMS model verified by NRMSE."
    )

    col_l, col_r = st.columns([1, 1])

    with col_l:
        st.subheader("SPICE Netlist")
        st.caption("Circuit: 1.8V NMOS CML — TX diff pair → 5Ω/200fF channel → RX diff pair")
        netlist_path = EXAMPLES_DIR / "serdes_cml.cir"
        netlist_text = netlist_path.read_text() if netlist_path.exists() else ""
        netlist_input = st.text_area("", value=netlist_text, height=360,
                                     label_visibility="collapsed")
        run_dc = st.button("▶  Run SerDes Pipeline", type="primary",
                           use_container_width=True)

    with col_r:
        st.subheader("Output")
        dc_output_area = st.empty()

    if run_dc and netlist_input.strip():
        with dc_output_area.container():
            with st.spinner("ngspice simulating + LLM generating..."):
                t0 = time.time()
                with tempfile.TemporaryDirectory() as tmpdir:
                    try:
                        va_path, nrmse = run_pipeline(
                            netlist_input,
                            output_dir=tmpdir,
                            **ai_kwargs,
                        )
                        va_code = Path(va_path).read_text()
                        elapsed = time.time() - t0
                        info = parse_netlist(netlist_input)

                        # Metrics row
                        m1, m2, m3 = st.columns(3)
                        nrmse_pct = (nrmse or 0) * 100
                        m1.metric("NRMSE", f"{nrmse_pct:.2f}%",
                                  delta="PASS ✓" if nrmse_pct < 5 else "needs refinement",
                                  delta_color="normal" if nrmse_pct < 5 else "inverse")
                        m2.metric("Model accuracy", f"{100 - nrmse_pct:.1f}%")
                        m3.metric("Runtime", f"{elapsed:.1f} s")

                        # Plot
                        plot_path = Path(tmpdir) / "characterization.png"
                        if plot_path.exists():
                            st.image(str(plot_path),
                                     caption="Left: DC S-curve (ngspice vs model)  |  Right: AC Bode plot",
                                     use_container_width=True)

                        # Generated VA
                        st.subheader("Generated Verilog-AMS")
                        st.code(va_code, language="verilog")
                        st.download_button("⬇ Download model.va", data=va_code,
                                           file_name="serdes_rx_model.va",
                                           use_container_width=True)

                    except Exception as e:
                        st.error(f"Pipeline error: {e}")
                        import traceback
                        st.code(traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════
# TAB 2 — VCO / PLL
# ══════════════════════════════════════════════════════════════════════
with tab2:
    st.header("Clock Recovery: VCO / PLL CDR")
    st.markdown(
        "The **VCO is the analog core of the PLL Clock and Data Recovery (CDR)** circuit. "
        "In a locked SerDes, the PLL drives the VCO control voltage until the VCO output "
        "frequency equals the incoming data rate — allowing the slicer to sample "
        "bits at the optimal eye-center point.\n\n"
        "Because a VCO oscillates, it has no DC transfer function — a DC sweep produces "
        "nothing useful. Instead, SynapticAMS runs a **transient simulation** at N different "
        "control voltages, counts oscillation cycles to measure frequency, fits a linear "
        "Kvco model, and generates a Verilog-AMS `idtmod` behavioral model. "
        "**No LLM needed** — the parameters come directly from simulation."
    )

    col_vl, col_vr = st.columns([1, 1])

    with col_vl:
        st.subheader("SPICE Netlist")
        st.caption("Circuit: 5-stage current-starved ring VCO, 1.8V, Level-1 MOSFET")
        vco_path = EXAMPLES_DIR / "vco_ring5.cir"
        vco_default = vco_path.read_text() if vco_path.exists() else ""
        vco_input = st.text_area("", value=vco_default, height=300,
                                 label_visibility="collapsed")

        with st.expander("⚙ Sweep settings"):
            c1, c2 = st.columns(2)
            vctrl_min = c1.number_input("Vctrl min (V)", 0.5, 1.0, 0.70, 0.05)
            vctrl_max = c2.number_input("Vctrl max (V)", 1.0, 1.8, 1.20, 0.05)
            n_pts = st.slider("Bias points", 3, 11, 7, 2)

        run_vco = st.button("▶  Run VCO Pipeline", type="primary",
                            use_container_width=True)

    with col_vr:
        st.subheader("Output")
        vco_output_area = st.empty()

    if run_vco and vco_input.strip():
        with vco_output_area.container():
            with st.spinner("Running transient sweeps..."):
                t0 = time.time()
                try:
                    vctrl_vals = np.linspace(vctrl_min, vctrl_max, n_pts)
                    metrics = vco_tran_sweep(vco_input, ctrl_source="Vctrl",
                                             output_node="vout",
                                             vctrl_values=vctrl_vals)
                    va_code = generate_vco_va(metrics)
                    elapsed = time.time() - t0

                    # Metrics
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Kvco", f"{metrics['kvco']/1e6:.0f} MHz/V")
                    m2.metric("Linearity R²", f"{metrics['r_squared']:.4f}")
                    m3.metric("Runtime", f"{elapsed:.1f} s")

                    # f vs Vctrl plot
                    fig, ax = plt.subplots(figsize=(5.5, 3))
                    vc = metrics['vctrl']
                    fr = metrics['frequencies'] / 1e6
                    ax.scatter(vc, fr, color="#4CAF50", zorder=5, s=70,
                               label="ngspice .TRAN measured")
                    vc_fit = np.linspace(vc.min(), vc.max(), 100)
                    fr_fit = (metrics['kvco'] * vc_fit + metrics['f_intercept']) / 1e6
                    ax.plot(vc_fit, fr_fit, color="#FF9800", lw=2, ls="--",
                            label=f"Linear fit  Kvco={metrics['kvco']/1e6:.0f} MHz/V  R²={metrics['r_squared']:.3f}")
                    ax.set_xlabel("Vctrl (V)", color="#ccc")
                    ax.set_ylabel("Oscillation frequency (MHz)", color="#ccc")
                    ax.set_title("VCO Characterization: f vs Vctrl", color="white")
                    ax.legend(fontsize=8, facecolor="#1a1a1a",
                              labelcolor="white", edgecolor="#444")
                    ax.set_facecolor("#0d1117")
                    ax.tick_params(colors="#aaa")
                    for spine in ax.spines.values():
                        spine.set_edgecolor("#444")
                    fig.patch.set_facecolor("#0e1117")
                    fig.tight_layout()
                    st.pyplot(fig, use_container_width=True)
                    plt.close(fig)

                    # PLL context callout
                    f_lo = metrics['frequencies'].min() / 1e6
                    f_hi = metrics['frequencies'].max() / 1e6
                    kvco = metrics['kvco'] / 1e6
                    st.info(
                        f"**In the SerDes PLL:** This VCO covers {f_lo:.0f}–{f_hi:.0f} MHz. "
                        f"With a ÷N divider (N=4), it generates a recovered clock for "
                        f"a {f_hi/4*2:.0f}–{f_hi/2:.0f} Mbps data stream. "
                        f"The loop filter drives Vctrl until frequency lock is achieved."
                    )

                    # Generated VA
                    st.subheader("Generated Verilog-AMS")
                    st.code(va_code, language="verilog")
                    st.download_button("⬇ Download vco_model.va", data=va_code,
                                       file_name="vco_model.va",
                                       use_container_width=True)

                except Exception as e:
                    st.error(f"VCO pipeline error: {e}")
                    import traceback
                    st.code(traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════
# TAB 3 — About
# ══════════════════════════════════════════════════════════════════════
with tab3:
    st.header("About SynapticAMS")
    st.markdown("""
**The problem:** Every analog block on a chip needs a Verilog-AMS behavioral model for
system-level simulation. Writing these by hand takes a skilled analog engineer 1–2 days
per block. A typical SerDes has 6–10 such blocks.

**What SynapticAMS does:** Takes any SPICE netlist, runs it in ngspice, extracts the
transfer characteristic, and produces a validated Verilog-AMS model in under a minute.

---

### How the two pipelines work

| | DC / AC Pipeline | VCO / TRAN Pipeline |
|--|--|--|
| **Circuit types** | Amplifiers, filters, data-path | Ring oscillators, VCOs |
| **Simulation** | DC sweep + AC Bode | .TRAN at N bias points |
| **Model output** | `laplace_nd` (bandwidth-aware) | `idtmod` (phase integration) |
| **AI needed?** | Yes — LLM generates code | No — deterministic template |
| **Validation** | NRMSE vs ngspice | R² of Kvco linear fit |

---

### SerDes block coverage

| Block | Netlist | Pipeline | Status |
|-------|---------|----------|--------|
| TX CML driver | `serdes_cml.cir` | DC + AC | ✅ NRMSE ≈ 1.9% |
| PCB channel | `serdes_cml.cir` | DC + AC | ✅ RC passthrough |
| RX CML amplifier | `serdes_cml.cir` | DC + AC | ✅ NRMSE ≈ 1.9% |
| **VCO / PLL CDR** | `vco_ring5.cir` | TRAN | ✅ Kvco ≈ 335 MHz/V, R²=0.993 |
| PFD / Charge pump | — | — | 🔲 Digital — no SPICE→VA needed |
| Serializer / Deserializer | — | — | 🔲 Digital RTL |

---

### AI backends

```bash
# Free (local) — recommended for demos
ollama serve
ollama pull qwen2.5-coder:7b
streamlit run demo/app.py

# Cloud (Claude)
export ANTHROPIC_API_KEY=sk-ant-...
streamlit run demo/app.py
```

### CLI (what engineers actually use)
```bash
python pipeline.py examples/netlists/serdes_cml.cir
python pipeline.py --vco examples/netlists/vco_ring5.cir
python tests/test_pipeline.py --skip-live   # 56 unit tests
```
    """)
