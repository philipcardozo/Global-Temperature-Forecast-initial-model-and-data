"""Estimate a NOAA monthly value from observed ERA5 days, with uncertainty.

The climatology-only baseline: month-to-date observed ERA5 anomaly, plus an
empirically fitted estimate of the unobserved remainder, mapped through the
ERA5-to-NOAA transformation in configs/noaa_calibration.json.

This uses no forecast-model data at all. It is the baseline any forecast layer
has to beat, and the honest answer for a month that is already complete.

    uv run python scripts/estimate_month.py --year 2026 --month 7
"""

from __future__ import annotations

import argparse
import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from fit_noaa_mapping import (
    ERA5_SERIES_URL,
    discover_noaa_series_url,
    fetch,
    load_era5_monthly,
    load_noaa,
)

# NOAAGlobalTemp v6.1 anomalies are referenced to 1991-2020. NOAA's published
# monthly reports quote the 20th century average instead.
TWENTIETH_CENTURY_OFFSET = 0.6121

# Years used to fit the unobserved-remainder model. Recent enough that the
# residual spread reflects current variability.
REMAINDER_FIT_START = 1980

TRAILING_DAYS = 30


@dataclass(frozen=True, slots=True)
class MonthEstimate:
    """A predicted NOAA monthly anomaly and its uncertainty."""

    year: int
    month: int
    observed_days: int
    days_in_month: int
    observed_anomaly: float
    remainder_anomaly: float | None
    remainder_sigma: float
    era5_anomaly: float
    era5_sigma: float
    noaa_anomaly: float
    noaa_sigma: float


def load_era5_daily(
    text: str,
) -> pd.DataFrame:
    """Parse the ERA5 daily global-mean series."""

    lines = [line for line in text.splitlines() if not line.startswith("#")]

    frame = pd.read_csv(io.StringIO("\n".join(lines)))

    frame["date"] = pd.to_datetime(frame["date"])

    return frame.sort_values("date").reset_index(drop=True)


def normal_quantile(
    probability: float,
) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation)."""

    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]

    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]

    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]

    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]

    low = 0.02425

    if probability < low:
        q = np.sqrt(-2.0 * np.log(probability))

        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )

    if probability > 1.0 - low:
        return -normal_quantile(1.0 - probability)

    q = probability - 0.5
    r = q * q

    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )


def normal_cdf(
    value: float,
) -> float:
    """Standard normal CDF via the error function."""

    from math import erf, sqrt

    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def fit_remainder_model(
    daily: pd.DataFrame,
    *,
    month: int,
    observed_days: int,
    target_year: int,
) -> tuple[float, float, float, int]:
    """Predict the mean anomaly of a month's unobserved days.

    The predictor is the trailing 30-day anomaly ending on the last observed
    day, which is a better-conditioned estimate of the current state than a
    handful of noisy month-to-date days. Fitted across history for this exact
    calendar month and this exact number of observed days, then scored
    leave-one-out.
    """

    rows: list[tuple[float, float]] = []

    for year in range(REMAINDER_FIT_START, target_year + 1):
        month_rows = daily[
            (daily["date"].dt.year == year) & (daily["date"].dt.month == month)
        ]

        if month_rows.empty:
            continue

        days_in_month = int(month_rows["date"].dt.days_in_month.iloc[0])

        if len(month_rows) < days_in_month:
            continue

        cutoff = month_rows["date"].iloc[observed_days - 1]

        trailing = daily[
            (daily["date"] <= cutoff)
            & (daily["date"] > cutoff - pd.Timedelta(days=TRAILING_DAYS))
        ]

        if len(trailing) < TRAILING_DAYS:
            continue

        remainder = month_rows["ano_91-20"].iloc[observed_days:].mean()

        rows.append(
            (
                float(trailing["ano_91-20"].mean()),
                float(remainder),
            )
        )

    if len(rows) < 20:
        raise RuntimeError(
            f"Only {len(rows)} training years for month {month} "
            f"with {observed_days} observed days."
        )

    table = np.asarray(rows, dtype=float)

    matrix = np.column_stack(
        [
            np.ones(len(table)),
            table[:, 0],
        ]
    )

    target = table[:, 1]

    coefficients, *_ = np.linalg.lstsq(matrix, target, rcond=None)

    # Leave-one-out: refit without each year and predict it.
    errors: list[float] = []

    for index in range(len(table)):
        keep = np.arange(len(table)) != index

        fold, *_ = np.linalg.lstsq(
            matrix[keep],
            target[keep],
            rcond=None,
        )

        errors.append(float(target[index] - matrix[index] @ fold))

    return (
        float(coefficients[0]),
        float(coefficients[1]),
        float(np.std(errors, ddof=1)),
        len(table),
    )


def estimate(
    daily: pd.DataFrame,
    calibration: dict,
    *,
    year: int,
    month: int,
) -> MonthEstimate:
    """Estimate the NOAA anomaly for one month."""

    month_rows = daily[
        (daily["date"].dt.year == year) & (daily["date"].dt.month == month)
    ]

    if month_rows.empty:
        raise RuntimeError(f"No ERA5 days available for {year}-{month:02d}.")

    days_in_month = int(month_rows["date"].dt.days_in_month.iloc[0])

    observed_days = len(month_rows)

    observed_anomaly = float(month_rows["ano_91-20"].mean())

    if observed_days >= days_in_month:
        remainder_anomaly = None
        remainder_sigma = 0.0
        era5_anomaly = observed_anomaly
        era5_sigma = 0.0
    else:
        cutoff = month_rows["date"].iloc[-1]

        trailing = daily[
            (daily["date"] <= cutoff)
            & (daily["date"] > cutoff - pd.Timedelta(days=TRAILING_DAYS))
        ]

        intercept, slope, remainder_sigma, _ = fit_remainder_model(
            daily,
            month=month,
            observed_days=observed_days,
            target_year=year - 1,
        )

        remainder_anomaly = intercept + slope * float(trailing["ano_91-20"].mean())

        weight = (days_in_month - observed_days) / days_in_month

        era5_anomaly = (
            observed_days * observed_anomaly
            + (days_in_month - observed_days) * remainder_anomaly
        ) / days_in_month

        era5_sigma = weight * remainder_sigma

    selected = calibration["selected"]

    coefficients = np.asarray(selected["coefficients"], dtype=float)

    radians = 2.0 * np.pi * month / 12.0

    design = np.array(
        [
            1.0,
            era5_anomaly,
            np.sin(radians),
            np.cos(radians),
            np.sin(2.0 * radians),
            np.cos(2.0 * radians),
        ]
    )

    if not selected["seasonal"]:
        design = design[:2]

    noaa_anomaly = float(design @ coefficients)

    transformation_sigma = float(selected["out_of_sample_sigma"])

    noaa_sigma = float(
        np.sqrt((coefficients[1] * era5_sigma) ** 2 + transformation_sigma**2)
    )

    return MonthEstimate(
        year=year,
        month=month,
        observed_days=observed_days,
        days_in_month=days_in_month,
        observed_anomaly=observed_anomaly,
        remainder_anomaly=remainder_anomaly,
        remainder_sigma=remainder_sigma,
        era5_anomaly=era5_anomaly,
        era5_sigma=era5_sigma,
        noaa_anomaly=noaa_anomaly,
        noaa_sigma=noaa_sigma,
    )


def build_history(
    era5_monthly: pd.DataFrame,
    noaa: pd.DataFrame,
    calibration: dict,
) -> pd.DataFrame:
    """Join both series and attach the transformation residual per month."""

    merged = noaa.merge(
        era5_monthly,
        on=["year", "month"],
    ).sort_values(["year", "month"])

    merged = merged.reset_index(drop=True)

    selected = calibration["selected"]

    coefficients = np.asarray(selected["coefficients"], dtype=float)

    radians = 2.0 * np.pi * merged["month"].to_numpy(dtype=float) / 12.0

    matrix = np.column_stack(
        [
            np.ones(len(merged)),
            merged["era5_anomaly"].to_numpy(dtype=float),
            np.sin(radians),
            np.cos(radians),
            np.sin(2.0 * radians),
            np.cos(2.0 * radians),
        ]
    )

    if not selected["seasonal"]:
        matrix = matrix[:, :2]

    merged["residual"] = merged["noaa_anomaly"].to_numpy(dtype=float) - matrix @ (
        coefficients
    )

    return merged


def residual_autocorrelation(
    history: pd.DataFrame,
    *,
    month: int,
    lag: int,
    since: int = 2000,
) -> tuple[float, int]:
    """Same-month year-to-year correlation of the transformation residual.

    This is the evidence for treating a published year as a plain constant
    when computing rankings. If it were near 1, knowing last year's residual
    would tell you most of this year's, and a comparison should be anchored.
    It is near 0, so it should not.
    """

    residuals = history[history["month"] == month].set_index("year")["residual"]

    pairs = [
        (float(residuals[year - lag]), float(residuals[year]))
        for year in residuals.index
        if year - lag in residuals.index and year >= since
    ]

    if len(pairs) < 10:
        return float("nan"), len(pairs)

    table = np.asarray(pairs, dtype=float)

    return float(np.corrcoef(table[:, 0], table[:, 1])[0, 1]), len(table)


def report(
    item: MonthEstimate,
    noaa: pd.DataFrame,
    history: pd.DataFrame,
) -> None:
    """Print one month's distribution."""

    name = pd.Timestamp(year=item.year, month=item.month, day=1).strftime("%B %Y")

    print(f"=== {name} ===")

    print(
        f"ERA5 observed:      {item.observed_days}/{item.days_in_month} days, "
        f"{item.observed_anomaly:+.4f} C"
    )

    if item.remainder_anomaly is not None:
        print(
            f"Remaining {item.days_in_month - item.observed_days:2d} days:  "
            f"{item.remainder_anomaly:+.4f} C predicted "
            f"(LOO sigma {item.remainder_sigma:.4f})"
        )

    print(
        f"ERA5 month:         {item.era5_anomaly:+.4f} C  (sigma {item.era5_sigma:.4f})"
    )

    print()

    print(
        f"NOAA estimate:      {item.noaa_anomaly:+.4f} C  "
        f"+/- {item.noaa_sigma:.4f} (1 sigma), base 1991-2020"
    )

    print(
        f"                    {item.noaa_anomaly + TWENTIETH_CENTURY_OFFSET:+.4f} C  "
        f"in NOAA's published 20th-century base"
    )

    print()

    print("  quantile      1991-2020      20th century")

    for probability in (0.05, 0.25, 0.50, 0.75, 0.95):
        value = item.noaa_anomaly + item.noaa_sigma * normal_quantile(probability)

        print(
            f"  {probability:>6.0%}       {value:+.4f} C       "
            f"{value + TWENTIETH_CENTURY_OFFSET:+.4f} C"
        )

    ranks = noaa[(noaa["month"] == item.month) & (noaa["year"] < item.year)]

    ranks = ranks.sort_values("noaa_anomaly", ascending=False).head(5)

    print()

    # Published years are known constants, so this is a plain tail probability
    # of the estimate. An earlier version anchored on each reference year and
    # carried its residual across, which assumes the transformation residual
    # persists year to year. It does not: same-month lag-1 to lag-3
    # autocorrelation since 2000 runs -0.21 to +0.15, and pooling every month
    # gives +0.14 with a standard error of 0.06.
    correlations = " ".join(
        f"lag{lag}="
        f"{residual_autocorrelation(history, month=item.month, lag=lag)[0]:+.2f}"
        for lag in (1, 2, 3)
    )

    print(f"  Residual autocorrelation (why levels, not anchors): {correlations}")

    print()

    print("  Ranking against published years:")

    print("    year   published    P(2026 warmer)")

    probabilities: list[float] = []

    for _, row in ranks.iterrows():
        probability = 1.0 - normal_cdf(
            (float(row["noaa_anomaly"]) - item.noaa_anomaly) / item.noaa_sigma
        )

        probabilities.append(probability)

        print(
            f"    {int(row['year'])}   {row['noaa_anomaly']:+.4f} C   "
            f"{probability:>13.1%}"
        )

    print()

    print(
        f"  P(warmest {pd.Timestamp(2000, item.month, 1):%B} on record) "
        f"= {probabilities[0]:.1%}"
    )

    print()


def main() -> int:
    """Estimate one or more months."""

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--year",
        type=int,
        default=2026,
    )

    parser.add_argument(
        "--month",
        type=int,
        action="append",
        help="Repeatable. Defaults to July and August.",
    )

    parser.add_argument(
        "--calibration",
        default="configs/noaa_calibration.json",
    )

    parser.add_argument(
        "--cache-root",
        default="data/calibration",
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
    )

    arguments = parser.parse_args()

    months = arguments.month or [7, 8]

    cache_root = Path(str(arguments.cache_root))

    refresh = bool(arguments.refresh)

    calibration = json.loads(
        Path(str(arguments.calibration)).read_text(encoding="utf-8")
    )

    daily = load_era5_daily(
        fetch(
            ERA5_SERIES_URL,
            cache_root / "era5_daily_series_2t_global.csv",
            refresh=refresh,
        )
    )

    noaa_url = discover_noaa_series_url(
        refresh=refresh,
        cache_root=cache_root,
    )

    noaa = load_noaa(
        fetch(
            noaa_url,
            cache_root / Path(noaa_url).name,
            refresh=refresh,
        )
    )

    print(f"ERA5 through:  {daily['date'].max().date()}")

    print(
        f"NOAA through:  {int(noaa['year'].iloc[-1])}-{int(noaa['month'].iloc[-1]):02d}"
    )

    print(
        f"Transformation sigma: {calibration['selected']['out_of_sample_sigma']:.4f} C"
    )

    print()

    history = build_history(
        load_era5_monthly(
            fetch(
                ERA5_SERIES_URL,
                cache_root / "era5_daily_series_2t_global.csv",
                refresh=False,
            )
        ),
        noaa,
        calibration,
    )

    for month in months:
        report(
            estimate(
                daily,
                calibration,
                year=int(arguments.year),
                month=int(month),
            ),
            noaa,
            history,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
