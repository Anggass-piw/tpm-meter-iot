#!/usr/bin/env python3
"""Fit a simple linear TPM model from paired, real reference-meter readings."""
import argparse
import csv
import math
import random
import sys
from pathlib import Path

import numpy as np

FEATURES = ("capacitance_pf", "optical_raw", "temperature_c")
TARGET = "reference_tpm"


def load_data(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    if len(rows) < 10:
        raise ValueError("Perlu sekurangnya 10 baris data nyata; disarankan 20+ dan mencakup rentang sampel/suhu.")
    required = set(FEATURES) | {TARGET}
    missing = required - set(rows[0])
    if missing:
        raise ValueError("Kolom wajib tidak ada: " + ", ".join(sorted(missing)))
    x = np.array([[1.0] + [float(row[name]) for name in FEATURES] for row in rows], dtype=float)
    y = np.array([float(row[TARGET]) for row in rows], dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(y).all() or np.any((y < 0) | (y > 100)):
        raise ValueError("Data mengandung nilai kosong/tidak finite atau TPM di luar 0–100.")
    groups = [row.get("batch_id", "").strip() for row in rows]
    return x, y, groups


def make_folds(n: int, groups: list[str], seed: int = 42):
    nonempty = all(groups)
    if nonempty and len(set(groups)) >= 2:
        unique = list(dict.fromkeys(groups))
        random.Random(seed).shuffle(unique)
        k = min(5, len(unique))
        folds = [[] for _ in range(k)]
        for i, group in enumerate(unique):
            folds[i % k].extend(j for j, value in enumerate(groups) if value == group)
        return folds, True
    indices = list(range(n))
    random.Random(seed).shuffle(indices)
    k = min(5, n)
    folds = [[] for _ in range(k)]
    for i, index in enumerate(indices):
        folds[i % k].append(index)
    return folds, False


def evaluate_cv(x, y, groups):
    folds, grouped = make_folds(len(y), groups)
    actual, predicted = [], []
    all_indices = set(range(len(y)))
    for test in folds:
        train = sorted(all_indices - set(test))
        if not train or not test:
            continue
        coeff = np.linalg.lstsq(x[train], y[train], rcond=None)[0]
        actual.extend(y[test].tolist())
        predicted.extend((x[test] @ coeff).tolist())
    residual = np.asarray(actual) - np.asarray(predicted)
    rmse = float(np.sqrt(np.mean(residual ** 2)))
    denominator = float(np.sum((np.asarray(actual) - np.mean(actual)) ** 2))
    r2 = 1.0 - float(np.sum(residual ** 2)) / denominator if denominator else float("nan")
    return rmse, r2, grouped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path, help="CSV pengukuran nyata berpasangan dengan alat TPM acuan")
    parser.add_argument("--out", type=Path, default=Path("calibration.h"), help="lokasi header C++ yang dihasilkan")
    args = parser.parse_args()
    try:
        x, y, groups = load_data(args.csv)
        coeff = np.linalg.lstsq(x, y, rcond=None)[0]
        rmse, r2, grouped = evaluate_cv(x, y, groups)
    except (OSError, ValueError, np.linalg.LinAlgError) as exc:
        print(f"Gagal: {exc}", file=sys.stderr)
        return 2

    # CAP_PF conversion remains a separate hardware calibration; these are placeholders.
    content = f'''#pragma once
// Generated from paired, real reference-meter data. Still disabled pending sensor calibration.
// Rows={len(y)}, CV_RMSE={rmse:.5f}, CV_R2={r2:.5f}, grouped_by_batch={str(grouped).lower()}
static constexpr bool MODEL_READY = false;
static constexpr float CAP_PF_OFFSET = 0.0f; // TODO: calibrate ADC-to-pF separately
static constexpr float CAP_PF_PER_ADC = 0.0f; // TODO: calibrate ADC-to-pF separately
static constexpr float MODEL_B0 = {coeff[0]:.9g}f;
static constexpr float MODEL_B_CAP_PF = {coeff[1]:.9g}f;
static constexpr float MODEL_B_OPTICAL = {coeff[2]:.9g}f;
static constexpr float MODEL_B_TEMP = {coeff[3]:.9g}f;
static constexpr float TPM_YELLOW_MIN = 20.0f;
static constexpr float TPM_RED_MIN = 24.0f;
'''
    if args.out.name == "calibration.h":
        print("PERINGATAN: koefisien regresi memakai capacitance_pf yang tersedia pada CSV; konstanta konversi ADC-ke-pF di firmware masih nol. Jangan aktifkan firmware sebelum kalibrasi rangkaian itu juga.", file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(content, encoding="utf-8")
    print(f"Model disimpan ke {args.out}; CV RMSE={rmse:.3f}, R2={r2:.3f} (grouped batch={grouped}).")
    if not grouped:
        print("Peringatan: CSV tidak memiliki batch_id lengkap; ulangan dari batch yang sama mungkin tersebar antar fold. Gunakan batch_id untuk validasi yang lebih jujur.", file=sys.stderr)
    print("Koefisien belum merupakan bukti kelayakan alat. Validasi dengan batch sampel terpisah dan alat TPM acuan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
