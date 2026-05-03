# Development Documentation

This directory contains historical documentation created during the development and debugging process.

## Documents

### `TRANSIENT_VALIDATION_FIX_COMPLETE.md`
Complete documentation of the transient validation fix for AC-coupled circuits.

**Contents:**
- Problem statement (DC sweep on AC circuit)
- Solution implementation (auto-detect circuit type)
- Code changes in `demo_warmstart_validated.py` and `equivalence_checker_osdi.py`
- Testing and validation results

---

### `PIPELINE_RUN_SUMMARY.md`
Summary of a complete pipeline run with validation metrics.

**Contents:**
- Pipeline execution timeline
- Step-by-step progress
- Validation results for each pass
- Error messages and resolutions

---

### `HOW_TO_FIX_EVERYTHING.md`
Comprehensive guide to all the fixes applied to the pipeline.

**Contents:**
- SPICE netlist AC signal fix
- Transient validation implementation
- OpenVAF compatibility post-processing
- Anthropic API connection
- Variable declaration issues

---

### `SOLUTION_SUMMARY.md`
High-level summary of the complete solution.

**Contents:**
- Overall architecture
- Key features implemented
- Results and performance metrics
- Known limitations
- Future improvements

## Reading Order

For best understanding, read in this order:

1. **SOLUTION_SUMMARY.md** - Get the big picture
2. **HOW_TO_FIX_EVERYTHING.md** - Understand all the fixes
3. **TRANSIENT_VALIDATION_FIX_COMPLETE.md** - Deep dive into validation
4. **PIPELINE_RUN_SUMMARY.md** - See actual execution results

## Note

These documents were created during development and may contain outdated information. For the most current documentation, see the main `README.md` in the parent directory.
