#!/usr/bin/env python3
"""Parse ngspice binary raw file and check signal variation"""
import struct
import sys

def parse_raw_file(filename):
    """Parse ngspice binary raw file"""
    with open(filename, 'rb') as f:
        # Skip ASCII header until we find "Binary:"
        header = ""
        while True:
            line = f.readline().decode('ascii', errors='ignore')
            header += line
            if 'Binary:' in line or 'Values:' in line:
                break

        # Extract number of variables and points from header
        num_vars = None
        num_points = None
        var_names = []

        for line in header.split('\n'):
            if 'No. Variables:' in line:
                num_vars = int(line.split(':')[1].strip())
            elif 'No. Points:' in line or 'No. of Data Rows' in line:
                try:
                    num_points = int(line.split(':')[1].strip())
                except:
                    pass
            elif line.strip().startswith('0') and '\t' in line:
                # Variable definition line
                parts = line.strip().split('\t')
                if len(parts) >= 2:
                    var_names.append(parts[1].strip())

        print(f"Variables: {num_vars}, Points: {num_points}")
        print(f"Variable names: {var_names[:10]}...")  # First 10

        # Read binary data (assuming real numbers, 8 bytes each)
        if num_vars and num_points:
            try:
                # Each point has num_vars values
                data = []
                for i in range(min(10, num_points)):  # Just first 10 points
                    point = []
                    for j in range(num_vars):
                        val = struct.unpack('d', f.read(8))[0]
                        point.append(val)
                    data.append(point)

                # Print first few points
                print("\nFirst 10 transient points:")
                print(f"{'Time':>12} {'tx_p_src':>12} {'ch_out_p':>12} {'ctle_outp':>12} {'vga_out':>12} {'final_out':>12}")

                # Find indices (assume time=0, and others by name)
                try:
                    time_idx = 0
                    tx_p_idx = var_names.index('tx_p')
                    ch_p_idx = var_names.index('ch_out_p')
                    ctle_p_idx = var_names.index('ctle_outp')
                    vga_idx = var_names.index('vga_out')
                    final_idx = var_names.index('final_out')

                    for point in data:
                        print(f"{point[time_idx]:12.3e} {point[tx_p_idx]:12.6f} {point[ch_p_idx]:12.6f} {point[ctle_p_idx]:12.6f} {point[vga_idx]:12.6f} {point[final_idx]:12.6f}")
                except ValueError as e:
                    print(f"Error finding variable: {e}")
                    print(f"Available vars: {var_names}")
            except Exception as e:
                print(f"Error reading binary data: {e}")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        parse_raw_file(sys.argv[1])
    else:
        parse_raw_file('/tmp/serdes_rx_integrated.raw')
