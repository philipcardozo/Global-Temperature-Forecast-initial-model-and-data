"""Fit the ERA5 to NOAAGlobalTemp monthly mapping and report the error floor.

Half A of the calibration: how a monthly ERA5 global-mean 2 m temperature
anomaly maps onto the NOAAGlobalTemp monthly published anomaly. Both series
exist for the full historical record, so this needs no forecast data and no
pipeline execution.

The number that matters is the out-of-sample residual standard deviation. It
bounds the accuracy of any NOAA monthly prediction this system can make: no
amount of forecast skill removes it.

    uv run python scripts/fit_noaa_mapping.py
"""

from __future__ import annotations

import argparse
import io
import json
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import urllib3.util.connection

NOAA_VERSION = "v6.1"

NOAA_DIRECTORY = (
    "https://www.ncei.noaa.gov/data/noaa-global-surface-temperature/"
    f"{NOAA_VERSION}/access/timeseries/"
)

# Global land and ocean, pole to pole: the headline monthly product.
NOAA_SERIES_PREFIX = f"aravg.mon.land_ocean.90S.90N.{NOAA_VERSION}"

ERA5_SERIES_URL = "https://sites.ecmwf.int/data/climatepulse/data/series/era5_daily_series_2t_global.csv"

NOAA_MISSING = -999.0

# Windows to fit separately: the ERA5/NOAA relationship is not stationary
# across the pre-satellite, satellite, and modern observing eras.
FIT_WINDOWS = (1940, 1979, 2000, 2015)

OUT_OF_SAMPLE_MONTHS = 120

# See select(): a judgement call among statistically indistinguishable fits.
SELECTED_WINDOW = 2000

SELECTED_SEASONAL = True


@dataclass(frozen=True, slots=True)
class Fit:
    """One fitted mapping and its residual behaviour."""

    start_year: int
    seasonal: bool
    months: int
    coefficients: list[float]
    in_sample_sigma: float
    out_of_sample_sigma: float
    out_of_sample_bias: float
    out_of_sample_months: int
    worst_absolute_error: float


def _prefer_ipv4() -> socket.AddressFamily:
    """Resolve data hosts over IPv4 only.

    ponytail: www.ncei.noaa.gov advertises AAAA records that are unreachable
    from networks without IPv6 transit. curl survives this through Happy
    Eyeballs; urllib3 does not, and connects hang past their own timeout.
    Every source used here serves IPv4. Drop this if urllib3 gains Happy
    Eyeballs, or make it a flag if this ever runs on an IPv6-only host.
    """

    return socket.AF_INET


urllib3.util.connection.allowed_gai_family = _prefer_ipv4


def fetch(
    url: str,
    cache_path: Path,
    *,
    refresh: bool,
) -> str:
    """Download a text resource, caching it under data/."""

    if cache_path.is_file() and not refresh:
        return cache_path.read_text(encoding="utf-8")

    cache_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # NCEI stalls on the default Python user agent.
    response = requests.get(
        url,
        headers={"User-Agent": "global-temperature-forecast/0.1"},
        timeout=120,
    )

    response.raise_for_status()

    cache_path.write_text(
        response.text,
        encoding="utf-8",
    )

    return response.text


def discover_noaa_series_url(
    *,
    refresh: bool,
    cache_root: Path,
) -> str:
    """Find the current NOAAGlobalTemp monthly file.

    The filename embeds the release month, so it changes with every monthly
    publication and cannot be hard-coded.
    """

    listing = fetch(
        NOAA_DIRECTORY,
        cache_root / "noaa_timeseries_listing.html",
        refresh=refresh,
    )

    pattern = re.escape(NOAA_SERIES_PREFIX) + r"\.\d+\.\d{6}\.asc"

    names = sorted(set(re.findall(pattern, listing)))

    if not names:
        raise RuntimeError(
            f"No NOAAGlobalTemp monthly series found under {NOAA_DIRECTORY}"
        )

    return NOAA_DIRECTORY + names[-1]


def load_noaa(
    text: str,
) -> pd.DataFrame:
    """Parse the NOAAGlobalTemp monthly anomaly series."""

    rows: list[tuple[int, int, float]] = []

    for line in text.splitlines():
        fields = line.split()

        if len(fields) < 3:
            continue

        anomaly = float(fields[2])

        if anomaly == NOAA_MISSING:
            continue

        rows.append(
            (
                int(fields[0]),
                int(fields[1]),
                anomaly,
            )
        )

    frame = pd.DataFrame(
        rows,
        columns=["year", "month", "noaa_anomaly"],
    )

    if frame.empty:
        raise RuntimeError("NOAAGlobalTemp series contained no usable rows.")

    return frame


def load_era5_monthly(
    text: str,
) -> pd.DataFrame:
    """Aggregate the ERA5 daily global-mean series to complete months."""

    lines = [line for line in text.splitlines() if not line.startswith("#")]

    frame = pd.read_csv(
        io.StringIO("\n".join(lines)),
    )

    frame["date"] = pd.to_datetime(frame["date"])

    frame["year"] = frame["date"].dt.year
    frame["month"] = frame["date"].dt.month

    frame["days_in_month"] = frame["date"].dt.days_in_month

    grouped = frame.groupby(
        ["year", "month"],
        as_index=False,
    ).agg(
        era5_anomaly=("ano_91-20", "mean"),
        era5_absolute=("2t", "mean"),
        observed_days=("date", "count"),
        expected_days=("days_in_month", "first"),
        preliminary_days=(
            "status",
            lambda values: int((values != "FINAL").sum()),
        ),
    )

    # A partial month is not a monthly mean.
    complete = grouped["observed_days"] == grouped["expected_days"]

    return grouped.loc[complete].reset_index(drop=True)


def design_matrix(
    frame: pd.DataFrame,
    *,
    seasonal: bool,
) -> np.ndarray:
    """Build the regression design matrix.

    The seasonal terms absorb a month-of-year offset between the two products:
    ERA5 and NOAA weight land and ocean differently, and the land/ocean split
    of the global mean has an annual cycle.
    """

    anomaly = frame["era5_anomaly"].to_numpy(dtype=float)

    columns = [
        np.ones_like(anomaly),
        anomaly,
    ]

    if seasonal:
        radians = 2.0 * np.pi * frame["month"].to_numpy(dtype=float) / 12.0

        columns.extend(
            [
                np.sin(radians),
                np.cos(radians),
                np.sin(2.0 * radians),
                np.cos(2.0 * radians),
            ]
        )

    return np.column_stack(columns)


def solve(
    matrix: np.ndarray,
    target: np.ndarray,
) -> np.ndarray:
    """Ordinary least squares."""

    coefficients, *_ = np.linalg.lstsq(
        matrix,
        target,
        rcond=None,
    )

    return np.asarray(coefficients, dtype=float)


def evaluation_span(
    frame: pd.DataFrame,
) -> int:
    """Choose one out-of-sample period every window can be scored over.

    Windows must be compared on identical months. The shortest window sets
    the limit, since it needs enough training months before the first
    prediction to be solvable at all.
    """

    limits = [
        int((frame["year"] >= start_year).sum()) - 4 * parameters
        for start_year in FIT_WINDOWS
        for parameters in (6,)
    ]

    return min(
        OUT_OF_SAMPLE_MONTHS,
        min(limits),
    )


def fit_window(
    frame: pd.DataFrame,
    *,
    start_year: int,
    seasonal: bool,
    evaluated_months: int,
) -> Fit:
    """Fit one window and evaluate it walking forward month by month.

    The walk-forward pass is the honest number: every prediction uses only
    months that were already published when it was made.
    """

    window = frame.loc[frame["year"] >= start_year].reset_index(drop=True)

    matrix = design_matrix(window, seasonal=seasonal)

    target = window["noaa_anomaly"].to_numpy(dtype=float)

    coefficients = solve(matrix, target)

    in_sample = target - matrix @ coefficients

    first_evaluated = len(window) - evaluated_months

    if first_evaluated < matrix.shape[1] + 1:
        raise ValueError(
            f"Window {start_year}+ is too short to score {evaluated_months} months."
        )

    errors: list[float] = []

    for index in range(first_evaluated, len(window)):
        history = solve(
            matrix[:index],
            target[:index],
        )

        errors.append(float(target[index] - matrix[index] @ history))

    out_of_sample = np.asarray(errors, dtype=float)

    return Fit(
        start_year=start_year,
        seasonal=seasonal,
        months=len(window),
        coefficients=[float(value) for value in coefficients],
        in_sample_sigma=float(in_sample.std(ddof=matrix.shape[1])),
        out_of_sample_sigma=float(out_of_sample.std(ddof=1)),
        out_of_sample_bias=float(out_of_sample.mean()),
        out_of_sample_months=int(out_of_sample.size),
        worst_absolute_error=float(np.abs(out_of_sample).max()),
    )


def select(
    fits: list[Fit],
) -> Fit:
    """Return the configured operational fit.

    Every window scores within about 0.004 C of every other, which is inside
    the standard error of an estimated sigma over this many months
    (sigma / sqrt(2n)). There is no evidence favouring any of them, so this is
    a judgement call rather than a search: 2000+ has enough months to be
    stable and is recent enough to reflect the current observing system. The
    seasonal terms are kept because they are nearly free and absorb the
    annual cycle in the land/ocean split.
    """

    for item in fits:
        if item.start_year == SELECTED_WINDOW and item.seasonal == SELECTED_SEASONAL:
            return item

    raise RuntimeError("The configured operational fit was not evaluated.")


def verdict(
    sigma: float,
) -> str:
    """Translate the error floor into a decision."""

    if sigma <= 0.03:
        return "GO: the transformation is tight enough to predict the NOAA value."

    if sigma <= 0.06:
        return (
            "QUALIFIED GO: direction and rough magnitude are predictable; "
            "the exact published value is not."
        )

    return (
        "RETARGET: the ERA5-to-NOAA transformation is looser than the signal. "
        "Predict the ERA5 monthly value or NOAA's rank instead."
    )


def main() -> int:
    """Fit the mapping and write the calibration artifact."""

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download the source series instead of using the cache.",
    )

    parser.add_argument(
        "--cache-root",
        default="data/calibration",
        help="Directory for cached source downloads.",
    )

    parser.add_argument(
        "--output",
        default="configs/noaa_calibration.json",
        help="Path for the fitted mapping.",
    )

    arguments = parser.parse_args()

    cache_root = Path(str(arguments.cache_root))

    refresh = bool(arguments.refresh)

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

    era5 = load_era5_monthly(
        fetch(
            ERA5_SERIES_URL,
            cache_root / "era5_daily_series_2t_global.csv",
            refresh=refresh,
        )
    )

    merged = noaa.merge(
        era5,
        on=["year", "month"],
        how="inner",
    ).sort_values(["year", "month"])

    merged = merged.reset_index(drop=True)

    print(f"NOAA series:  {noaa_url}")
    print(f"ERA5 series:  {ERA5_SERIES_URL}")
    print()

    print(f"NOAA months:  {len(noaa)} ({noaa['year'].min()}-{noaa['year'].max()})")

    print(f"ERA5 months:  {len(era5)} ({era5['year'].min()}-{era5['year'].max()})")

    print(f"Overlap:      {len(merged)} months")
    print()

    # The NOAA base period is a published property, but verifying it against
    # the data costs nothing and catches a silent version change.
    for label, span in (
        ("1901-2000", (1901, 2000)),
        ("1991-2020", (1991, 2020)),
    ):
        selection = noaa.loc[
            noaa["year"].between(*span),
            "noaa_anomaly",
        ]

        print(f"NOAA mean over {label}: {selection.mean():+.4f} C")

    print()

    evaluated_months = evaluation_span(merged)

    print(f"Walk-forward scoring period: last {evaluated_months} months")
    print()

    fits = [
        fit_window(
            merged,
            start_year=start_year,
            seasonal=seasonal,
            evaluated_months=evaluated_months,
        )
        for start_year in FIT_WINDOWS
        for seasonal in (False, True)
    ]

    header = (
        f"{'window':>8}  {'seasonal':>8}  {'months':>6}  "
        f"{'slope':>7}  {'in-sig':>7}  {'oos-sig':>7}  "
        f"{'oos-bias':>8}  {'worst':>6}"
    )

    print(header)
    print("-" * len(header))

    for item in fits:
        print(
            f"{item.start_year:>8}  "
            f"{str(item.seasonal):>8}  "
            f"{item.months:>6}  "
            f"{item.coefficients[1]:>7.4f}  "
            f"{item.in_sample_sigma:>7.4f}  "
            f"{item.out_of_sample_sigma:>7.4f}  "
            f"{item.out_of_sample_bias:>+8.4f}  "
            f"{item.worst_absolute_error:>6.3f}"
        )

    lowest = min(fits, key=lambda item: item.out_of_sample_sigma)

    best = select(fits)

    print()
    print(
        f"Lowest sigma:  {lowest.start_year}+, seasonal={lowest.seasonal}, "
        f"sigma={lowest.out_of_sample_sigma:.4f} C"
    )

    print(
        f"Selected:      {best.start_year}+, seasonal={best.seasonal}, "
        f"sigma={best.out_of_sample_sigma:.4f} C "
        f"over {best.out_of_sample_months} months "
        f"({best.months} training months)"
    )

    print()
    print(verdict(best.out_of_sample_sigma))

    payload: dict[str, Any] = {
        "schema_version": 1,
        "target": {
            "product": f"NOAAGlobalTemp {NOAA_VERSION}",
            "series": Path(noaa_url).name,
            "domain": "global land and ocean, 90S-90N",
            "quantity": "monthly mean surface temperature anomaly",
            "units": "degrees Celsius",
        },
        "predictor": {
            "product": "ERA5 daily global-mean 2 m temperature (ECMWF Climate Pulse)",
            "source": ERA5_SERIES_URL,
            "quantity": "monthly mean of daily anomalies vs 1991-2020",
            "units": "degrees Celsius",
        },
        "overlap_months": int(len(merged)),
        "latest_month": (
            f"{int(merged['year'].iloc[-1])}-{int(merged['month'].iloc[-1]):02d}"
        ),
        "selected": {
            "start_year": best.start_year,
            "seasonal": best.seasonal,
            "terms": (
                ["intercept", "era5_anomaly"]
                + (
                    [
                        "sin_annual",
                        "cos_annual",
                        "sin_semiannual",
                        "cos_semiannual",
                    ]
                    if best.seasonal
                    else []
                )
            ),
            "coefficients": best.coefficients,
            "out_of_sample_sigma": best.out_of_sample_sigma,
            "out_of_sample_bias": best.out_of_sample_bias,
            "out_of_sample_months": best.out_of_sample_months,
            "worst_absolute_error": best.worst_absolute_error,
        },
        "all_fits": [
            {
                "start_year": item.start_year,
                "seasonal": item.seasonal,
                "months": item.months,
                "coefficients": item.coefficients,
                "in_sample_sigma": item.in_sample_sigma,
                "out_of_sample_sigma": item.out_of_sample_sigma,
                "out_of_sample_bias": item.out_of_sample_bias,
                "worst_absolute_error": item.worst_absolute_error,
            }
            for item in fits
        ],
        "caveats": [
            "Fitted against currently published NOAA values, not first releases. "
            "Real first-publication error is this sigma plus the revision spread.",
            "The ERA5 predictor is the ECMWF Climate Pulse global mean, which is "
            "not identical to this system's own ERA5T extraction. Measure that "
            "offset against overlapping days before using the mapping in "
            "production.",
        ],
    }

    output_path = Path(str(arguments.output))

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Wrote {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
