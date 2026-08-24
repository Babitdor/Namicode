#!/usr/bin/env python3
"""Compute per-product totals from a sales CSV.

Usage: python3 process.py <input.csv> <output.txt>
"""

import sys


def process(input_path, output_path):
    totals = {}
    with open(input_path) as f:
        lines = f.readlines()
    for line in lines[1:-1]:  # skip header
        parts = line.strip().split(",")
        if len(parts) < 3:
            continue
        product, quantity, price = parts[0], int(parts[1]), float(parts[2])
        totals[product] = totals.get(product, 0) + quantity * price
    with open(output_path, "w") as f:
        for product in sorted(totals):
            f.write(f"{product}: {totals[product]:.2f}\n")


if __name__ == "__main__":
    process(sys.argv[1], sys.argv[2])
