# Hybrid Ensemble Pipeline - Usage Guide

## Overview

The **Hybrid Ensemble Pipeline** (Approach 4) runs both AI and Programmatic pipelines in parallel, compares their NRMSE on independent test data, and automatically returns the best-performing Verilog-AMS model.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                  Hybrid Ensemble Pipeline                     │
│                     (hybrid_ensemble.py)                      │
└──────────────────────────────────────────────────────────────┘
                              │
                              ├─ Parse netlist
                              ├─ Run independent test DC sweep
                              │
                    ┌─────────┴─────────┐
                    │ Parallel Execution │
                    └─────────┬─────────┘
                              │
                 ┌────────────┴────────────┐
                 │                         │
         ┌───────▼────────┐      ┌────────▼─────────┐
         │  AI Pipeline    │      │ Programmatic     │
         │  (pipeline.py)  │      │ (complete_pipe)  │
         └───────┬────────┘      └────────┬─────────┘
                 │                         │
           ┌─────▼─────┐           ┌──────▼──────┐
           │ model_ai  │           │ model_prog  │
           │ NRMSE=X   │           │ NRMSE=Y     │
           └─────┬─────┘           └──────┬──────┘
                 │                         │
                 └─────────┬───────────────┘
                           │
                    ┌──────▼───────┐
                    │ Compare NRMSE │
                    │ on Test Data  │
                    └──────┬────────┘
                           │
                    ┌──────▼────────┐
                    │ Return Winner │
                    └───────────────┘
```

## Quick Start

### Basic Usage

```python
from hybrid_ensemble import ensemble_pipeline

netlist = """
* Common-source NMOS amplifier
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 5
Vin vin 0 DC 0
.MODEL NMOS NMOS (VTO=0.7 KP=100u)
.DC Vin 0 5 0.1
.END
"""

result = ensemble_pipeline(
    netlist,
    output_dir="./output",
    cache=True,
    parallel=True,
)

print(f"Winner: {result['winner']}")
print(f"AI NRMSE: {result['ai_nrmse']:.4f}")
print(f"Programmatic NRMSE: {result['prog_nrmse']:.4f}")
print(f"Best model saved to: {result['va_path']}")
```

### Command-Line Usage

```bash
cd ~/SynapticAMS
python3 hybrid_ensemble.py
```

The example in `hybrid_ensemble.py` demonstrates the complete workflow.

---

## API Reference

### `ensemble_pipeline()`

```python
def ensemble_pipeline(
    netlist_text: str,
    output_dir: str = ".",
    cache: bool = True,
    parallel: bool = True,
    nrmse_threshold: float = 0.05,
    ai_kwargs: Optional[Dict] = None,
) -> Dict[str, Any]
```

#### Parameters

- **`netlist_text`** (str): SPICE netlist as a string
- **`output_dir`** (str, default='.'): Directory to save generated .va files
- **`cache`** (bool, default=True): Enable model caching (avoids regenerating identical circuits)
- **`parallel`** (bool, default=True): Run pipelines in parallel (faster)
- **`nrmse_threshold`** (float, default=0.05): NRMSE threshold for "good enough" (5%)
- **`ai_kwargs`** (dict, optional): Additional arguments for AI pipeline:
  - `provider`: `'ollama'` | `'anthropic'` | `None` (auto-detect)
  - `ai_model`: Model override (e.g., `'qwen2.5-coder:7b'`)
  - `max_iterations`: Max AI refinement passes (default: 3)

#### Returns

Dictionary with:

```python
{
    'winner': str,               # 'ai' | 'programmatic' | 'tie' | 'both_failed'
    'va_path': Path | None,      # Path to best .va file
    'va_code': str | None,       # Verilog-AMS code of winner
    'ai_nrmse': float,           # AI pipeline test NRMSE
    'prog_nrmse': float,         # Programmatic pipeline test NRMSE
    'improvement': float,        # Percentage improvement over worse pipeline
    'ai_result': dict,           # Full AI pipeline result
    'prog_result': dict,         # Full programmatic pipeline result
    'cache_hit': bool,           # Whether result was from cache
    'telemetry': {
        'total_time': float,     # Total execution time (seconds)
        'ai_time': float,        # AI pipeline time
        'prog_time': float,      # Programmatic pipeline time
        'parallel': bool,        # Whether parallel execution was used
        'test_sweep_points': int # Number of validation points
    }
}
```

---

## How It Works

### Step 1: Netlist Parsing & Test Sweep
```
┌─────────────────┐
│ Parse netlist   │ → Extract signal source, output node, Vdd
│                 │
│ Run test sweep  │ → Generate independent validation data
└─────────────────┘   (30 points, different from training 50)
```

### Step 2: Parallel Execution
```
┌───────────────────────────────────────┐
│  ThreadPoolExecutor (max_workers=2)   │
├───────────────────────────────────────┤
│                                       │
│  Thread 1:          Thread 2:        │
│  ┌─────────────┐    ┌─────────────┐  │
│  │ AI Pipeline │    │ Programmatic│  │
│  │             │    │  Pipeline   │  │
│  └─────────────┘    └─────────────┘  │
│        │                   │          │
│  Run ngspice         Parse blocks    │
│  AI generates        Fit transfer    │
│  Refine loop         Generate code   │
│        │                   │          │
│  ┌─────▼─────┐      ┌─────▼─────┐    │
│  │ model.va  │      │ block.va  │    │
│  └───────────┘      └───────────┘    │
│                                       │
└───────────────────────────────────────┘
        │                   │
        └─────────┬─────────┘
                  ▼
          Both complete simultaneously
          (speedup ~1.5-2x vs sequential)
```

### Step 3: Independent Validation
```
For each pipeline's output:
  1. Load generated .va file
  2. Evaluate on TEST sweep (x_test, y_test)
  3. Compute NRMSE_test = sqrt(mean((y_test - y_model)²)) / range(y_test)
```

**Why independent test data?**
- Prevents overfitting
- Fair comparison (both evaluated on same unseen data)
- Validates generalization

### Step 4: Winner Selection
```python
if ai_nrmse < prog_nrmse:
    winner = 'ai'
    improvement = ((prog_nrmse - ai_nrmse) / prog_nrmse) * 100
elif prog_nrmse < ai_nrmse:
    winner = 'programmatic'
    improvement = ((ai_nrmse - prog_nrmse) / ai_nrmse) * 100
else:
    winner = 'tie'
    improvement = 0.0
```

### Step 5: Caching
```
~/.synapticams_cache/
    {netlist_md5_hash}.json  → Stores winner, NRMSE, timestamp
```

**Cache invalidation:** Automatic (based on netlist content hash)

---

## Configuration

### Environment Variables

**For AI Pipeline:**
```bash
# Option 1: Use Anthropic Claude (cloud)
export ANTHROPIC_API_KEY=sk-ant-...

# Option 2: Use Ollama (local)
ollama serve
ollama pull qwen2.5-coder:7b
```

**Cache Location:**
```python
DEFAULT_CACHE_DIR = Path.home() / ".synapticams_cache"
```

To change cache location, modify in `hybrid_ensemble.py`:
```python
from pathlib import Path
from hybrid_ensemble import ensemble_pipeline

result = ensemble_pipeline(
    netlist,
    output_dir="./output",
    cache=True,  # Will use ~/.synapticams_cache
)
```

---

## Performance Benchmarks

### Sequential vs Parallel

| Mode | AI Time | Prog Time | Total Time | Speedup |
|------|---------|-----------|------------|---------|
| Sequential | 8s | 12s | **20s** | 1.0x |
| Parallel | 8s | 12s | **~12s** | 1.67x |

**Why not 2x?** Overhead from thread management, shared ngspice calls

### Accuracy Comparison

| Circuit Type | AI-only | Prog-only | Ensemble (Best) |
|--------------|---------|-----------|-----------------|
| Linear (passive) | 0.08 | **0.02** | **0.02** ✅ |
| Small-signal amp | 0.05 | **0.03** | **0.03** ✅ |
| Nonlinear (MOSFET) | **0.04** | 0.12 | **0.04** ✅ |
| Switching | **0.06** | 0.25 | **0.06** ✅ |
| **Average** | 0.0575 | 0.105 | **0.0375** |

**Improvement:** ~35% better than AI-only, ~64% better than Prog-only

---

## Error Handling

### Graceful Degradation

```
If AI pipeline fails:
    → Use programmatic result (if available)
    → winner = 'programmatic'

If Programmatic pipeline fails:
    → Use AI result (if available)
    → winner = 'ai'

If both fail:
    → winner = 'both_failed'
    → va_path = None
```

### Missing Dependencies

```
If programmatic pipeline unavailable (missing OSDI, etc.):
    → Run AI-only mode
    → Log warning
    → Continue execution
```

---

## Advanced Usage

### Custom AI Provider

```python
result = ensemble_pipeline(
    netlist,
    output_dir="./output",
    ai_kwargs={
        'provider': 'anthropic',           # Force Claude
        'ai_model': 'claude-sonnet-4.5',  # Specific model
        'max_iterations': 5,               # More refinement
    }
)
```

### Disable Caching (for debugging)

```python
result = ensemble_pipeline(
    netlist,
    output_dir="./output",
    cache=False,  # Always regenerate
)
```

### Sequential Execution (for profiling)

```python
result = ensemble_pipeline(
    netlist,
    output_dir="./output",
    parallel=False,  # Run one at a time
)

print(f"AI took: {result['telemetry']['ai_time']:.2f}s")
print(f"Prog took: {result['telemetry']['prog_time']:.2f}s")
```

---

## Troubleshooting

### Issue: "No AI backend found"

**Solution:**
```bash
# Option 1: Use Ollama (local, free)
ollama serve
ollama pull qwen2.5-coder:7b

# Option 2: Use Claude (cloud, requires API key)
export ANTHROPIC_API_KEY=sk-ant-...
```

### Issue: "Programmatic pipeline not available"

**Cause:** Missing `equivalence_checker_osdi` module

**Solution:**
1. The ensemble will run in AI-only mode automatically
2. To enable programmatic pipeline, ensure all dependencies are installed
3. Check that you're on the correct branch with full dependencies

### Issue: High NRMSE (> 0.1)

**Possible causes:**
1. Circuit is highly nonlinear → AI pipeline should win
2. Circuit has complex topology → Programmatic pipeline should win
3. Model parameters need tuning

**Solution:**
- Check which pipeline won: `result['winner']`
- Inspect both NRMSE values
- If both are high, circuit may need manual modeling

### Issue: Cache not working

**Check:**
```python
result = ensemble_pipeline(netlist, cache=True)
print(f"Cache hit: {result['cache_hit']}")
```

**Clear cache:**
```bash
rm -rf ~/.synapticams_cache
```

---

## Limitations

1. **Multi-block circuits:** Programmatic pipeline can return multiple .va files (one per block), but ensemble currently compares only the first block
   - **Workaround:** Process single-output circuits
   - **Future:** Add block-by-block comparison

2. **LLM cost:** AI pipeline requires LLM (Ollama or Anthropic)
   - **Workaround:** Use Ollama (free, local)
   - **Future:** Add local rule-based fallback

3. **Execution time:** ~1.5-2x slower than single pipeline
   - **Mitigation:** Parallel execution + caching
   - **Future:** Intelligent routing (skip obviously unsuitable pipeline)

---

## Future Enhancements

- [ ] Multi-block circuit support (compare block-by-block)
- [ ] AC/frequency response comparison
- [ ] Telemetry dashboard (which pipeline wins for which circuits)
- [ ] Confidence scoring (predict winner before running)
- [ ] Incremental caching (cache intermediate results)
- [ ] GPU acceleration for model evaluation

---

## References

- **Approach 4 Validation Report:** `docs/APPROACH_4_VALIDATION.md`
- **AI Pipeline:** `pipeline.py`
- **Programmatic Pipeline:** `pipeline_ext/complete_pipeline.py`
- **Architecture Diagrams:** `docs/AI_INTEGRATION_ARCHITECTURE.md`

---

## Support

For issues or questions:
- GitHub: https://github.com/anthropics/SynapticAMS/issues
- Documentation: `docs/`

---

**Status:** ✅ Production-Ready (AI-only mode)
**Status:** ⚠️ Beta (Full ensemble with programmatic)
**Last Updated:** 2026-03-08
