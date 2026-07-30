# Global Temperature Forecast and Verification System

## Overview

This repository implements a reproducible, multi-model system for estimating the daily whole-Earth mean 2-meter air temperature from operational numerical weather prediction and artificial-intelligence forecast systems.

The project retrieves global 2-meter temperature fields, converts each forecast field into an area-weighted global mean, aggregates six-hourly values into UTC daily means, summarizes ensemble uncertainty, builds a multimodel consensus, and verifies forecasts against ERA5T as observations become available.

The current implementation supports seven forecast systems:

- NOAA Global Forecast System (GFS)
- NOAA Global Ensemble Forecast System (GEFS)
- Environment and Climate Change Canada Global Deterministic Prediction System (GDPS)
- Deutscher Wetterdienst ICON Global
- Environment and Climate Change Canada Global Ensemble Prediction System (GEPS)
- ECMWF Integrated Forecasting System Ensemble (IFS ENS)
- ECMWF Artificial Intelligence Forecasting System Ensemble (AIFS ENS)

ERA5T is used as the realized reference dataset for verification.

The repository is designed around immutable forecast-run identifiers, explicit provenance, run-scoped raw and processed paths, cloud archival, integrity validation, and repeatable verification. It is not a climate reanalysis product, a surface-station product, or a replacement for an official global-temperature index. It is a forecast-processing and verification system whose primary statistic is the spatially area-weighted whole-Earth mean of gridded 2-meter air temperature.

## Primary objectives

The project has five primary objectives.

1. **Produce a reproducible global forecast statistic.**  
   Convert each global 2-meter temperature field into one physically interpretable scalar: the area-weighted whole-Earth mean temperature in degrees Celsius.

2. **Compare structurally different forecast systems.**  
   Evaluate deterministic, traditional ensemble, and AI ensemble systems using a common temporal and spatial aggregation framework.

3. **Separate internal ensemble uncertainty from inter-model structural disagreement.**  
   Quantify the uncertainty within each ensemble and the disagreement between model centers.

4. **Verify forecasts against realized conditions.**  
   Match forecast-valid dates to complete ERA5T days and calculate model errors, member-level errors, and eventual calibration statistics.

5. **Build an auditable data pipeline.**  
   Preserve run identity, manifests, file counts, checksums, cloud paths, validation results, and a machine-readable run catalog.

## Current project status

The first complete reference cycle is:

```text
Initialization: 2026-07-28 00Z
Run ID:         20260728_00z
```

The reference cycle currently contains:

| System | Type | Forecast coverage | Effective members |
|---|---:|---:|---:|
| GFS | Deterministic | 10 complete UTC days through +240 h | 1 |
| GEFS | Ensemble | 10 complete UTC days through +240 h | 31 |
| GDPS | Deterministic | 10 complete UTC days through +240 h | 1 |
| ICON Global | Deterministic | 7 complete UTC days through +180 h | 1 |
| GEPS | Ensemble | 10 complete UTC days through +240 h | 21 |
| IFS ENS | Ensemble | 10 complete UTC days through +240 h | 51 |
| AIFS ENS | AI ensemble | 10 complete UTC days through +240 h | 51 |

The pipeline has passed a clean multi-cycle readiness audit:

```text
Errors:   0
Warnings: 0
Passes:   22
```

The reference raw archive has also passed cloud validation:

```text
Cloud objects: 1,652
Cloud bytes:   3,896,758,158
Restore test:  SHA-256 match
GRIB test:     restored file readable by ecCodes
```

Forecast verification is not yet populated for the reference cycle because the available ERA5T archive has not reached the forecast-valid period. The correct operational status is therefore:

```text
WAITING_FOR_ERA5T
```

## System architecture

The system is divided into acquisition, transformation, aggregation, consensus, verification, archival, and cloud-storage layers.

```text
Official forecast providers
        |
        v
Model-specific downloaders
        |
        v
Run-scoped raw GRIB storage
data/<model>/<run_id>/
        |
        v
Model-specific global processors
        |
        +---------------------------+
        |                           |
        v                           v
Six-hourly global means      Member-level global means
        |                           |
        +-------------+-------------+
                      |
                      v
UTC daily aggregation and ensemble summaries
                      |
                      v
Cross-model comparisons and multimodel consensus
                      |
                      v
ERA5T matching and verification
                      |
                      v
Run snapshot, manifest, catalog, readiness audit
                      |
                      v
Google Cloud Storage archive and restore validation
```

### Run identity

Every operational forecast cycle is identified by:

```text
RUN_ID = YYYYMMDD_CCz
```

Examples:

```text
20260728_00z
20260728_06z
20260729_00z
```

A run ID must be present in:

- Raw-data directories
- Processed output filenames
- Verification output filenames
- Snapshot directories
- Cloud object prefixes
- Manifest and catalog records
- Log directories

Run scoping prevents one cycle from overwriting another and is a core reproducibility requirement.

## Data retrieved

### Common physical variable

Every forecast downloader targets:

```text
2-meter air temperature
```

Depending on the provider and file format, the variable may be represented by identifiers such as:

```text
2t
t2m
TMP at 2 m above ground
AirTemp_AGL-2m
T_2M
```

The processing layer identifies the corresponding temperature field, converts Kelvin to degrees Celsius, and computes a whole-Earth spatial mean.

### Temporal sampling

The reference implementation samples forecasts every six hours:

```text
f000, f006, f012, ..., f240
```

For a +240-hour system, this yields 41 forecast times.

A complete UTC forecast day normally contains four snapshots:

```text
00:00 UTC
06:00 UTC
12:00 UTC
18:00 UTC
```

A daily row is marked complete only when all four expected snapshots are present.

### Model-specific acquisition

#### GFS

GFS is the deterministic NOAA forecast.

The downloader requests:

- Global domain
- 2-meter temperature
- 0.25-degree GFS product
- Six-hourly lead times
- Forecast hours 0 through 240
- Explicit initialization date and cycle

The downloader uses NOAA NOMADS filtering and writes:

```text
data/gfs/<run_id>/gfs_<run_id>_fHHH.grib2
```

The current GFS interface includes:

```text
--date
--cycle
--max-hour
--overwrite
```

The downloader writes through a temporary `.part` file and atomically renames a completed download. Existing nonempty files can be skipped, allowing interrupted runs to resume.

#### GEFS

GEFS is the NOAA ensemble system.

The reference cycle uses:

- One control member
- Thirty perturbed members
- Thirty-one total members
- Six-hourly lead times through +240 h

The run-scoped layout separates members:

```text
data/gefs/<run_id>/c00/
data/gefs/<run_id>/p01/
...
data/gefs/<run_id>/p30/
```

The processor calculates each member’s global mean before constructing ensemble summaries.

#### GDPS

GDPS is the deterministic Canadian global forecast.

The reference cycle retrieves:

- Global 2-meter air temperature
- Six-hourly lead times
- Forecast hours 0 through 240
- Forty-one GRIB files

Raw paths use:

```text
data/gdps/<run_id>/
```

#### ICON Global

ICON Global is the deterministic global model from Deutscher Wetterdienst.

ICON distributes temperature on an unstructured icosahedral grid. The project encountered and resolved several format and regridding issues during development, including CCSDS packing support and invalid intermediate files.

The current reference archive contains 93 ICON-related raw objects and supports 31 forecast lead times from +0 h through +180 h. The processed forecast contains seven complete UTC days.

Because native unstructured-grid handling is more complex than regular latitude-longitude processing, ICON remains the model most in need of additional production hardening and independent spatial-integration validation.

#### GEPS

GEPS is the Canadian ensemble forecast.

The reference cycle uses:

- Twenty-one ensemble members
- Forty-one forecast files
- Six-hourly lead times through +240 h

A GEPS forecast file can contain all members for one lead time. The processor extracts member-level global means and generates daily ensemble statistics.

#### IFS ENS

IFS ENS is ECMWF’s traditional physics-based ensemble.

The reference cycle uses:

- One control member
- Fifty perturbed members
- Fifty-one total members
- Six-hourly lead times through +240 h
- Forty-one control files
- Forty-one perturbed-member files

Each perturbed file contains fifty ensemble messages, while each control file contains one message.

The raw structure is:

```text
data/ecmwf_ens/<run_id>/control/
data/ecmwf_ens/<run_id>/perturbed/
```

#### AIFS ENS

AIFS ENS is ECMWF’s AI ensemble.

The project processes AIFS ENS in the same comparison framework as IFS ENS:

- One control member
- Fifty perturbed members
- Fifty-one total members
- Six-hourly lead times through +240 h
- Forty-one control files
- Forty-one perturbed-member files

The raw structure is:

```text
data/aifs_ens/<run_id>/control/
data/aifs_ens/<run_id>/perturbed/
```

AIFS is retained as a distinct model center. It is not merged with IFS before the multimodel calculations.

#### ERA5T

ERA5T is the near-real-time reanalysis reference used for forecast verification.

The project requests:

- Global 2-meter temperature
- Twenty-four hourly fields per complete UTC day
- One file per date

The raw structure is:

```text
data/era5t/YYYYMMDD/
```

The ERA5T processor calculates two daily estimates:

1. The mean of all 24 hourly fields
2. The mean of the four forecast-matched six-hourly fields

This makes it possible to measure the small sampling difference between a full hourly daily mean and the forecast-compatible four-snapshot daily mean.

At the time of the reference snapshot, complete ERA5T data existed for:

```text
2026-07-22
2026-07-23
```

The forecast cycle starts on 2026-07-28, so no verification overlap existed yet.

## Mathematical processing

### Area-weighted whole-Earth mean

For a regular latitude-longitude grid, grid points are not equal-area. Longitude spacing is approximately uniform, but the physical area represented by a grid point decreases toward the poles.

The global mean is therefore calculated with latitude weights:

\[
w_i = \cos(\phi_i)
\]

where \(\phi_i\) is latitude.

For temperature field \(T_{ij}\), the weighted global mean is:

\[
\bar{T}
=
\frac{
\sum_i \sum_j T_{ij}\cos(\phi_i)
}{
\sum_i \sum_j \cos(\phi_i)
}
\]

The processor also removes a duplicated longitude endpoint when both 0 degrees and 360 degrees are present.

Temperatures are converted from Kelvin to Celsius:

\[
T_{^\circ C} = T_K - 273.15
\]

### Six-hourly output

A deterministic processor produces records with fields such as:

```text
file
initialization_utc
valid_time_utc
forecast_hour
global_temperature_c
date_utc
```

An ensemble processor additionally retains:

```text
member
control_or_perturbed
members_available
```

### Daily aggregation

The daily deterministic mean is:

\[
\bar{T}_d
=
\frac{1}{n_d}
\sum_{k=1}^{n_d} T_{d,k}
\]

where \(n_d\) is the number of available six-hourly snapshots for date \(d\).

A day is complete when:

\[
n_d = 4
\]

Daily deterministic output includes:

```text
global_temperature_c
snapshots
minimum_snapshot_c
maximum_snapshot_c
complete_day
```

### Ensemble summaries

For each date, ensemble products include:

```text
ensemble_mean_c
ensemble_std_c
p05_c
p95_c
members_available
```

The project also preserves member-level daily values so member errors can be calculated after ERA5T becomes available.

## Multimodel consensus

The consensus currently combines four ensemble centers:

```text
GEFS
GEPS
IFS ENS
AIFS ENS
```

### Equal-center consensus

Each forecasting system receives equal weight, regardless of member count.

This prevents a 51-member ensemble from dominating a 21-member ensemble solely because it contains more members.

The equal-center mean is:

\[
\mu_{\text{equal}}
=
\frac{1}{4}
\sum_{m=1}^{4}\mu_m
\]

### Physics consensus

The physics-only center excludes AIFS:

\[
\mu_{\text{physics}}
=
\frac{
\mu_{\text{GEFS}}
+
\mu_{\text{GEPS}}
+
\mu_{\text{IFS}}
}{3}
\]

The project then measures:

```text
AIFS minus IFS
AIFS minus physics consensus
```

### Structural disagreement

The system calculates:

- Minimum model-center mean
- Maximum model-center mean
- Center-mean range
- Between-center standard deviation
- Warmest system
- Coolest system
- Disagreement rank

### Variance decomposition

The average within-center ensemble variance is:

\[
\sigma^2_{\text{within}}
=
\frac{1}{M}
\sum_{m=1}^{M}\sigma_m^2
\]

The between-center variance is the population variance of the model-center means:

\[
\sigma^2_{\text{between}}
=
\operatorname{Var}(\mu_1,\ldots,\mu_M)
\]

The equal-weight mixture variance is:

\[
\sigma^2_{\text{total}}
=
\sigma^2_{\text{within}}
+
\sigma^2_{\text{between}}
\]

The structural variance fraction is:

\[
f_{\text{structural}}
=
\frac{
\sigma^2_{\text{between}}
}{
\sigma^2_{\text{total}}
}
\]

This statistic identifies whether forecast uncertainty is mainly caused by disagreement inside ensembles or disagreement between forecasting systems.

### Interval diagnostics

The consensus calculates:

- A normal-approximation multimodel 5th percentile
- A normal-approximation multimodel 95th percentile
- Intersection of the four reported central 90% intervals
- Union of the four central 90% intervals
- Common-to-union overlap fraction

These intervals are diagnostics. They are not yet statistically calibrated forecast intervals.

## Reference-run results

For run `20260728_00z`, the four-center consensus produced:

```text
Equal-center period mean:              16.934039 °C
Physics-consensus period mean:         16.888760 °C
Average AIFS minus IFS:                +0.106438 °C
Average AIFS minus physics consensus:  +0.181115 °C
Average center-mean range:              0.250378 °C
Average internal RMS spread:            0.050642 °C
Average total mixture spread:           0.107425 °C
Average structural variance fraction:  77.97%
Common central-90% overlap:             0 of 10 dates
Greatest disagreement date:             2026-08-03
Greatest center-mean range:              0.297486 °C
```

Interpretation:

- AIFS was consistently warmer than IFS and the physics-only consensus in this cycle.
- Inter-model disagreement dominated the total mixture variance.
- Internal ensemble spread alone materially understated total cross-system uncertainty.
- The four reported central 90% intervals did not share a common overlap on any of the ten consensus dates.

These are results for one initialization cycle. They are not evidence of stable model bias. Bias and calibration conclusions require many verified historical cycles.

## Verification architecture

Verification scripts match complete forecast days to complete ERA5T days.

The verification layer includes:

```text
verify_forecasts.py
verify_gdps.py
verify_icon.py
verify_geps.py
verify_ecmwf_ens.py
verify_aifs_ens.py
verify_multimodel_consensus.py
verification_status.py
```

Verification output is written under:

```text
output/verification/
```

Typical outputs include:

```text
<model>_<run_id>_vs_era5t.csv
<ensemble>_<run_id>_member_errors.csv
multimodel_consensus_<run_id>_vs_era5t.csv
```

The intended verification metrics include:

- Forecast minus ERA5T error
- ERA5T minus forecast error
- Absolute error
- Squared error
- Member-level error
- Ensemble-mean error
- Interval coverage
- Lead-time error
- Model-center ranking
- Cross-cycle calibration statistics

Current reference-run verification tables contain headers but no overlapping rows because ERA5T has not reached the forecast dates.

## Repository structure

The following layout describes the current architecture. Additional experimental scripts may exist.

```text
.
├── README.md
├── .gitignore
├── gcs_lifecycle.json
│
├── download_gfs.py
├── download_gefs.py
├── download_gdps.py
├── download_icon.py
├── download_geps.py
├── download_ecmwf_ens.py
├── download_aifs_ens.py
├── download_era5t.py
│
├── calculate_gfs_global.py
├── calculate_gefs_global.py
├── calculate_gdps_global.py
├── calculate_icon_global.py
├── calculate_geps_global.py
├── calculate_ecmwf_ens_global.py
├── calculate_aifs_ens_global.py
├── calculate_era5t_global.py
│
├── compare_all_global_models.py
├── compare_ensemble_systems.py
├── compare_three_ensemble_systems.py
├── build_multimodel_consensus.py
│
├── verify_forecasts.py
├── verify_gdps.py
├── verify_icon.py
├── verify_geps.py
├── verify_ecmwf_ens.py
├── verify_aifs_ens.py
├── verify_multimodel_consensus.py
├── verification_status.py
│
├── snapshot_run.py
├── build_run_catalog.py
├── audit_multicycle_readiness.py
│
├── archive/
│   ├── run_catalog.csv
│   ├── run_catalog.json
│   ├── multicycle_readiness.csv
│   ├── multicycle_readiness.json
│   └── runs/
│       └── <run_id>/
│           ├── manifest.json
│           ├── output_index.csv
│           ├── cloud_validation.json
│           └── cloud_validation_complete.json
│
├── data/                  # Local raw data; ignored by Git
│   ├── gfs/
│   ├── gefs/
│   ├── gdps/
│   ├── icon/
│   ├── geps/
│   ├── ecmwf_ens/
│   ├── aifs_ens/
│   └── era5t/
│
├── output/                # Generated products; ignored by Git
│   └── verification/
│
└── logs/                  # Runtime and transfer logs; ignored by Git
```

## File responsibilities

### Download scripts

| File | Responsibility |
|---|---|
| `download_gfs.py` | Downloads run-scoped GFS 2-meter temperature GRIB files and supports resumption. |
| `download_gefs.py` | Downloads the GEFS control and perturbed members. |
| `download_gdps.py` | Downloads deterministic GDPS 2-meter air temperature. |
| `download_icon.py` | Downloads ICON Global 2-meter temperature and supporting grid products. |
| `download_geps.py` | Downloads GEPS files containing all expected members. |
| `download_ecmwf_ens.py` | Downloads IFS ENS control and perturbed products. |
| `download_aifs_ens.py` | Downloads AIFS ENS control and perturbed products. |
| `download_era5t.py` | Requests complete hourly ERA5T 2-meter temperature days. |

### Processing scripts

| File | Responsibility |
|---|---|
| `calculate_gfs_global.py` | Produces run-scoped six-hourly, daily, complete-daily, and JSON GFS outputs. |
| `calculate_gefs_global.py` | Produces member-level and ensemble-level GEFS global summaries. |
| `calculate_gdps_global.py` | Produces deterministic GDPS global summaries. |
| `calculate_icon_global.py` | Processes ICON data and produces deterministic global summaries. |
| `calculate_geps_global.py` | Produces member-level and ensemble-level GEPS summaries. |
| `calculate_ecmwf_ens_global.py` | Produces IFS ENS member and ensemble summaries. |
| `calculate_aifs_ens_global.py` | Produces AIFS ENS member and ensemble summaries. |
| `calculate_era5t_global.py` | Produces hourly and daily ERA5T global means and matched-six-hour diagnostics. |

### Comparison and consensus scripts

| File | Responsibility |
|---|---|
| `compare_all_global_models.py` | Joins deterministic and ensemble products for cross-model inspection. |
| `compare_ensemble_systems.py` | Compares ensemble systems on common dates. |
| `compare_three_ensemble_systems.py` | Earlier or narrower ensemble comparison workflow. |
| `build_multimodel_consensus.py` | Builds the four-center consensus and structural-disagreement diagnostics. |

### Verification scripts

| File | Responsibility |
|---|---|
| `verify_forecasts.py` | Verifies GFS and GEFS against ERA5T. |
| `verify_gdps.py` | Verifies GDPS. |
| `verify_icon.py` | Verifies ICON. |
| `verify_geps.py` | Verifies GEPS and member-level errors. |
| `verify_ecmwf_ens.py` | Verifies IFS ENS and member-level errors. |
| `verify_aifs_ens.py` | Verifies AIFS ENS and member-level errors. |
| `verify_multimodel_consensus.py` | Verifies consensus output. |
| `verification_status.py` | Reports whether ERA5T overlap is available for each system. |

### Reproducibility and audit scripts

| File | Responsibility |
|---|---|
| `snapshot_run.py` | Creates an immutable run snapshot and output index. |
| `build_run_catalog.py` | Builds CSV and JSON catalogs across run manifests. |
| `audit_multicycle_readiness.py` | Enforces run-scoped data, output naming, script interfaces, and clean Git state. |

## Raw and processed data policy

Raw GRIB data and generated output are not stored in Git.

The repository intentionally ignores:

```text
data/
output/
logs/
.venv/
.env.gcp.local
.DS_Store
__pycache__/
*.py[cod]
```

Reasons:

- GRIB archives are too large for ordinary Git history.
- Generated CSV and JSON files can be recreated from raw data.
- Logs are operational artifacts.
- Local virtual environments are platform-specific.
- Cloud configuration may contain local identifiers.
- Python bytecode and macOS metadata are not source code.

Manifests, catalogs, validation records, and readiness reports remain suitable for Git because they are small, auditable metadata products.

## Google Cloud Storage architecture

### Active cloud resources

```text
Google Cloud project:
gtf-forecast-20260729-a7c9

Cloud Storage bucket:
gtf-forecast-20260729-a7c9-data

Location:
US-EAST1
```

The bucket was created with:

- Standard default storage
- Uniform bucket-level access
- Public-access prevention
- Seven-day soft delete

### Object layout

```text
gs://gtf-forecast-20260729-a7c9-data/
├── raw/<run_id>/<model>/
├── processed/<run_id>/
├── verification/<run_id>/
├── manifests/<run_id>/
├── catalogs/
└── logs/<run_id>/
```

### Prefix purposes

| Prefix | Purpose |
|---|---|
| `raw/` | Original provider GRIB files and model-specific supporting files. |
| `processed/` | Run-scoped CSV and JSON forecast products. |
| `verification/` | ERA5T comparison products. |
| `manifests/` | Snapshot manifests, output indexes, and cloud-validation records. |
| `catalogs/` | Cross-run CSV and JSON catalogs. |
| `logs/` | Download, processing, and cloud-transfer logs. |

### Lifecycle policy

The raw archive uses storage-class transitions:

```text
STANDARD -> NEARLINE after 30 days
NEARLINE -> COLDLINE after 90 days
COLDLINE -> ARCHIVE after 365 days
```

The policy applies only to objects under `raw/`. Small processed products, manifests, and catalogs remain immediately accessible.

### Common gcloud commands

Set the project and bucket:

```bash
export PROJECT_ID="gtf-forecast-20260729-a7c9"
export BUCKET="${PROJECT_ID}-data"
export RUN_ID="20260728_00z"

gcloud config set project "$PROJECT_ID"
```

Inspect the bucket:

```bash
gcloud storage buckets describe "gs://${BUCKET}"
```

List run objects:

```bash
gcloud storage ls \
  --recursive \
  "gs://${BUCKET}/raw/${RUN_ID}/**"
```

Calculate run size:

```bash
gcloud storage du \
  --summarize \
  "gs://${BUCKET}/raw/${RUN_ID}"
```

Synchronize a raw model directory:

```bash
gcloud storage rsync \
  --recursive \
  "data/gfs/${RUN_ID}" \
  "gs://${BUCKET}/raw/${RUN_ID}/gfs"
```

Synchronize processed output:

```bash
gcloud storage rsync \
  --recursive \
  output \
  "gs://${BUCKET}/processed/${RUN_ID}"
```

Restore one object:

```bash
gcloud storage cp \
  "gs://${BUCKET}/raw/${RUN_ID}/gfs/gfs_${RUN_ID}_f000.grib2" \
  "/tmp/gfs_${RUN_ID}_f000.grib2"
```

### Cloud integrity validation

The complete reference archive records:

```text
aifs_ens:   82 objects
ecmwf_ens:  82 objects
gdps:       41 objects
gefs:     1272 objects
geps:       41 objects
gfs:        41 objects
icon:       93 objects
total:    1652 objects
```

A GFS file was downloaded back from Cloud Storage and compared to the local source:

```text
Local SHA-256:
f4d4a26ee37a3a55009634bd30fd6d5e615c7ac2a4d7a792d8eee96d8d357582

Restored SHA-256:
f4d4a26ee37a3a55009634bd30fd6d5e615c7ac2a4d7a792d8eee96d8d357582
```

The restored file also returned:

```text
grib_count = 1
```

This demonstrates object restoration and content integrity for the tested file. A future production version should perform automated checksum validation across a statistically meaningful sample or every object.

## Local environment

The reference development environment is macOS with Python 3.13.

Core Python packages observed in the processing code include:

```text
requests
numpy
pandas
xarray
cfgrib
```

Additional system requirements include:

```text
ecCodes command-line tools
Google Cloud CLI
```

ERA5T retrieval also requires valid Copernicus Climate Data Store credentials.

A formal pinned dependency file is still required. Until one is committed, a representative environment can be created with:

```bash
python3.13 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install \
  requests \
  numpy \
  pandas \
  xarray \
  cfgrib
```

Install ecCodes using the package manager appropriate for the operating system. On macOS, Homebrew can provide the ecCodes utilities.

## Manual execution

The exact command-line options differ slightly by model. Every operational model script must accept explicit run parameters.

### GFS example

```bash
python download_gfs.py \
  --date 20260728 \
  --cycle 00 \
  --max-hour 240

python calculate_gfs_global.py \
  --date 20260728 \
  --cycle 00 \
  --max-hour 240
```

### Consensus example

```bash
python build_multimodel_consensus.py \
  --date 20260728 \
  --cycle 00
```

### Readiness audit

```bash
python audit_multicycle_readiness.py \
  --run-id 20260728_00z
```

A run is automation-ready only when the audit reports:

```text
Errors:   0
Warnings: 0
```

### Run snapshot and catalog

The expected workflow is:

```bash
python snapshot_run.py --run-id 20260728_00z
python build_run_catalog.py
```

The snapshot records code, output, raw-directory, file-count, size, and result metadata without duplicating all raw GRIB files into Git.

## Reproducibility controls completed

The following controls have been implemented.

1. Run-scoped GFS raw paths
2. Run-scoped GFS output filenames
3. Explicit `--date`, `--cycle`, and horizon parameters
4. Removal of hardcoded consensus dates
5. Atomic or resumable GFS downloads
6. Immutable run snapshot
7. Output index
8. Machine-readable run catalog
9. Multi-cycle readiness audit
10. Git exclusion of generated and binary data
11. Cloud archive organized by run and model
12. Cloud object-count validation
13. Cloud size validation
14. SHA-256 restore test
15. GRIB readability test after restore
16. Clean repository state
17. Deterministic audit output

## Work completed

### Forecast ingestion

- GFS complete
- GEFS complete
- GDPS complete
- ICON complete through +180 h
- GEPS complete
- IFS ENS complete
- AIFS ENS complete
- ERA5T ingestion operational for available complete dates

### Processing

- Whole-Earth weighted means implemented
- Duplicate longitude handling implemented
- Kelvin-to-Celsius conversion implemented
- Six-hourly outputs implemented
- UTC daily aggregation implemented
- Complete-day flags implemented
- Ensemble member processing implemented
- Ensemble mean, standard deviation, and percentile summaries implemented

### Analysis

- Deterministic model comparison implemented
- Ensemble-system comparison implemented
- Equal-center multimodel consensus implemented
- Physics-only consensus implemented
- AI-versus-physics diagnostics implemented
- Within-center and between-center variance decomposition implemented
- Structural variance fraction implemented
- Interval-overlap diagnostics implemented
- Disagreement ranking implemented

### Verification

- ERA5T hourly and matched-six-hour processing implemented
- Verification files implemented for all seven systems
- Ensemble member-error outputs implemented
- Verification-status reporting implemented
- Current no-overlap state handled without treating it as a failure

### Reproducibility and operations

- Reference run snapshot created
- Run catalog created
- Cloud archive created
- Complete raw object counts validated
- GFS cloud restore validated
- Generated files removed from Git tracking
- Gitignore hardened for data, output, logs, macOS metadata, and Python caches
- Multi-cycle readiness audit passed with zero errors and zero warnings

## Missing work

The project is operational for a manually executed reference cycle, but it is not yet a complete unattended production system.

### Highest-priority missing component: orchestrator

A single resumable run orchestrator is required. It should:

1. Accept or resolve an initialization date and cycle
2. Acquire a filesystem lock
3. Run model downloads independently
4. Resume partially completed downloads
5. Validate expected files and message counts
6. Process each available model
7. Build comparison and consensus outputs
8. Update ERA5T
9. Run verification
10. Create a snapshot and manifest
11. Update the run catalog
12. Upload raw and processed artifacts
13. Validate cloud counts and checksums
14. Write a final machine-readable run status
15. Release the lock
16. Return a nonzero exit code for an incomplete mandatory stage

### Dependency management

The repository still needs:

- `requirements.txt` or `pyproject.toml`
- Exact version pins
- Reproducible environment lock file
- Supported Python-version declaration
- Automated installation test

### Testing

The repository still needs:

- Unit tests for spatial weighting
- Unit tests for daily completeness
- Unit tests for member parsing
- Unit tests for filename parsing
- Unit tests for run IDs
- Unit tests for consensus variance decomposition
- Tests for empty or delayed ERA5T overlap
- Integration tests with small fixture GRIB files
- Cloud-upload dry-run tests
- Restore-validation tests
- Regression tests for the reference cycle

### Historical verification

One forecast cycle is insufficient for skill conclusions.

The system needs:

- Historical forecast-cycle backfill
- ERA5T backfill
- Lead-time verification
- Seasonal stratification
- Rolling bias estimates
- Mean absolute error
- Root mean squared error
- Continuous ranked probability score
- Interval coverage
- Rank histograms
- Spread-error analysis
- Ensemble reliability analysis
- Cross-model error correlation
- Out-of-sample calibration

### Calibrated consensus

The current equal-center consensus is transparent but uncalibrated.

Future versions should compare:

- Equal-center weighting
- Inverse-error weighting
- Constrained linear stacking
- Bayesian model averaging
- Lead-dependent weights
- Season-dependent weights
- Regime-dependent weights
- Robust median or trimmed consensus
- Correlation-adjusted weighting

All weights must be estimated only from historical information available before the forecast being evaluated.

### ICON hardening

ICON requires additional validation because its native grid is unstructured.

Required work includes:

- Independent cell-area weighting validation
- Regridding-conservation tests
- CCSDS packing compatibility checks
- Detection of zero-byte and invalid intermediate files
- Native-grid metadata preservation
- Repeatable containerized regridding environment

### Data provenance

Each raw object should eventually include or be associated with:

- Provider
- Source URL or request parameters
- Retrieval timestamp
- Initialization time
- Forecast lead
- Member
- Variable
- Level
- Grid
- Message count
- File size
- Checksum
- Downloader version
- Processing-code commit

### Cloud operations

The cloud layer still needs:

- Dedicated service account
- Least-privilege IAM policy
- Application Default Credentials strategy for automation
- Budget alerts
- Cost monitoring
- Retention review
- Automated lifecycle-policy tests
- Cross-region recovery decision
- Automated catalog upload
- Automated log retention
- Optional object versioning policy review

### Monitoring

A production deployment should report:

- Missing model cycles
- Missing forecast hours
- Missing ensemble members
- Invalid GRIB messages
- Slow downloads
- ERA5T lag
- Processing exceptions
- Cloud transfer failures
- Checksum mismatches
- Disk-space thresholds
- Forecast completion status
- Verification completion status

### Documentation and governance

The repository still needs:

- License selection
- `CONTRIBUTING.md`
- Code of conduct if public collaboration is expected
- Maintainer and ownership information
- Release policy
- Data-provider attribution review
- Citation instructions
- Security policy
- Changelog

## Target architecture

The target is a daily, unattended, auditable forecast and verification platform.

```text
Scheduler
   |
   v
Run resolver and lock manager
   |
   +--> GFS acquisition
   +--> GEFS acquisition
   +--> GDPS acquisition
   +--> ICON acquisition
   +--> GEPS acquisition
   +--> IFS ENS acquisition
   +--> AIFS ENS acquisition
   |
   v
Integrity gate
   |
   v
Parallel model processing
   |
   v
Daily products and member summaries
   |
   v
Consensus and diagnostics
   |
   v
ERA5T update and verification
   |
   v
Snapshot, manifest, and catalog
   |
   v
GCS upload and checksum validation
   |
   v
Run-status database and monitoring
```

The final system should support:

- Multiple cycles without overwrite risk
- Restart after interruption
- Independent model failures
- Explicit partial-completion status
- Historical backfill
- Forecast verification by lead
- Calibrated multimodel distributions
- Programmatic query of all runs
- Reproducible restoration from cloud storage
- Automated reports
- Optional API or dashboard access

## Scientific limitations

1. **2-meter air temperature is not surface skin temperature.**
2. **A gridded forecast is not a direct observation.**
3. **The global mean depends on spatial weighting and grid representation.**
4. **Four six-hourly samples are an approximation to a 24-hour mean.**
5. **Model initializations are not independent observations.**
6. **Ensemble members within one system are correlated.**
7. **Different systems can share observations, data assimilation inputs, and model assumptions.**
8. **One forecast cycle cannot establish persistent bias.**
9. **Normal approximations may not represent multimodal or skewed mixtures.**
10. **ERA5T is a near-real-time reanalysis and may later differ from finalized reanalysis products.**
11. **The current statistic is an absolute global mean temperature, not an anomaly relative to a climatological baseline.**
12. **The system has not yet been calibrated across historical out-of-sample cycles.**

## Security and secret handling

Never commit:

```text
.env.gcp.local
Google service-account keys
Copernicus credentials
Application Default Credential files
Private API tokens
Cloud billing information
Local browser credentials
```

The bucket is configured to prevent public access. Public release of source code does not imply public release of the raw forecast archive.

Before publishing a repository archive:

```bash
git status --short
git ls-files data
git ls-files output
git ls-files logs
git grep -n -I -E \
  'BEGIN PRIVATE KEY|SECRET_ACCESS_KEY|API_KEY=|PASSWORD='
```

The generated GitHub archive should be created from committed Git files rather than by zipping the entire working directory.

## Recommended release procedure

1. Place this `README.md` in the repository root.
2. Review project name, ownership, and license.
3. Add a pinned dependency file.
4. Commit all source and metadata changes.
5. Confirm the working tree is clean.
6. Run the multi-cycle readiness audit.
7. Confirm `data/`, `output/`, and `logs/` contain no tracked files.
8. Generate the release ZIP using `git archive`.
9. Generate a SHA-256 checksum for the ZIP.
10. Inspect the ZIP listing before publishing.
11. Push source to the intended GitHub repository.
12. Keep raw data in Cloud Storage rather than GitHub.

## Project progress summary

The project has progressed from a single-cycle experimental workflow into a run-scoped, cloud-archived, reproducibility-oriented forecast system.

The most important completed milestone is not only that seven systems produced output. It is that the reference run can be identified, audited, restored, and compared without relying on untracked assumptions.

The next major milestone is unattended orchestration. After that, the project’s scientific value will depend primarily on accumulating verified historical cycles and replacing uncalibrated equal weighting with rigorously out-of-sample calibrated probabilistic forecasts.

## License

No license has been selected in the available project state.

Until a license is added, normal copyright restrictions apply. A public repository should not be treated as open-source merely because its source is visible.

Select and add an explicit license before inviting external reuse or contributions.
