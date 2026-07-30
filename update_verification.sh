#!/usr/bin/env bash

set -u

cd "$(dirname "$0")"

if [[ -f ".venv/bin/activate" ]]; then
  source .venv/bin/activate
fi

INIT_DATE="20260728"
CYCLE="00"
FORECAST_END="20260806"

echo "========================================"
echo "ERA5T sequential update"
echo "========================================"

DATES=$(
python - <<'PY'
from datetime import (
    date,
    datetime,
    timedelta,
    timezone,
)
from pathlib import Path

import pandas as pd


default_start = date(2026, 7, 23)
forecast_end = date(2026, 8, 6)

summary_path = Path(
    "output/era5t_global_daily.csv"
)

latest_complete = default_start

if summary_path.exists():
    frame = pd.read_csv(summary_path)

    complete = (
        frame["complete_matched_6h_day"]
        .astype(str)
        .str.strip()
        .str.lower()
        .eq("true")
    )

    if complete.any():
        latest_complete = (
            pd.to_datetime(
                frame.loc[
                    complete,
                    "date_utc",
                ],
                utc=True,
            )
            .max()
            .date()
        )

start = latest_complete + timedelta(days=1)

today_utc = datetime.now(
    timezone.utc
).date()

end = min(
    today_utc,
    forecast_end,
)

current = start

while current <= end:
    print(current.strftime("%Y%m%d"))
    current += timedelta(days=1)
PY
)

if [[ -z "$DATES" ]]; then
  echo "No new ERA5T dates need to be requested."
else
  for date in $DATES; do
    echo
    echo "Attempting ERA5T date: $date"

    if python download_era5t.py --date "$date"; then
      echo "ERA5T date completed: $date"
    else
      echo
      echo "Stopping at $date."
      echo "That date is not yet available as a complete 24-hour day."
      break
    fi
  done
fi

echo
echo "========================================"
echo "Recalculating ERA5T"
echo "========================================"

python calculate_era5t_global.py

run_verifier() {
  local script="$1"
  shift

  echo
  echo "----------------------------------------"
  echo "Running: $script"
  echo "----------------------------------------"

  if [[ -f "$script" ]]; then
    python "$script" "$@"
  else
    echo "SKIPPED: $script does not exist."
  fi
}

run_verifier \
  verify_forecasts.py \
  --init-date "$INIT_DATE" \
  --cycle "$CYCLE"

run_verifier verify_gdps.py

run_verifier \
  verify_icon.py \
  --init-date "$INIT_DATE" \
  --cycle "$CYCLE"

run_verifier \
  verify_geps.py \
  --init-date "$INIT_DATE" \
  --cycle "$CYCLE"

run_verifier \
  verify_ecmwf_ens.py \
  --init-date "$INIT_DATE" \
  --cycle "$CYCLE"

run_verifier \
  verify_aifs_ens.py \
  --init-date "$INIT_DATE" \
  --cycle "$CYCLE"

run_verifier \
  verify_multimodel_consensus.py \
  --init-date "$INIT_DATE" \
  --cycle "$CYCLE"

echo
echo "========================================"
echo "Verification status"
echo "========================================"

python verification_status.py

echo
echo "========================================"
echo "Verification update finished"
echo "========================================"
