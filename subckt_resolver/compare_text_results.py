#!/usr/bin/env python3
"""
Compare hierarchical vs flattened simulation text results
"""

def parse_results(filename):
    """Parse ngspice print output"""
    with open(filename, 'r') as f:
        lines = f.readlines()

    # Skip header, find data start
    data = []
    in_data = False
    for line in lines:
        if line.startswith('Index'):
            in_data = True
            continue
        if in_data and line.strip().startswith('---'):
            continue
        if in_data and line.strip():
            parts = line.split()
            if len(parts) >= 5 and parts[0].isdigit():
                # Index, time, v(d_in), v(clk_in), v(q1)...
                try:
                    idx = int(parts[0])
                    time = float(parts[1])
                    d_in = float(parts[2])
                    clk_in = float(parts[3])
                    q1 = float(parts[4])
                    data.append((idx, time, d_in, clk_in, q1))
                except:
                    pass
    return data

def main():
    print("=" * 80)
    print("COMPARING HIERARCHICAL vs FLATTENED SIMULATION RESULTS")
    print("=" * 80)

    hier_data = parse_results('hierarchical_results.txt')
    flat_data = parse_results('flattened_results.txt')

    print(f"\nHierarchical: {len(hier_data)} data points")
    print(f"Flattened:    {len(flat_data)} data points")

    if len(hier_data) != len(flat_data):
        print("\n⚠ WARNING: Different number of data points!")
        return

    # Compare values
    max_diff_q1 = 0
    total_diff = 0
    mismatches = 0

    print("\n" + "=" * 80)
    print("SAMPLE COMPARISON (first 20 points)")
    print("=" * 80)
    print(f"{'Index':<8} {'Time(ns)':<14} {'Hier Q1':<14} {'Flat Q1':<14} {'Difference':<14}")
    print("-" * 80)

    for i in range(min(20, len(hier_data))):
        idx_h, time_h, din_h, clk_h, q1_h = hier_data[i]
        idx_f, time_f, din_f, clk_f, q1_f = flat_data[i]

        diff_q1 = abs(q1_h - q1_f)
        max_diff_q1 = max(max_diff_q1, diff_q1)
        total_diff += diff_q1

        if diff_q1 > 1e-12:
            mismatches += 1

        if i < 20:
            print(f"{idx_h:<8} {time_h*1e9:<14.6f} {q1_h:<14.6e} {q1_f:<14.6e} {diff_q1:<14.6e}")

    # Check all points
    print("\n" + "=" * 80)
    print("COMPLETE COMPARISON (all {} points)".format(len(hier_data)))
    print("=" * 80)

    for i in range(len(hier_data)):
        idx_h, time_h, din_h, clk_h, q1_h = hier_data[i]
        idx_f, time_f, din_f, clk_f, q1_f = flat_data[i]

        diff_q1 = abs(q1_h - q1_f)
        max_diff_q1 = max(max_diff_q1, diff_q1)
        total_diff += diff_q1

        if diff_q1 > 1e-12:
            mismatches += 1

    avg_diff = total_diff / len(hier_data)

    print(f"\nMaximum difference in Q1: {max_diff_q1:.6e} V")
    print(f"Average difference in Q1: {avg_diff:.6e} V")
    print(f"Points with diff > 1e-12: {mismatches}")

    # Verdict
    print("\n" + "=" * 80)
    print("VERIFICATION RESULT")
    print("=" * 80)

    if max_diff_q1 < 1e-10:
        print("\n✓ SUCCESS: Hierarchical and flattened simulations produce IDENTICAL results!")
        print(f"  Maximum difference: {max_diff_q1:.6e} V (< 0.1 nV)")
        print(f"  This confirms the flattening tool correctly preserved circuit behavior.")
    else:
        print(f"\n✗ MISMATCH: Maximum difference {max_diff_q1:.6e} V exceeds tolerance")

    print("\n" + "=" * 80)

if __name__ == '__main__':
    main()
