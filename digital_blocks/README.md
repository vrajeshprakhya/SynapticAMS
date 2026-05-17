# SerDes Digital Blocks

This folder contains behavioral Python models for all **blue (digital)** blocks
in the SynapticAMS SerDes architecture diagram
([`docs/serdes_architecture_diagram.md`](../docs/serdes_architecture_diagram.md)).

Each block is self-contained and can be:
- Imported directly in Python for system-level simulation
- Run standalone via its testbench for unit verification
- Eventually integrated with the SynapticAMS analog blocks via the
  ngspice + Verilog-AMS co-simulation pipeline already in this repo

---

## Block Map

| File | Block in Diagram | Domain |
|---|---|---|
| [`encoder_8b10b.py`](encoder_8b10b.py) | TX Encoder (8b/10b) | TX |
| [`decoder_8b10b.py`](decoder_8b10b.py) | RX Decoder | RX |
| [`encoder_64b66b.py`](encoder_64b66b.py) | TX Encoder (64b/66b) | TX |
| [`tx_ffe.py`](tx_ffe.py) | TX FFE (Digital Pre-emphasis) | TX |
| [`cdr_divider.py`](cdr_divider.py) | CDR Divider / Counter | CDR |
| [`error_detector.py`](error_detector.py) | Error Detector (Eye Monitor) | Adapt |
| [`adaptive_engine.py`](adaptive_engine.py) | Adaptive Engine (LMS) | Adapt |

---

## Confirmed Existing Analog Blocks

The following analog blocks are **already built** in this repository and can
be used immediately with the ngspice pipeline:

| Block | File | Notes |
|---|---|---|
| TX CML Driver + TX Termination | [`examples/netlists/serdes_cml.cir`](../examples/netlists/serdes_cml.cir) | NMOS CML diff pair, 1.8V, ±200mV swing |
| PCB Channel | [`examples/netlists/serdes_cml.cir`](../examples/netlists/serdes_cml.cir) | 5cm 50Ω RC trace model |
| RX CML Amplifier + Termination | [`examples/netlists/serdes_cml.cir`](../examples/netlists/serdes_cml.cir) | 10V/V gain, ~200MHz BW |
| VCO / PLL (ring oscillator) | [`examples/netlists/vco_ring5.cir`](../examples/netlists/vco_ring5.cir) | 5-stage, Kvco≈335 MHz/V |
| VCO Verilog-AMS model | [`output_pll_demo/vco_model.va`](../output_pll_demo/vco_model.va) | AI-extracted behavioral model |
| Full RX system (CTLE+VGA+Summer) | [`examples/serdes_system_level_demo/serdes_final_model/final/serdes_rx_system.va`](../examples/serdes_system_level_demo/serdes_final_model/final/serdes_rx_system.va) | 2D LUT Verilog-AMS behavioral model |
| Inverter-based TX/RX (OpenSERDES) | [`openserdes_complete.cir`](../openserdes_complete.cir) | 3.3V CMOS reference |
| BJT Amplifier | [`examples/netlists/bjt_amplifier.cir`](../examples/netlists/bjt_amplifier.cir) | Small-signal model |

The **boundary blocks** (Serializer, Sampler, Comparator, DFE Logic, Phase
Detector, etc.) are not yet built but are the natural next step bridging these
digital blocks to the analog blocks.

---

## How to Simulate

### Prerequisites

```bash
cd /path/to/SynapticAMS
# Activate the virtual environment
source .venv/bin/activate
# numpy is required (already in requirements.txt)
pip install numpy scipy
```

### Option 1: Run individual testbenches

Each testbench can be run as a standalone script:

```bash
# 8b/10b Encoder
python -m digital_blocks.testbenches.tb_encoder_8b10b

# 8b/10b Decoder (round-trip)
python -m digital_blocks.testbenches.tb_decoder_8b10b

# 64b/66b Encoder / Decoder
python -m digital_blocks.testbenches.tb_encoder_64b66b

# TX FFE with frequency response
python -m digital_blocks.testbenches.tb_tx_ffe

# CDR Divider (measures effective ratio)
python -m digital_blocks.testbenches.tb_cdr_divider

# Eye monitor + Mueller-Müller TED
python -m digital_blocks.testbenches.tb_error_detector

# LMS adaptive engine convergence
python -m digital_blocks.testbenches.tb_adaptive_engine

# Full integration testbench (all blocks together)
python -m digital_blocks.testbenches.tb_integration
```

### Option 2: Run all tests with pytest

```bash
pytest digital_blocks/testbenches/ -v
# Or with coverage:
pytest digital_blocks/testbenches/ -v --tb=short
```

### Option 3: Import in your own script

```python
from digital_blocks import (
    Encoder8b10b, Decoder8b10b,
    Encoder64b66b, Decoder64b66b,
    TxFFE, CDRDivider,
    ErrorDetector, AdaptiveEngine,
)

# 8b/10b encode a stream
enc = Encoder8b10b()
codes = enc.encode_stream([0x00, 0xBC, 0xFF, 0xAA])

# TX FFE with PCIe P5 preset
ffe = TxFFE.from_preset('P5')
tx_symbols = ffe.filter([1., -1., 1., 1., -1., 1., -1.])

# CDR divide by 4.5 (fractional)
div = CDRDivider(ratio=4.5)
clk = div.run(10000)

# LMS adaptation
engine = AdaptiveEngine(ffe_taps=3, dfe_taps=5)
for samples, decisions in your_data_stream:
    coeffs = engine.update(samples, decisions)
    ffe.set_taps(coeffs.ffe)
```

### Option 4: Mixed-signal co-simulation with ngspice

The digital blocks produce floating-point symbol streams compatible with the
SynapticAMS analog pipeline.  To connect them:

1. **TX side**: use `TxFFE.filter()` to pre-emphasize symbols, then pass the
   result to the `ngspice_runner.py` as a PWL voltage source (use
   `numpy`→PWL conversion as done in `demo_warmstart_validated.py`).

2. **RX side**: run ngspice on `examples/netlists/serdes_cml.cir` to get
   sampled output, then feed into `ErrorDetector` and `AdaptiveEngine`.

3. **CDR**: call `CDRDivider.step()` once per VCO clock cycle (driven from
   VCO model output) to generate the recovered clock.

Example integration snippet:

```python
from ngspice_runner import NgspiceRunner
from digital_blocks import Encoder8b10b, TxFFE, ErrorDetector, AdaptiveEngine

enc = Encoder8b10b()
ffe = TxFFE.from_preset('P5')
ed  = ErrorDetector(baud_rate=500e6)   # match serdes_cml.cir ~500Mbps

# Encode data
codes   = enc.encode_stream(range(256))
symbols = codes_to_nrz(codes)           # your PWL conversion helper
tx_eq   = ffe.filter(symbols)

# Write to PWL and run ngspice
runner  = NgspiceRunner()
results = runner.run_transient('examples/netlists/serdes_cml.cir', tx_pwl=tx_eq)

# Analyse RX output
rx_samples  = results['rx_out_p']
rx_decisions = np.sign(rx_samples)
metrics = ed.analyse(rx_samples, rx_decisions)
print(f"Eye height: {metrics.height:.3f} V, BER≈{metrics.ber_estimate:.2e}")
```

---

## Block Details

### `encoder_8b10b.py` — 8b/10b Encoder

- IEEE 802.3 / IBM Widmer-Franaszek (1983) standard
- Full running disparity (RD±1) tracking
- K-character support (K28.5 comma, K23.7, K27.7, K29.7, K30.7)
- D.x.7 alternate encoding handled correctly (D.17/18/20.7)
- Output: 10-bit integer, bits[9:4]=abcdei, bits[3:0]=fghj

### `decoder_8b10b.py` — 8b/10b Decoder

- Stateful inverse of encoder with RD tracking
- Outputs: `(byte, is_k, code_err, disp_err)` via `DecodeResult` NamedTuple
- Invalid 6-bit or 4-bit codes set `code_err=True`
- Disparity violations set `disp_err=True`

### `encoder_64b66b.py` — 64b/66b Encoder / Decoder

- IEEE 802.3ae Clause 49 (10GbE PCS)
- PRBS-58 self-synchronous scrambler: G(x) = 1 + x^39 + x^58
- Sync header: 01 = data, 10 = control
- Self-sync: descrambler locks within 58 received bits (< 1 block)

### `tx_ffe.py` — TX Feed-Forward Equalizer

- 3–5 tap FIR with configurable tap weights
- 11 built-in PCIe Gen3/4 presets (P0–P10)
- `filter()` — stateful (maintains history across blocks)
- `filter_stateless()` — for isolated analysis
- `frequency_response()` — magnitude in dB vs normalised frequency
- Tap constraint: normalise or clip

### `cdr_divider.py` — CDR Frequency Divider

- `IntegerDivider(n)` — synchronous ÷N, 50% duty cycle for even N
- `FractionalDivider(n_int, frac)` — dual-modulus + Σ-Δ accumulator
- `CDRDivider(ratio)` — high-level wrapper, auto-selects integer/fractional
- `measured_ratio()` — empirical verification over N cycles

### `error_detector.py` — Eye Monitor + TED

- `MuellerMullerTED` — baud-rate timing error: e_MM = y[k-1]â[k] − y[k]â[k-1]
- `EyeMonitor` — eye height (3σ), Q-factor, BER estimate
- `ErrorDetector` — combined interface returning `EyeMetrics` NamedTuple
- Supports NRZ (2-level) and PAM4 (4-level)

### `adaptive_engine.py` — LMS / Sign-LMS

- Adapts: FFE taps, DFE taps, CTLE scalar (dB), VGA gain
- Full LMS or Sign-LMS (replace `e` with `sign(e)` for hardware efficiency)
- Tap constraints: normalise or clip
- `has_converged()` — MSE variance gate
- Returns `AdaptCoeffs` snapshot for direct use by `TxFFE.set_taps()`

---

## Integration with the Rest of the SerDes

```
[This repo — analog blocks]         [digital_blocks/ — this folder]
─────────────────────────          ──────────────────────────────
serdes_cml.cir                 ←── TxFFE → TX DAC (boundary)
vco_ring5.cir                  ←── CDRDivider feedback
serdes_rx_system.va            ←── ErrorDetector input
                                    AdaptiveEngine controls:
                                      CTLE boost (dB)
                                      VGA gain (linear)
                                      DFE taps
                                      FFE taps (backchannel)
```

The boundary blocks (Serializer, Comparator, DFE Logic, Phase Detector,
TX DAC, CTLE Ctrl DAC, VGA Ctrl DAC) are the natural next PR to bridge
these two halves.
