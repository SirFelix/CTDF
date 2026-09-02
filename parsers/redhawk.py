from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .clean import clean_xy, insert_gap_nans

PRESSURE_RANGE = (-200.0, 15_000.0)
SPEED_RANGE = (-250.0, 250.0)
DEPTH_RANGE = (-200.0, 4_000.0)
WEIGHT_RANGE = (-50_000.0, 150_000.0)
FLOW_RANGE = (-2.0, 300.0)


def _read_text(path: Path) -> list[str]:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=enc).splitlines()
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _header_index(lines: list[str], markers: tuple[str, ...]) -> int:
    for i, line in enumerate(lines[:30]):
        low = line.lower()
        if all(m.lower() in low for m in markers):
            return i
    raise ValueError("Could not find RedHawk header row")


def _to_utc_ms(series: pd.Series, tz_name: str):
    ts = pd.to_datetime(series, errors="coerce", format="mixed")
    tz = ZoneInfo(tz_name)
    if getattr(ts.dt, "tz", None) is None:
        ts = ts.dt.tz_localize(tz, ambiguous="infer", nonexistent="shift_forward")
    else:
        ts = ts.dt.tz_convert(tz)
    ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
    return ts.to_numpy(dtype="datetime64[ns]").astype("int64").astype("float64") / 1_000_000.0


def _norm_col(name: str) -> str:
    return " ".join(str(name).strip().lower().split())


FIELD_MAP = {
    "speed": ("rh_speed", "RedHawk Speed", "speed", "ft/min", "#F472B6", SPEED_RANGE, "y", True),
    "return rate": ("rh_return_rate", "RedHawk Return Rate", "pressure", "bpm", "#2DD4BF", FLOW_RANGE, "y2", True),
    "pump rate": ("rh_pump_rate", "RedHawk Pump Rate", "pressure", "bpm", "#14B8A6", FLOW_RANGE, "y2", True),
    "depth": ("rh_depth", "RedHawk Depth", "depth", "ft", "#A3E635", DEPTH_RANGE, "y", True),
    "wellhead": ("rh_wellhead", "RedHawk Wellhead", "pressure", "psi", "#34D399", PRESSURE_RANGE, "y", True),
    "weight": ("rh_weight", "RedHawk Weight", "weight", "lbf", "#FBBF24", WEIGHT_RANGE, "y", True),
    "circ pressure": ("rh_circ", "RedHawk Circ Pressure", "pressure", "psi", "#22C55E", PRESSURE_RANGE, "y", True),
    "injector depth": ("rh_inj_depth", "RedHawk Injector Depth", "depth", "ft", "#65A30D", DEPTH_RANGE, "y", False),
    "traction pressure": ("rh_traction", "RedHawk Traction Pressure", "pressure", "psi", "#86EFAC", PRESSURE_RANGE, "y", False),
    "differential pressure": ("rh_diff", "RedHawk Differential Pressure", "pressure", "psi", "#4ADE80", PRESSURE_RANGE, "y", False),
}


def parse_redhawk_fieldlog(path: str | Path, tz_name: str = "America/Chicago") -> dict:
    path = Path(path)
    lines = _read_text(path)
    header_i = _header_index(lines, ("date time", "comment"))
    from io import StringIO

    body = "\n".join(lines[header_i:])
    df = pd.read_csv(StringIO(body), engine="c", on_bad_lines="skip", low_memory=False)
    df.columns = [str(c).strip() for c in df.columns]
    time_col = df.columns[0]
    t = _to_utc_ms(df[time_col], tz_name)

    series: dict[str, dict] = {}
    comments: list[dict] = []
    col_lookup = {_norm_col(c): c for c in df.columns}

    for key, meta in FIELD_MAP.items():
        sid, label, panel, unit, color, rng, axis, default_on = meta
        col = col_lookup.get(key)
        if not col:
            continue
        x, y = clean_xy(t, pd.to_numeric(df[col], errors="coerce"), *rng)
        x, y = insert_gap_nans(x, y)
        if y.size == 0:
            continue
        series[sid] = {
            "id": sid,
            "label": label,
            "panel": panel,
            "unit": unit,
            "source": "redhawk",
            "color": color,
            "axis": axis,
            "x": x,
            "y": y,
            "default_on": default_on,
        }

    comment_col = col_lookup.get("comment")
    if comment_col:
        texts = df[comment_col].fillna("").astype(str).str.strip().str.strip('"')
        keep = texts != ""
        for ms, text in zip(t[keep.to_numpy()], texts[keep].tolist()):
            if not pd.isna(ms):
                comments.append({"t": float(ms), "text": text, "source": "redhawk"})

    return {
        "file": str(path),
        "source": "redhawk_field",
        "series": series,
        "comments": comments,
    }


def parse_redhawk_joblog(path: str | Path, tz_name: str = "America/Chicago") -> dict:
    path = Path(path)
    lines = _read_text(path)
    header_i = None
    for i, line in enumerate(lines[:30]):
        low = line.lower()
        if "comment" in low and ("datatime" in low or "date" in low):
            header_i = i
            break
    if header_i is None:
        raise ValueError(f"Could not find JobLog header in {path.name}")

    from io import StringIO

    df = pd.read_csv(StringIO("\n".join(lines[header_i:])), engine="c", on_bad_lines="skip")
    df.columns = [str(c).strip() for c in df.columns]
    time_col = df.columns[0]
    comment_col = next((c for c in df.columns if c.lower().startswith("comment")), None)
    if comment_col is None:
        return {"file": str(path), "source": "redhawk_job", "series": {}, "comments": []}

    t = _to_utc_ms(df[time_col], tz_name)
    texts = df[comment_col].fillna("").astype(str).str.strip().str.strip('"')
    comments = []
    for ms, text in zip(t, texts.tolist()):
        if text and pd.notna(ms):
            comments.append({"t": float(ms), "text": text, "source": "redhawk"})
    return {
        "file": str(path),
        "source": "redhawk_job",
        "series": {},
        "comments": comments,
    }
