# The NOAA target

The exact quantity this system predicts, and how accurately it can possibly be
predicted. Regenerate the numbers with:

```bash
uv run python scripts/fit_noaa_mapping.py --refresh
```

## 1. The target

| Property | Value |
|---|---|
| Product | NOAAGlobalTemp v6.1 |
| Publisher | NOAA National Centers for Environmental Information |
| Series | `aravg.mon.land_ocean.90S.90N.v6.1.0.<YYYYMM>.asc` |
| Domain | Global, land **and** ocean, 90S–90N |
| Quantity | Monthly mean surface temperature **anomaly** |
| Baseline | **1991–2020** (verified empirically, see below) |
| Units | degrees Celsius |
| Record starts | January 1850 |
| Directory | `https://www.ncei.noaa.gov/data/noaa-global-surface-temperature/v6.1/access/timeseries/` |

The filename embeds the release month and changes with every publication, so it
must be discovered from the directory listing, never hard-coded.

### Baseline, verified not assumed

The v6.1 series mean over each candidate baseline:

```text
1901-2000   -0.6121 C
1991-2020   +0.0000 C
```

The baseline is 1991–2020. This matters twice over:

- It matches the ERA5 Climate Pulse anomaly baseline, so no rebaselining is
  needed on the predictor side.
- NOAA's public monthly climate reports quote anomalies against the 20th
  century average. **Add 0.6121 °C** to convert a prediction from this system
  into the number that appears in the press release. Predicting "+0.51 °C" and
  reading "+1.12 °C" in the report is the same value in two baselines.

### Publication timing and revisions

As of 2026-08-06 the latest published month is **2026-06**, so July 2026
publishes in mid-August. The monthly release lands roughly two weeks after
month end, which is the deadline the daily estimate is racing.

NOAA revises: the values fitted here are the *currently published* ones, not
the ones published first. Real first-release error is therefore the residual
below **plus** the revision spread, which this analysis does not measure.
Measuring it needs archived monthly releases and is not yet done.

## 2. The error floor

Half A of the calibration is the mapping from monthly ERA5 global-mean 2 m
temperature anomaly to the NOAA published anomaly. Both series are fully
available historically, so this is measurable today, with no forecast data.

Predictor: ERA5 daily global-mean 2 m temperature (ECMWF Climate Pulse),
1940–present, averaged over complete months. Overlap with NOAA: 1038 months.

Fitted as `noaa ~ intercept + era5_anomaly (+ annual and semiannual harmonics)`,
scored walk-forward over the same last 114 months for every window, each
prediction using only months already published when it was made:

```text
  window  seasonal  months    slope   in-sig  oos-sig  oos-bias   worst
    1940     False    1038   0.8903   0.0684   0.0350   +0.0277   0.106
    1940      True    1038   0.8919   0.0674   0.0371   +0.0261   0.104
    1979     False     570   0.9175   0.0425   0.0362   +0.0100   0.103
    1979      True     570   0.9180   0.0419   0.0369   +0.0096   0.108
    2000     False     318   0.9060   0.0356   0.0356   +0.0066   0.103
    2000      True     318   0.9076   0.0353   0.0354   +0.0060   0.095
    2015     False     138   0.8531   0.0355   0.0338   -0.0011   0.097
    2015      True     138   0.8540   0.0333   0.0328   -0.0014   0.093
```

**Error floor: σ ≈ 0.035 °C, worst month ≈ 0.10 °C.**

Every window lands between 0.033 and 0.037 °C. The standard error of an
estimated σ over 114 months is about σ/√228 ≈ 0.002 °C, so none of these fits
is distinguishable from any other. The operational choice is 2000+ with
seasonal terms: enough months to be stable, recent enough to reflect the
current observing system. It is a judgement call, not a search result.

### Verdict

**Qualified go.** Direction and rough magnitude of the NOAA monthly value are
predictable. The exact published value is not, and no forecast skill will make
it so — this floor sits below the forecast layer entirely.

### Consequences that change the design

1. **The proposed 0.05 °C alert threshold is inside the noise.** A 0.05 °C
   move in the NOAA estimate is 1.4σ of the transformation alone, before any
   forecast error. Thresholds must be set from the total error budget, and
   0.05 °C is not a defensible one for the NOAA estimate. It may still be
   defensible for shifts in the *forecast consensus*, which is a different
   quantity with different noise.

2. **The slope is not 1.** ERA5 anomalies map onto NOAA anomalies at roughly
   0.85–0.92, consistently across every window. NOAA damps relative to the
   reanalysis — different coverage, interpolation, and SST treatment. Passing
   an ERA5 anomaly through unscaled introduces a systematic error that grows
   with the anomaly: at today's ≈ +0.6 °C, about 0.06 °C, larger than the
   residual σ itself.

3. **Report an interval, never a point.** The honest daily output is
   `estimate ± 0.035 °C` from this stage alone, widened by the forecast
   contribution for the unobserved remainder of the month.

## 3. What this does not cover

Half B — daily forecast consensus to observed ERA5T, by lead time — needs
forecast history that does not exist yet (2 cycles archived). It only affects
the unobserved remainder of the month, weighted `days_remaining / days_in_month`,
so its influence collapses as a month fills in.

The predictor used here is the ECMWF Climate Pulse global mean, which is not
identical to this system's own ERA5T extraction (different grid handling and
sampling). That offset must be measured against overlapping days before the
mapping is used in production; with 2 days of local ERA5T it cannot be
measured yet.

## 4. Artifact

`configs/noaa_calibration.json` holds the fitted coefficients, all eight fits,
the scoring period, and the caveats above in machine-readable form.
