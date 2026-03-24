"""
SynapticAMS Demo UI
===================
Streamlit app for VP / investor demos.

NOTE: This is a demo-only UI. Production usage is via the CLI:
    python pipeline.py <netlist.cir>
    python pipeline.py --vco <vco.cir>

Run:
    streamlit run demo/app.py
"""

import sys
import io
import time
import tempfile
from pathlib import Path

import numpy as np
import streamlit as st
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Make sure project root is importable from demo/
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import run_pipeline, parse_netlist, vco_tran_sweep, run_vco_pipeline
from ai_agent import generate_vco_va

# ── Page config ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SynapticAMS",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Example netlists ───────────────────────────────────────────────────
EXAMPLES_DIR = Path(__file__).parent.parent / "examples" / "netlists"

DC_EXAMPLES = {
    "CML SerDes Data Path (TX → Channel → RX)": "serdes_cml.cir",
    "BJT Common-Emitter Amplifier":              "bjt_amplifier.cir",
    "NMOS Common-Source DC Sweep":               "nmos_dc_sweep.cir",
}

VCO_EXAMPLES = {
    "5-Stage Current-Starved Ring VCO": "vco_ring5.cir",
}

# ── Sidebar ────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://raw.githubusercontent.com/vrajeshprakhya/SynapticAMS/refs/heads/main/docs/diagram.png",
             use_container_width=True) if False else None  # skip remote image fetch
    st.title("⚡ SynapticAMS")
    st.caption("SPICE → Verilog-AMS, automatically.")

    st.divider()
    st.markdown("**AI Backend**")
    provider = st.radio("", ["Claude (Anthropic)", "Ollama (local)"],
                        label_visibility="collapsed")
    if provider == "Claude (Anthropic)":
        import os
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            st.warning("Set ANTHROPIC_API_KEY env var before running.")
        ai_kwargs = {}
    else:
        ollama_url = st.text_input("Ollama URL", "http://localhost:11434")
        ai_kwargs = {"provider": "ollama"}

    st.divider()
    st.markdown("""
**CLI usage (production):**
```bash
# DC/AC pipeline
python pipeline.py netlist.cir

# VCO pipeline
python pipeline.py --vco vco.cir
```
    """)

# ── Main tabs ──────────────────────────────────────────────────────────
tab_dc, tab_vco, tab_about = st.tabs([
    "📈 DC / AC Pipeline",
    "🔄 VCO / PLL Pipeline",
    "ℹ️ About",
])


# ══════════════════════════════════════════════════════════════════════
# TAB 1 — DC / AC Pipeline
# ══════════════════════════════════════════════════════════════════════
with tab_dc:
    st.header("DC / AC Pipeline")
    st.markdown(
        "Runs a DC sweep + AC frequency sweep in ngspice, then generates a "
        "Verilog-AMS behavioral model using an LLM. "
        "NRMSE is computed against the actual simulation to validate accuracy."
    )

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("Input Netlist")
        example_name = st.selectbox("Load example", list(DC_EXAMPLES.keys()))
        example_path = EXAMPLES_DIR / DC_EXAMPLES[example_name]
        default_text = example_path.read_text() if example_path.exists() else ""

        netlist_text = st.text_area(
            "SPICE netlist",
            value=default_text,
            height=340,
            help="Paste any SPICE netlist with a .DC directive.",
        )
        run_btn = st.button("▶ Run Pipeline", type="primary", use_container_width=True)

    with col_right:
        st.subheader("Results")
        results_placeholder = st.empty()

    if run_btn and netlist_text.strip():
        with st.spinner("Running ngspice + AI generation..."):
            t0 = time.time()
            with tempfile.TemporaryDirectory() as tmpdir:
                try:
                    va_path, nrmse = run_pipeline(
                        netlist_text,
                        output_dir=tmpdir,
                        **ai_kwargs,
                    )
                    va_code = Path(va_path).read_text()
                    elapsed = time.time() - t0

                    # Parse info for labels
                    info = parse_netlist(netlist_text)

                    # ── NRMSE metric ──────────────────────────────────
                    with col_right:
                        nrmse_pct = (nrmse * 100) if nrmse is not None else None
                        if nrmse_pct is not None:
                            color = "normal" if nrmse_pct < 5 else "inverse"
                            st.metric(
                                "NRMSE (model vs. ngspice)",
                                f"{nrmse_pct:.2f}%",
                                delta=f"{'PASS ✓' if nrmse_pct < 5 else 'FAIL — refine'}",
                                delta_color=color,
                            )
                        st.metric("Runtime", f"{elapsed:.1f}s")

                    # ── DC sweep plot ─────────────────────────────────
                    dc_plot_path = Path(tmpdir) / "characterization.png"
                    if dc_plot_path.exists():
                        st.image(str(dc_plot_path),
                                 caption="DC transfer curve + AC Bode plot",
                                 use_container_width=True)
                    else:
                        # Fallback: generate inline plot
                        from ngspice_runner import NgspiceRunner
                        runner = NgspiceRunner()
                        dc_r = runner.dc_sweep(netlist_text, {
                            "sweep_var": info["signal_source"],
                            "start": info.get("dc_start", 0),
                            "stop":  info.get("dc_stop",  info["vdd"]),
                            "step":  info.get("dc_step",  info["vdd"] / 50),
                            "observe": [info["output_node"]],
                        })
                        x = dc_r[info["signal_source"]]
                        y = dc_r[info["output_node"]]
                        fig, ax = plt.subplots(figsize=(5, 3))
                        ax.plot(x, y, color="#2196F3", linewidth=2)
                        ax.set_xlabel(f"{info['signal_source']} (V)")
                        ax.set_ylabel(f"V({info['output_node']}) (V)")
                        ax.set_title("DC Transfer Characteristic")
                        ax.grid(True, alpha=0.3)
                        fig.tight_layout()
                        st.pyplot(fig)
                        plt.close(fig)

                    # ── Generated Verilog-AMS ─────────────────────────
                    st.subheader("Generated Verilog-AMS")
                    st.code(va_code, language="verilog")
                    st.download_button(
                        "⬇ Download .va file",
                        data=va_code,
                        file_name="model.va",
                        mime="text/plain",
                        use_container_width=True,
                    )

                except Exception as e:
                    with col_right:
                        st.error(f"Pipeline error: {e}")
                        import traceback
                        st.code(traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════
# TAB 2 — VCO / PLL Pipeline
# ══════════════════════════════════════════════════════════════════════
with tab_vco:
    st.header("VCO / PLL Pipeline")
    st.markdown(
        "Characterizes a ring VCO by running `.TRAN` at multiple control-voltage "
        "bias points, extracts the VCO gain (Kvco), and generates a Verilog-AMS "
        "`idtmod` behavioral model — **no LLM needed**, parameters come directly "
        "from simulation."
    )

    col_vl, col_vr = st.columns([1, 1])

    with col_vl:
        st.subheader("Input Netlist")
        vco_example_name = st.selectbox("Load example", list(VCO_EXAMPLES.keys()))
        vco_example_path = EXAMPLES_DIR / VCO_EXAMPLES[vco_example_name]
        vco_default = vco_example_path.read_text() if vco_example_path.exists() else ""

        vco_netlist = st.text_area(
            "SPICE netlist",
            value=vco_default,
            height=300,
            help="Netlist must have a .TRAN directive and .IC to start oscillation.",
        )

        with st.expander("⚙ Sweep settings"):
            vctrl_min = st.slider("Vctrl min (V)", 0.5, 1.0, 0.70, 0.05)
            vctrl_max = st.slider("Vctrl max (V)", 1.0, 1.8, 1.20, 0.05)
            n_pts     = st.slider("Number of bias points", 3, 11, 7, 2)
            ctrl_src  = st.text_input("Control voltage source name", "Vctrl")
            out_node  = st.text_input("Output node name", "vout")

        vco_run = st.button("▶ Run VCO Pipeline", type="primary", use_container_width=True)

    with col_vr:
        st.subheader("Results")

    if vco_run and vco_netlist.strip():
        with st.spinner("Running transient sweeps..."):
            t0 = time.time()
            try:
                vctrl_vals = np.linspace(vctrl_min, vctrl_max, n_pts)
                metrics = vco_tran_sweep(
                    vco_netlist,
                    ctrl_source=ctrl_src,
                    output_node=out_node,
                    vctrl_values=vctrl_vals,
                )
                va_code = generate_vco_va(metrics)
                elapsed = time.time() - t0

                with col_vr:
                    # ── Key metrics ───────────────────────────────────
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Kvco", f"{metrics['kvco']/1e6:.1f} MHz/V")
                    m2.metric("f_ref", f"{metrics['f_ref']/1e6:.1f} MHz")
                    m3.metric("Linearity R²", f"{metrics['r_squared']:.4f}")
                    st.metric("Runtime", f"{elapsed:.1f}s")

                    # ── Frequency vs Vctrl plot ───────────────────────
                    fig, ax = plt.subplots(figsize=(5, 3))
                    vc_arr = metrics['vctrl']
                    fr_arr = metrics['frequencies'] / 1e6
                    ax.scatter(vc_arr, fr_arr, color="#4CAF50", zorder=5, s=60, label="Measured")
                    # linear fit line
                    vc_fit = np.linspace(vc_arr.min(), vc_arr.max(), 100)
                    fr_fit = (metrics['kvco'] * vc_fit + metrics['f_intercept']) / 1e6
                    ax.plot(vc_fit, fr_fit, color="#FF9800", linewidth=1.5,
                            linestyle="--", label=f"Kvco fit (R²={metrics['r_squared']:.3f})")
                    ax.set_xlabel("Vctrl (V)")
                    ax.set_ylabel("Frequency (MHz)")
                    ax.set_title("VCO Characterization: f vs Vctrl")
                    ax.legend(fontsize=8)
                    ax.grid(True, alpha=0.3)
                    fig.tight_layout()
                    st.pyplot(fig)
                    plt.close(fig)

                    # ── Generated Verilog-AMS ─────────────────────────
                    st.subheader("Generated Verilog-AMS")
                    st.code(va_code, language="verilog")
                    st.download_button(
                        "⬇ Download vco_model.va",
                        data=va_code,
                        file_name="vco_model.va",
                        mime="text/plain",
                        use_container_width=True,
                    )

            except Exception as e:
                with col_vr:
                    st.error(f"VCO pipeline error: {e}")
                    import traceback
                    st.code(traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════
# TAB 3 — About
# ══════════════════════════════════════════════════════════════════════
with tab_about:
    st.header("About SynapticAMS")
    st.markdown("""
SynapticAMS converts transistor-level SPICE netlists into Verilog-AMS behavioral
models automatically — replacing a process that normally takes an experienced analog
engineer 1–2 days per block.

---

### How it works

```
SPICE netlist (.cir)
       │
       ▼  ngspice simulation
  DC sweep + AC sweep data
       │
       ▼  LLM (Claude / Ollama)
  Verilog-AMS code (.va)
       │
       ▼  NRMSE validation loop
  Verified behavioral model
```

For **VCOs**, the pipeline uses transient analysis instead of DC sweep:
```
SPICE netlist (.cir)
       │
       ▼  ngspice .TRAN × N bias points
  (Vctrl, f_osc) pairs
       │
       ▼  linear Kvco fit
  Kvco, f_ref, R²
       │
       ▼  deterministic template
  Verilog-AMS (idtmod model)
```

---

### Production CLI

This UI is for demos. In production, engineers use the CLI directly:

```bash
# DC + AC pipeline (outputs model.va)
python pipeline.py examples/netlists/serdes_cml.cir

# VCO pipeline (outputs vco_model.va)
python pipeline.py --vco examples/netlists/vco_ring5.cir

# Hybrid ensemble (AI vs programmatic, returns best)
python hybrid_ensemble.py

# Full test suite
python tests/test_pipeline.py --skip-live   # fast, no external deps
python tests/test_pipeline.py               # all tests (needs ngspice + AI)
```

---

### SerDes coverage

| Block | Circuit | Pipeline | Model |
|-------|---------|----------|-------|
| TX CML driver | `serdes_cml.cir` | DC + AC | `laplace_nd` |
| PCB channel | `serdes_cml.cir` | DC + AC | RC passthrough |
| RX CML amplifier | `serdes_cml.cir` | DC + AC | `laplace_nd` |
| VCO / PLL CDR | `vco_ring5.cir` | TRAN | `idtmod` |

---

### AI backends

| Backend | Setup |
|---------|-------|
| Claude (recommended) | `export ANTHROPIC_API_KEY=sk-ant-...` |
| Ollama (free, local) | `ollama serve && ollama pull qwen2.5-coder:7b` |
    """)
