from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .clean import clean_xy, insert_gap_nans

PRESSURE_RANGE = (-200.0, 15_000.0)
TENSION_RANGE = (-5_000.0, 80_000.0)


def _find_header_row(path: Path) -> int:
    encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    last_err: Exception | None = None
    for enc in encodings:
        try:
            with path.open("r", encoding=enc, errors="strict") as handle:
                for i, line in enumerate(handle):
                    if i > 40:
                        break
                    cols = [c.strip() for c in line.replace(",", "\t").split("\t")]
                    if cols and cols[0] == "Date" and any("Real Time" in c for c in cols):
                        return i
            last_err = None
            break
        except UnicodeDecodeError as exc:
            last_err = exc
            continue
    if last_err:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for i, line in enumerate(handle):
                if i > 40:
                    break
                if line.startswith("Date") and "Real Time" in line:
                    return i
    raise ValueError(f"Could not find Date / Real Time header in {path.name}")


def _to_utc_ms(date_s: pd.Series, time_s: pd.Series, tz_name: str) -> pd.Series:
    combined = date_s.astype(str).str.strip() + " " + time_s.astype(str).str.strip()
    ts = pd.to_datetime(combined, errors="coerce", format="mixed")
    tz = ZoneInfo(tz_name)
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(tz, ambiguous="infer", nonexistent="shift_forward")
    else:
        ts = ts.dt.tz_convert(tz)
    ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
    return ts.to_numpy(dtype="datetime64[ns]").astype("int64").astype("float64") / 1_000_000.0


def parse_datacan(path: str | Path, tz_name: str = "America/Chicago") -> dict:
    path = Path(path)
    header_row = _find_header_row(path)
    skip = list(range(header_row)) + [header_row + 1]
    df = pd.read_csv(
        path,
        sep="\t",
        header=0,
        skiprows=skip,
        engine="c",
        encoding="utf-8",
        encoding_errors="replace",
        on_bad_lines="skip",
        low_memory=False,
    )
    df.columns = [str(c).strip() for c in df.columns]
    if not df.empty and str(df.iloc[0, 0]).startswith("("):
        df = df.iloc[1:].copy()

    rename = {}
    cols = list(df.columns)
    pressure_cols = [c for c in cols if c == "Pressure" or c.startswith("Pressure")]
    if "Pressure" in cols:
        rename["Pressure"] = "internal_psi"
    extras = [c for c in pressure_cols if c != "Pressure"]
    if extras:
        rename[extras[0]] = "external_psi"

    df = df.rename(columns=rename)
    if "Date" not in df.columns or "Real Time" not in df.columns:
        raise ValueError(f"{path.name} is not an Intelli-Log export (missing Date / Real Time)")

    t = _to_utc_ms(df["Date"], df["Real Time"], tz_name)
    series: dict[str, dict] = {}

    if "internal_psi" in df.columns:
        x, y = clean_xy(t, pd.to_numeric(df["internal_psi"], errors="coerce"), *PRESSURE_RANGE)
        x, y = insert_gap_nans(x, y)
        series["dc_internal_p"] = {
            "id": "dc_internal_p",
            "label": "Intelli-Log Internal Pressure",
            "panel": "pressure",
            "unit": "psia",
            "source": "datacan",
            "color": "#E8A838",
            "axis": "y",
            "x": x,
            "y": y,
        }
    if "external_psi" in df.columns:
        x, y = clean_xy(t, pd.to_numeric(df["external_psi"], errors="coerce"), *PRESSURE_RANGE)
        x, y = insert_gap_nans(x, y)
        series["dc_external_p"] = {
            "id": "dc_external_p",
            "label": "Intelli-Log External Pressure",
            "panel": "pressure",
            "unit": "psia",
            "source": "datacan",
            "color": "#F0C674",
            "axis": "y",
            "x": x,
            "y": y,
        }
    if "Tension" in df.columns:
        x, y = clean_xy(t, pd.to_numeric(df["Tension"], errors="coerce"), *TENSION_RANGE)
        x, y = insert_gap_nans(x, y)
        series["dc_tension"] = {
            "id": "dc_tension",
            "label": "Intelli-Log Tension",
            "panel": "weight",
            "unit": "lbf",
            "source": "datacan",
            "color": "#E07A3D",
            "axis": "y2",
            "x": x,
            "y": y,
        }

    return {
        "file": str(path),
        "source": "datacan",
        "series": series,
        "comments": [],
    }
