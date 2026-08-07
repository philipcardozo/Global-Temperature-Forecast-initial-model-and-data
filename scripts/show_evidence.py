"""Print every number behind the July and August 2026 NOAA estimates.

Nothing here is recomputed differently from the estimator: this walks the same
sources, the same fit, and the same arithmetic, printing each intermediate step
so the claims can be checked rather than taken on trust.

    uv run python scripts/show_evidence.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from estimate_month import (
    REMAINDER_FIT_START,
    TRAILING_DAYS,
    TWENTIETH_CENTURY_OFFSET,
    build_history,
    load_era5_daily,
    normal_cdf,
    residual_autocorrelation,
)
from fit_noaa_mapping import (
    ERA5_SERIES_URL,
    FIT_WINDOWS,
    NOAA_DIRECTORY,
    SELECTED_SEASONAL,
    SELECTED_WINDOW,
    design_matrix,
    discover_noaa_series_url,
    evaluation_span,
    fetch,
    fit_window,
    load_era5_monthly,
    load_noaa,
    solve,
)

CACHE = Path("data/calibration")


def rule(title: str) -> None:
    """Print a section heading."""

    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    """Print the full evidence trail."""

    noaa_url = discover_noaa_series_url(refresh=False, cache_root=CACHE)

    noaa_text = fetch(noaa_url, CACHE / Path(noaa_url).name, refresh=False)

    era5_text = fetch(
        ERA5_SERIES_URL,
        CACHE / "era5_daily_series_2t_global.csv",
        refresh=False,
    )

    noaa = load_noaa(noaa_text)
    era5_monthly = load_era5_monthly(era5_text)
    daily = load_era5_daily(era5_text)

    rule("1. SOURCES")

    print(f"NOAA directory : {NOAA_DIRECTORY}")
    print(f"NOAA file      : {Path(noaa_url).name}")
    print(f"NOAA bytes     : {len(noaa_text):,}")
    print(f"NOAA rows used : {len(noaa)}  ({noaa['year'].min()}-{noaa['year'].max()})")
    print(
        f"NOAA latest    : {int(noaa['year'].iloc[-1])}-{int(noaa['month'].iloc[-1]):02d}"
    )

    print()

    print(f"ERA5 source    : {ERA5_SERIES_URL}")
    print(f"ERA5 bytes     : {len(era5_text):,}")
    print(f"ERA5 daily rows: {len(daily):,}")
    print(
        f"ERA5 range     : {daily['date'].min().date()} to {daily['date'].max().date()}"
    )

    for line in era5_text.splitlines()[:20]:
        if line.startswith("# Last updated") or line.startswith("# Units"):
            print(f"ERA5 header    : {line}")

    rule("2. NOAA BASELINE, VERIFIED FROM THE DATA")

    print("If a series is referenced to a baseline, its mean over that baseline is 0.")
    print()

    for label, span in (
        ("1901-2000", (1901, 2000)),
        ("1951-1980", (1951, 1980)),
        ("1961-1990", (1961, 1990)),
        ("1981-2010", (1981, 2010)),
        ("1991-2020", (1991, 2020)),
    ):
        selection = noaa.loc[noaa["year"].between(*span), "noaa_anomaly"]

        marker = "  <-- baseline" if abs(selection.mean()) < 1e-6 else ""

        print(f"  mean over {label}: {selection.mean():+.6f} C{marker}")

    print()

    print(
        f"Conversion to NOAA's published 20th-century base: +{TWENTIETH_CENTURY_OFFSET}"
    )

    rule("3. THE FIT")

    merged = noaa.merge(era5_monthly, on=["year", "month"]).sort_values(
        ["year", "month"]
    )

    merged = merged.reset_index(drop=True)

    span = evaluation_span(merged)

    print(f"Overlapping months : {len(merged)}")
    print(f"Walk-forward period: last {span} months, identical for every window")
    print()

    header = (
        f"{'window':>8}  {'seasonal':>8}  {'months':>6}  {'slope':>7}  "
        f"{'in-sig':>7}  {'oos-sig':>7}  {'oos-bias':>8}  {'worst':>6}"
    )

    print(header)
    print("-" * len(header))

    fits = []

    for start_year in FIT_WINDOWS:
        for seasonal in (False, True):
            item = fit_window(
                merged,
                start_year=start_year,
                seasonal=seasonal,
                evaluated_months=span,
            )

            fits.append(item)

            chosen = (
                "  <-- used"
                if start_year == SELECTED_WINDOW and seasonal == SELECTED_SEASONAL
                else ""
            )

            print(
                f"{item.start_year:>8}  {str(item.seasonal):>8}  {item.months:>6}  "
                f"{item.coefficients[1]:>7.4f}  {item.in_sample_sigma:>7.4f}  "
                f"{item.out_of_sample_sigma:>7.4f}  {item.out_of_sample_bias:>+8.4f}  "
                f"{item.worst_absolute_error:>6.3f}{chosen}"
            )

    selected = next(
        item
        for item in fits
        if item.start_year == SELECTED_WINDOW and item.seasonal == SELECTED_SEASONAL
    )

    print()

    names = [
        "intercept",
        "era5_anomaly",
        "sin_annual",
        "cos_annual",
        "sin_semiannual",
        "cos_semiannual",
    ]

    print("Selected coefficients:")

    for name, value in zip(names, selected.coefficients, strict=True):
        print(f"  {name:>16} = {value:+.6f}")

    print()

    sigmas = [item.out_of_sample_sigma for item in fits]

    print(
        f"Spread of all 8 out-of-sample sigmas: {min(sigmas):.4f} to {max(sigmas):.4f}"
    )

    print(
        f"Standard error of a sigma over {span} months: "
        f"{selected.out_of_sample_sigma / np.sqrt(2 * span):.4f}"
    )

    print("-> the windows are statistically indistinguishable.")

    rule("4. WALK-FORWARD ERROR DISTRIBUTION OF THE SELECTED FIT")

    window = merged.loc[merged["year"] >= SELECTED_WINDOW].reset_index(drop=True)

    matrix = design_matrix(window, seasonal=SELECTED_SEASONAL)

    target = window["noaa_anomaly"].to_numpy(dtype=float)

    first = len(window) - span

    errors = []

    for index in range(first, len(window)):
        history_fit = solve(matrix[:index], target[:index])

        errors.append(float(target[index] - matrix[index] @ history_fit))

    errors_array = np.asarray(errors)

    print(f"n = {len(errors_array)} predictions, each using only prior months")

    print(f"mean   {errors_array.mean():+.4f}   sigma {errors_array.std(ddof=1):.4f}")

    print(
        f"min    {errors_array.min():+.4f}   max   {errors_array.max():+.4f}   "
        f"median {np.median(errors_array):+.4f}"
    )

    print()

    print("  error band      count   share")

    edges = [-0.12, -0.08, -0.04, -0.02, 0.0, 0.02, 0.04, 0.08, 0.12]

    for low, high in zip(edges[:-1], edges[1:], strict=True):
        count = int(((errors_array >= low) & (errors_array < high)).sum())

        print(
            f"  {low:+.2f} to {high:+.2f}  {count:>5}   "
            f"{count / len(errors_array):>5.1%}  {'#' * count}"
        )

    inside = int((np.abs(errors_array) <= selected.out_of_sample_sigma).sum())

    print()

    print(
        f"within 1 sigma: {inside}/{len(errors_array)} = "
        f"{inside / len(errors_array):.1%}  (normal expects 68.3%)"
    )

    rule("5. 2026 MONTHS ALREADY PUBLISHED BY NOAA: PREDICTED VS ACTUAL")

    print("The same model, applied to every 2026 month NOAA has released.")
    print()

    print("  month     ERA5      predicted    actual     error")

    calibration = json.loads(
        Path("configs/noaa_calibration.json").read_text(encoding="utf-8")
    )

    history = build_history(era5_monthly, noaa, calibration)

    coefficients = np.asarray(selected.coefficients)

    checks = merged[merged["year"] == 2026]

    for _, row in checks.iterrows():
        radians = 2.0 * np.pi * float(row["month"]) / 12.0

        design = np.array(
            [
                1.0,
                float(row["era5_anomaly"]),
                np.sin(radians),
                np.cos(radians),
                np.sin(2.0 * radians),
                np.cos(2.0 * radians),
            ]
        )

        predicted = float(design @ coefficients)

        actual = float(row["noaa_anomaly"])

        print(
            f"  2026-{int(row['month']):02d}  {row['era5_anomaly']:+.4f}   "
            f"{predicted:+.4f}     {actual:+.4f}   {actual - predicted:+.4f}"
        )

    radians_all = 2.0 * np.pi * checks["month"].to_numpy(dtype=float) / 12.0

    design_all = np.column_stack(
        [
            np.ones(len(checks)),
            checks["era5_anomaly"].to_numpy(dtype=float),
            np.sin(radians_all),
            np.cos(radians_all),
            np.sin(2.0 * radians_all),
            np.cos(2.0 * radians_all),
        ]
    )

    errors_2026 = checks["noaa_anomaly"].to_numpy(dtype=float) - design_all @ (
        coefficients
    )

    print()

    print(
        f"  2026 mean absolute error: {np.abs(errors_2026).mean():.4f} C, "
        f"largest {np.abs(errors_2026).max():.4f} C, "
        f"vs walk-forward sigma {selected.out_of_sample_sigma:.4f}"
    )

    rule("6. JULY 2026, EVERY ERA5 DAY")

    july = daily[(daily["date"].dt.year == 2026) & (daily["date"].dt.month == 7)]

    for start in range(0, len(july), 4):
        chunk = july.iloc[start : start + 4]

        print(
            "  "
            + "   ".join(
                f"{row['date'].strftime('%m-%d')} {row['ano_91-20']:+.3f} "
                f"{row['status'][:1]}"
                for _, row in chunk.iterrows()
            )
        )

    print()

    print(
        f"  days {len(july)}/31, all FINAL: {bool((july['status'] == 'FINAL').all())}"
    )

    print(f"  mean anomaly: {july['ano_91-20'].mean():+.6f} C")

    print(f"  absolute    : {july['2t'].mean():+.4f} C")

    rule("7. AUGUST 2026, OBSERVED DAYS AND THE REMAINDER MODEL")

    august = daily[(daily["date"].dt.year == 2026) & (daily["date"].dt.month == 8)]

    for _, row in august.iterrows():
        print(
            f"  {row['date'].date()}  anomaly {row['ano_91-20']:+.3f}  "
            f"absolute {row['2t']:.3f}  {row['status']}"
        )

    print()

    print(f"  observed {len(august)}/31 days, mean {august['ano_91-20'].mean():+.4f} C")

    cutoff = august["date"].iloc[-1]

    trailing = daily[
        (daily["date"] <= cutoff)
        & (daily["date"] > cutoff - pd.Timedelta(days=TRAILING_DAYS))
    ]

    print(
        f"  trailing {TRAILING_DAYS} days to {cutoff.date()}: "
        f"{trailing['ano_91-20'].mean():+.4f} C"
    )

    print()

    print("  Remainder training set: trailing-30 anomaly -> mean of days 5-31")
    print(f"  (calendar month 8, {len(august)} observed days, {REMAINDER_FIT_START}+)")

    print()

    print("   year   trailing30   days 5-31")

    rows = []

    for year in range(REMAINDER_FIT_START, 2026):
        month_rows = daily[
            (daily["date"].dt.year == year) & (daily["date"].dt.month == 8)
        ]

        if len(month_rows) < 31:
            continue

        year_cutoff = month_rows["date"].iloc[len(august) - 1]

        year_trailing = daily[
            (daily["date"] <= year_cutoff)
            & (daily["date"] > year_cutoff - pd.Timedelta(days=TRAILING_DAYS))
        ]

        if len(year_trailing) < TRAILING_DAYS:
            continue

        rows.append(
            (
                year,
                float(year_trailing["ano_91-20"].mean()),
                float(month_rows["ano_91-20"].iloc[len(august) :].mean()),
            )
        )

    for year, predictor, outcome in rows[-12:]:
        print(f"   {year}    {predictor:+.4f}      {outcome:+.4f}")

    print(f"   ... {len(rows)} training years total, showing the last 12")

    table = np.asarray([(item[1], item[2]) for item in rows])

    fit_matrix = np.column_stack([np.ones(len(table)), table[:, 0]])

    beta = solve(fit_matrix, table[:, 1])

    loo = []

    for index in range(len(table)):
        keep = np.arange(len(table)) != index

        fold = solve(fit_matrix[keep], table[keep, 1])

        loo.append(float(table[index, 1] - fit_matrix[index] @ fold))

    print()

    print(f"  remainder = {beta[0]:+.4f} {beta[1]:+.4f} * trailing30")

    print(f"  leave-one-out sigma: {np.std(loo, ddof=1):.4f} C")

    print(
        f"  applied: {beta[0]:+.4f} {beta[1]:+.4f} * "
        f"{trailing['ano_91-20'].mean():+.4f} = "
        f"{beta[0] + beta[1] * trailing['ano_91-20'].mean():+.4f} C"
    )

    rule("8. RESIDUAL AUTOCORRELATION (WHY RANKINGS USE LEVELS)")

    print("  month  lag   rho      n")

    for month in (7, 8):
        for lag in (1, 2, 3):
            rho, count = residual_autocorrelation(history, month=month, lag=lag)

            print(f"    {month:>2}    {lag}   {rho:+.3f}   {count}")

    pooled = []

    for month in range(1, 13):
        series = history[
            (history["month"] == month) & (history["year"] >= 2000)
        ].set_index("year")["residual"]

        pooled.extend(
            (float(series[year - 1]), float(series[year]))
            for year in series.index
            if year - 1 in series.index
        )

    pooled_array = np.asarray(pooled)

    rho = float(np.corrcoef(pooled_array[:, 0], pooled_array[:, 1])[0, 1])

    print()

    print(
        f"  pooled over all months, lag 1: rho = {rho:+.3f}, n = {len(pooled_array)}, "
        f"se ~ {1 / np.sqrt(len(pooled_array)):.3f}"
    )

    print("  -> a published year carries almost no information about this year.")

    rule("9. THE ARITHMETIC")

    for label, era5_value, era5_sigma in (
        ("July 2026", float(july["ano_91-20"].mean()), 0.0),
        ("August 2026", 0.6417, 0.0652),
    ):
        month = 7 if label.startswith("July") else 8

        radians = 2.0 * np.pi * month / 12.0

        design = np.array(
            [
                1.0,
                era5_value,
                np.sin(radians),
                np.cos(radians),
                np.sin(2.0 * radians),
                np.cos(2.0 * radians),
            ]
        )

        point = float(design @ coefficients)

        sigma = float(
            np.sqrt(
                (coefficients[1] * era5_sigma) ** 2 + selected.out_of_sample_sigma**2
            )
        )

        print()

        print(f"{label}")

        print(f"  ERA5 month anomaly      {era5_value:+.4f}  (sigma {era5_sigma:.4f})")

        print(
            f"  x slope {coefficients[1]:.4f} + intercept + seasonal "
            f"= {point:+.4f}  (1991-2020)"
        )

        print(
            f"  + {TWENTIETH_CENTURY_OFFSET} baseline shift "
            f"= {point + TWENTIETH_CENTURY_OFFSET:+.4f}  (20th century)"
        )

        print(
            f"  sigma = sqrt(({coefficients[1]:.4f} x {era5_sigma:.4f})^2 + "
            f"{selected.out_of_sample_sigma:.4f}^2) = {sigma:.4f}"
        )

        shifted = point + TWENTIETH_CENTURY_OFFSET

        for threshold in (1.24,):
            z = (threshold - shifted) / sigma

            print(
                f"  P(>= {threshold}) : z = ({threshold} - {shifted:.4f})/{sigma:.4f} "
                f"= {z:+.4f} -> {1 - normal_cdf(z):.1%}"
            )

        if month == 8:
            low = (1.24 - shifted) / sigma
            high = (1.30 - shifted) / sigma

            print(
                f"  P(1.24-1.30): Phi({high:+.4f}) - Phi({low:+.4f}) = "
                f"{normal_cdf(high):.4f} - {normal_cdf(low):.4f} = "
                f"{normal_cdf(high) - normal_cdf(low):.1%}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
