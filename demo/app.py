"""
SynapticAMS — VP Demo UI
Run:  streamlit run demo/app.py
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
from matplotlib.patches import FancyBboxPatch

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import run_pipeline, parse_netlist, vco_tran_sweep, run_vco_pipeline
from ai_agent import generate_vco_va, evaluate_va_code, OllamaAgent

EXAMPLES_DIR = Path(__file__).parent.parent / "examples" / "netlists"

# ── Page config ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SynapticAMS",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  div[data-testid="metric-container"] {
    background: #0d1117; border-radius: 8px;
    padding: 10px; border: 1px solid #21262d;
  }
  .stTabs [data-baseweb="tab"] { font-size: 15px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚡ SynapticAMS")
    st.caption("SPICE → Verilog-AMS, automatically.")
    st.divider()

    st.markdown("**AI Backend**")
    has_key   = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    ollama_up = OllamaAgent.is_available()

    backend = st.radio(
        "",
        ["Ollama — free, local", "Claude (Anthropic)"],
        index=0 if not has_key else 1,
        label_visibility="collapsed",
    )

    if backend == "Ollama — free, local":
        if ollama_up:
            models     = OllamaAgent.available_models()
            model_name = st.selectbox("Model", models if models else ["qwen2.5-coder:7b"])
            st.success(f"Ollama running · {model_name}")
            ai_kwargs  = {"provider": "ollama", "ai_model": model_name}
        else:
            st.error("Ollama not running.")
            st.code("ollama serve", language="bash")
            ai_kwargs  = {"provider": "ollama"}
    else:
        if has_key:
            st.success("ANTHROPIC_API_KEY set")
        else:
            st.warning("Set ANTHROPIC_API_KEY, then restart.")
            st.code("export ANTHROPIC_API_KEY=sk-ant-...")
        ai_kwargs = {}


# ── Header ─────────────────────────────────────────────────────────────
st.markdown("## SynapticAMS")
st.markdown(
    "Analog IP modeling, automated. Takes a SPICE netlist, simulates it, "
    "and generates a validated Verilog-AMS behavioral model — in under a minute."
)

# ── SerDes block diagram ───────────────────────────────────────────────
fig_chain, ax = plt.subplots(figsize=(13, 2.0))
ax.set_xlim(0, 13); ax.set_ylim(0, 2.0); ax.axis("off")
fig_chain.patch.set_facecolor("#0e1117")

BLOCKS = [
    (1.1,  "TX CML",   "Driver",    "#1565C0", "Tab 1"),
    (3.3,  "PCB",      "Channel",   "#37474F", "Tab 1"),
    (5.5,  "RX CML",   "Amplifier", "#1565C0", "Tab 1"),
    (7.7,  "Slicer /", "Sampler",   "#37474F", ""),
    (9.9,  "VCO /",    "PLL CDR",   "#1B5E20", "Tab 2"),
    (12.1, "÷N",       "Divider",   "#37474F", ""),
]
W, H, Y = 1.6, 1.1, 0.45

for xc, top, bot, col, hint in BLOCKS:
    ax.add_patch(FancyBboxPatch((xc - W/2, Y), W, H, boxstyle="round,pad=0.05",
                                linewidth=1.5,
                                edgecolor="#00bcd4" if hint else "#555",
                                facecolor=col, alpha=0.9))
    ax.text(xc, Y + H*0.65, top, ha="center", va="center",
            color="white", fontsize=8.5, fontweight="bold")
    ax.text(xc, Y + H*0.28, bot, ha="center", va="center", color="#ccc", fontsize=7.5)
    if hint:
        ax.text(xc, Y - 0.20, hint, ha="center", va="center",
                color="#00bcd4", fontsize=7, style="italic")

for ax_x in [1.9, 4.1, 6.3, 8.5, 10.7]:
    ax.annotate("", xy=(ax_x + 0.3, Y + H/2), xytext=(ax_x, Y + H/2),
                arrowprops=dict(arrowstyle="->", color="#666", lw=1.5))

ax.annotate("", xy=(7.7, Y + H + 0.10), xytext=(9.9, Y + H + 0.10),
            arrowprops=dict(arrowstyle="->", color="#4CAF50", lw=1.2,
                            connectionstyle="arc3,rad=-0.3"))
ax.text(8.8, Y + H + 0.25, "recovered clock", ha="center",
        color="#4CAF50", fontsize=6.5, style="italic")
ax.annotate("", xy=(9.9, Y - 0.10), xytext=(12.1, Y - 0.10),
            arrowprops=dict(arrowstyle="->", color="#888", lw=1.0,
                            connectionstyle="arc3,rad=0.3"))

ax.legend(handles=[
    mpatches.Patch(facecolor="#1565C0", label="DC + AC pipeline  (Tab 1)"),
    mpatches.Patch(facecolor="#1B5E20", label="VCO / TRAN pipeline  (Tab 2)"),
    mpatches.Patch(facecolor="#37474F", label="Digital — not modeled"),
], loc="upper right", fontsize=7, facecolor="#1a1a1a",
   labelcolor="white", edgecolor="#444", framealpha=0.9)

fig_chain.tight_layout(pad=0.2)
st.pyplot(fig_chain, use_container_width=True)
plt.close(fig_chain)

st.divider()


# ══════════════════════════════════════════════════════════════════════
# Tabs
# ══════════════════════════════════════════════════════════════════════
tab1, tab2 = st.tabs([
    "  Tab 1 — Analog Data Path  (TX → Channel → RX)  ",
    "  Tab 2 — Clock Recovery  (VCO / PLL)  ",
])


# ══════════════════════════════════════════════════════════════════════
# TAB 1 — Analog Data Path
# ══════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown(
        "The TX driver converts digital bits into a differential CML voltage swing. "
        "The PCB channel attenuates and bandlimits the signal. "
        "The RX amplifier restores the level before the slicer makes a 1/0 decision. "
        "**SynapticAMS generates a validated Verilog-AMS model for this entire chain automatically.**"
    )
    st.markdown("")

    col_l, col_r = st.columns([1, 1])

    with col_l:
        st.markdown("**SPICE Netlist**")
        st.caption("1.8V NMOS CML — TX diff pair → 5Ω / 200fF channel → RX diff pair")
        netlist_path  = EXAMPLES_DIR / "serdes_cml.cir"
        netlist_text  = netlist_path.read_text() if netlist_path.exists() else ""
        netlist_input = st.text_area("netlist", value=netlist_text, height=340,
                                     label_visibility="collapsed")
        run_dc = st.button("▶  Run Pipeline", type="primary",
                           key="run_dc", use_container_width=True)

    with col_r:
        st.markdown("**Results**")
        dc_out = st.empty()

    if run_dc and netlist_input.strip():
        with dc_out.container():
            with st.spinner("Simulating in ngspice + generating model..."):
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
                        info    = parse_netlist(netlist_input)

                        # ── Metrics ───────────────────────────────────
                        nrmse_pct = (nrmse or 0) * 100
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Model accuracy",
                                  f"{100 - nrmse_pct:.1f}%",
                                  delta="validated ✓" if nrmse_pct < 5 else "needs refinement",
                                  delta_color="normal" if nrmse_pct < 5 else "inverse")
                        m2.metric("NRMSE vs ngspice", f"{nrmse_pct:.2f}%")
                        m3.metric("Runtime", f"{elapsed:.1f} s")

                        # ── Comparison chart: ngspice vs model ────────
                        data_path = Path(tmpdir) / "sweep_data.npz"
                        if data_path.exists():
                            d     = np.load(data_path)
                            x_sim = d["x"]
                            y_sim = d["y"]
                            y_mod = evaluate_va_code(va_code, x_sim,
                                                     info["output_node"])

                            fig, axes = plt.subplots(1, 2, figsize=(9, 3.2))
                            fig.patch.set_facecolor("#0e1117")

                            # Left — DC comparison
                            ax0 = axes[0]
                            ax0.set_facecolor("#0d1117")
                            ax0.plot(x_sim, y_sim, color="#4FC3F7",
                                     lw=2, label="ngspice (ground truth)")
                            if y_mod is not None and not np.all(np.isnan(y_mod)):
                                ax0.plot(x_sim, y_mod, color="#FF9800",
                                         lw=1.5, ls="--", label="generated model")
                            ax0.set_xlabel(f"V({info['signal_source']})  [V]",
                                           color="#aaa")
                            ax0.set_ylabel(f"V({info['output_node']})  [V]",
                                           color="#aaa")
                            ax0.set_title("DC Transfer Characteristic", color="white")
                            ax0.legend(fontsize=7.5, facecolor="#1a1a1a",
                                       labelcolor="white", edgecolor="#444")
                            ax0.tick_params(colors="#aaa")
                            for sp in ax0.spines.values():
                                sp.set_edgecolor("#333")

                            # Right — Bode (from saved PNG if AC ran)
                            ax1 = axes[1]
                            ax1.set_facecolor("#0d1117")
                            bode_path = Path(tmpdir) / "characterization.png"
                            if bode_path.exists():
                                # Re-read the saved figure and copy the AC panel
                                bode_img = plt.imread(str(bode_path))
                                # characterization.png is (DC | Bode) side-by-side
                                w = bode_img.shape[1]
                                ax1.imshow(bode_img[:, w//2:], aspect="auto",
                                           extent=[0, 1, 0, 1])
                                ax1.set_axis_off()
                                ax1.set_title("AC Bode (ngspice)", color="white")
                            else:
                                ax1.text(0.5, 0.5, "AC sweep\nnot available",
                                         ha="center", va="center", color="#888",
                                         fontsize=10)
                                ax1.set_axis_off()

                            fig.tight_layout(pad=0.5)
                            st.pyplot(fig, use_container_width=True)
                            plt.close(fig)

                            if y_mod is not None and not np.all(np.isnan(y_mod)):
                                st.caption(
                                    "Blue = ngspice simulation (ground truth).  "
                                    "Orange dashed = generated Verilog-AMS model evaluated "
                                    "at the same input points.  NRMSE measures how closely "
                                    "they match."
                                )
                            else:
                                st.caption(
                                    "Dynamic model (laplace_nd) — Python evaluator not "
                                    "applicable. See DC curve above for ngspice ground truth."
                                )

                        # ── Generated Verilog-AMS ─────────────────────
                        st.markdown("**Generated Verilog-AMS**")
                        st.code(va_code, language="verilog")
                        st.download_button("Download model.va", data=va_code,
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
    st.markdown(
        "The VCO is the analog core of the PLL Clock and Data Recovery (CDR) circuit. "
        "Because a VCO oscillates, a DC sweep produces nothing useful. "
        "**SynapticAMS runs transient simulations at N control voltages, measures the "
        "oscillation frequency at each point, fits a linear Kvco model, and generates "
        "a Verilog-AMS idtmod behavioral model — no LLM required.**"
    )
    st.markdown("")

    col_vl, col_vr = st.columns([1, 1])

    with col_vl:
        st.markdown("**SPICE Netlist**")
        st.caption("5-stage current-starved ring VCO · 1.8V · Level-1 MOSFET")
        vco_path    = EXAMPLES_DIR / "vco_ring5.cir"
        vco_default = vco_path.read_text() if vco_path.exists() else ""
        vco_input   = st.text_area("vco_netlist", value=vco_default, height=280,
                                   label_visibility="collapsed")

        with st.expander("Sweep settings"):
            c1, c2      = st.columns(2)
            vctrl_min   = c1.number_input("Vctrl min (V)", 0.5, 1.0, 0.70, 0.05)
            vctrl_max   = c2.number_input("Vctrl max (V)", 1.0, 1.8, 1.20, 0.05)
            n_pts       = st.slider("Bias points", 3, 11, 7, 2)

        run_vco = st.button("▶  Run VCO Pipeline", type="primary",
                            key="run_vco", use_container_width=True)

    with col_vr:
        st.markdown("**Results**")
        vco_out = st.empty()

    if run_vco and vco_input.strip():
        with vco_out.container():
            with st.spinner("Running transient sweeps..."):
                t0 = time.time()
                try:
                    vctrl_vals = np.linspace(vctrl_min, vctrl_max, n_pts)
                    metrics    = vco_tran_sweep(vco_input,
                                               ctrl_source="Vctrl",
                                               output_node="vout",
                                               vctrl_values=vctrl_vals)
                    va_code    = generate_vco_va(metrics)
                    elapsed    = time.time() - t0

                    # ── Metrics ───────────────────────────────────────
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Kvco", f"{metrics['kvco']/1e6:.0f} MHz/V")
                    m2.metric("Linearity R²", f"{metrics['r_squared']:.4f}")
                    m3.metric("Runtime", f"{elapsed:.1f} s")

                    # ── f vs Vctrl chart ──────────────────────────────
                    vc  = metrics["vctrl"]
                    fr  = metrics["frequencies"] / 1e6
                    vc_fit = np.linspace(vc.min(), vc.max(), 100)
                    fr_fit = (metrics["kvco"] * vc_fit + metrics["f_intercept"]) / 1e6

                    fig, ax = plt.subplots(figsize=(5.5, 3.2))
                    fig.patch.set_facecolor("#0e1117")
                    ax.set_facecolor("#0d1117")
                    ax.scatter(vc, fr, color="#4CAF50", zorder=5, s=70,
                               label="ngspice .TRAN — measured")
                    ax.plot(vc_fit, fr_fit, color="#FF9800", lw=2, ls="--",
                            label=f"Linear fit  Kvco={metrics['kvco']/1e6:.0f} MHz/V  "
                                  f"R²={metrics['r_squared']:.3f}")
                    ax.set_xlabel("Vctrl (V)", color="#ccc")
                    ax.set_ylabel("Oscillation frequency (MHz)", color="#ccc")
                    ax.set_title("VCO Characterization: f vs Vctrl", color="white")
                    ax.legend(fontsize=8, facecolor="#1a1a1a",
                              labelcolor="white", edgecolor="#444")
                    ax.tick_params(colors="#aaa")
                    for sp in ax.spines.values():
                        sp.set_edgecolor("#333")
                    fig.tight_layout()
                    st.pyplot(fig, use_container_width=True)
                    plt.close(fig)

                    # ── PLL context ───────────────────────────────────
                    f_lo  = metrics["frequencies"].min() / 1e6
                    f_hi  = metrics["frequencies"].max() / 1e6
                    st.info(
                        f"**In the SerDes PLL:** this VCO covers {f_lo:.0f}–{f_hi:.0f} MHz. "
                        f"With a ÷N divider (N=4), it recovers a clock for a "
                        f"{f_hi/2:.0f} Mbps data stream. "
                        f"The PLL loop filter drives Vctrl until frequency lock is achieved."
                    )

                    # ── Generated Verilog-AMS ─────────────────────────
                    st.markdown("**Generated Verilog-AMS**")
                    st.code(va_code, language="verilog")
                    st.download_button("Download vco_model.va", data=va_code,
                                       file_name="vco_model.va",
                                       use_container_width=True)

                except Exception as e:
                    st.error(f"VCO pipeline error: {e}")
                    import traceback
                    st.code(traceback.format_exc())
