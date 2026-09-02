from __future__ import annotations

import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .clean import SENTINEL, clean_xy, insert_gap_nans

DAQ_PRESSURE_RANGE = (-500.0, 15_000.0)
SPEED_RANGE = (-250.0, 250.0)
DEPTH_RANGE = (-200.0, 40_000.0)
WEIGHT_RANGE = (-10_000.0, 150_000.0)
FLOW_RANGE = (-2.0, 50.0)


def _epoch_ms(timestamp_s: np.ndarray) -> np.ndarray:
    return np.asarray(timestamp_s, dtype=np.float64) * 1000.0


def _table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    row = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def _read_table(con: sqlite3.Connection, table: str, columns: list[str]) -> pd.DataFrame:
    existing = {row[1] for row in con.execute(f"PRAGMA table_info([{table}])")}
    use = [c for c in columns if c in existing]
    if not use:
        return pd.DataFrame()
    col_sql = ", ".join(f"[{c}]" for c in use)
    return pd.read_sql_query(f"SELECT {col_sql} FROM [{table}]", con)


def detect_daq_timezone(path: str | Path, candidates: list[str]) -> dict | None:
    """Infer the recording timezone from ops_log UTC epoch vs local datetime."""
    path = Path(path)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        df = None
        for table in ("ops_log", "daq_data"):
            if not _table_exists(cur, table):
                continue
            existing = {row[1] for row in con.execute(f"PRAGMA table_info([{table}])")}
            if "timestamp_s" not in existing:
                continue
            local_col = next(
                (
                    c
                    for c in ("datetime", "date_time", "local_time", "localtime", "local_datetime")
                    if c in existing
                ),
                None,
            )
            if local_col is None:
                local_col = next((c for c in existing if "datetime" in c.lower()), None)
            if local_col is None:
                continue
            df = pd.read_sql_query(
                f"SELECT [timestamp_s] AS timestamp_s, [{local_col}] AS datetime "
                f"FROM [{table}] WHERE [timestamp_s] IS NOT NULL AND [{local_col}] IS NOT NULL "
                f"AND CAST([{local_col}] AS TEXT) != '' LIMIT 250",
                con,
            )
            if df is not None and not df.empty:
                break
        if df is None or df.empty:
            return None

        utc = pd.to_datetime(df["timestamp_s"], unit="s", utc=True, errors="coerce")
        local = pd.to_datetime(df["datetime"], errors="coerce", format="mixed")
        mask = utc.notna() & local.notna()
        utc = utc.loc[mask]
        local = local.loc[mask]
        if local.empty:
            return None
        if getattr(local.dt, "tz", None) is not None:
            local = local.dt.tz_localize(None)

        best_id = None
        best_hits = -1
        n = int(local.size)
        for zid in candidates:
            try:
                tz = ZoneInfo(zid)
            except Exception:
                continue
            try:
                loc = local.dt.tz_localize(tz, ambiguous="infer", nonexistent="shift_forward")
            except Exception:
                try:
                    loc = local.dt.tz_localize(tz, ambiguous=True, nonexistent="shift_forward")
                except Exception:
                    continue
            as_utc = loc.dt.tz_convert("UTC")
            hits = int(((as_utc - utc).dt.total_seconds().abs() <= 120).sum())
            if hits > best_hits:
                best_hits = hits
                best_id = zid
        if best_id is None or best_hits < max(2, int(n * 0.25)):
            return None
        utc_naive = utc.dt.tz_convert("UTC").dt.tz_localize(None)
        offset_h = float(((local - utc_naive).dt.total_seconds() / 3600.0).median())
        return {
            "id": best_id,
            "matches": best_hits,
            "samples": n,
            "offset_hours": round(offset_h, 2),
            "file": path.name,
        }
    finally:
        con.close()


def parse_daq(path: str | Path) -> dict:
    path = Path(path)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        series: dict[str, dict] = {}
        comments: list[dict] = []

        if _table_exists(cur, "daq_data"):
            df = _read_table(
                con,
                "daq_data",
                ["timestamp_s", "daq_pressure_psi", "daq_filt_pressure_psi"],
            )
            if not df.empty:
                t = _epoch_ms(df["timestamp_s"].to_numpy())
                if "daq_pressure_psi" in df.columns:
                    x, y = clean_xy(t, df["daq_pressure_psi"], *DAQ_PRESSURE_RANGE)
                    x, y = insert_gap_nans(x, y)
                    series["daq_pressure"] = {
                        "id": "daq_pressure",
                        "label": "DAQ Surface Pressure",
                        "panel": "pressure",
                        "unit": "psi",
                        "source": "daq",
                        "color": "#5B9BD5",
                        "axis": "y",
                        "x": x,
                        "y": y,
                    }
                if "daq_filt_pressure_psi" in df.columns:
                    x, y = clean_xy(t, df["daq_filt_pressure_psi"], *DAQ_PRESSURE_RANGE)
                    x, y = insert_gap_nans(x, y)
                    series["daq_pressure_filt"] = {
                        "id": "daq_pressure_filt",
                        "label": "DAQ Filtered Pressure",
                        "panel": "pressure",
                        "unit": "psi",
                        "source": "daq",
                        "color": "#9DC3E6",
                        "axis": "y",
                        "x": x,
                        "y": y,
                        "default_on": False,
                    }

        if _table_exists(cur, "detection_speed_data"):
            df = _read_table(
                con,
                "detection_speed_data",
                ["timestamp_s", "detection_pressure_psi", "tractor_speed_fpm"],
            )
            if not df.empty:
                t = _epoch_ms(df["timestamp_s"].to_numpy())
                if "tractor_speed_fpm" in df.columns:
                    x, y = clean_xy(t, df["tractor_speed_fpm"], *SPEED_RANGE)
                    x, y = insert_gap_nans(x, y)
                    series["daq_tractor_speed"] = {
                        "id": "daq_tractor_speed",
                        "label": "DAQ Tractor Speed",
                        "panel": "speed",
                        "unit": "ft/min",
                        "source": "daq",
                        "color": "#C084FC",
                        "axis": "y",
                        "x": x,
                        "y": y,
                    }
                if "detection_pressure_psi" in df.columns:
                    x, y = clean_xy(t, df["detection_pressure_psi"], *DAQ_PRESSURE_RANGE)
                    x, y = insert_gap_nans(x, y)
                    if y.size and np.isfinite(y).any():
                        series["daq_detection_pressure"] = {
                            "id": "daq_detection_pressure",
                            "label": "DAQ Detection Pressure",
                            "panel": "pressure",
                            "unit": "psi",
                            "source": "daq",
                            "color": "#7C3AED",
                            "axis": "y",
                            "x": x,
                            "y": y,
                            "default_on": False,
                        }

        if _table_exists(cur, "rig_data"):
            df = _read_table(
                con,
                "rig_data",
                [
                    "timestamp_s",
                    "rig_timestamp_s",
                    "ct_depth_ft",
                    "ct_pressure_psi",
                    "ct_speed_fpm",
                    "ct_weight_lbs",
                    "wh_pressure_psi",
                    "wh_flow_rate_bpm",
                    "n2_flow_rate_scf",
                ],
            )
            if not df.empty:
                recv = df["timestamp_s"].to_numpy(dtype=np.float64)
                if "rig_timestamp_s" in df.columns:
                    rig_ts = df["rig_timestamp_s"].to_numpy(dtype=np.float64)
                    aligned = np.isfinite(rig_ts) & (np.abs(rig_ts - recv) <= 120.0)
                    df = df.loc[aligned].copy()
                    t = _epoch_ms(df["rig_timestamp_s"].to_numpy())
                else:
                    t = _epoch_ms(df["timestamp_s"].to_numpy())

                mapping = [
                    ("ct_pressure_psi", "daq_rig_ct_pressure", "DAQ Rig CT Pressure", "pressure", "psi", "#1D4E89", DAQ_PRESSURE_RANGE, "y", False),
                    ("wh_pressure_psi", "daq_rig_wh_pressure", "DAQ Rig Wellhead", "pressure", "psi", "#2E75B6", DAQ_PRESSURE_RANGE, "y", False),
                    ("wh_flow_rate_bpm", "daq_rig_pump_rate", "DAQ Rig Pump Rate", "pressure", "bpm", "#00A3A1", FLOW_RANGE, "y2", False),
                    ("ct_weight_lbs", "daq_rig_weight", "DAQ Rig Weight", "weight", "lbf", "#7A9E9F", WEIGHT_RANGE, "y", False),
                    ("ct_depth_ft", "daq_rig_depth", "DAQ Rig Depth", "depth", "ft", "#4B5563", DEPTH_RANGE, "y", False),
                    ("ct_speed_fpm", "daq_rig_speed", "DAQ Rig Speed", "speed", "ft/min", "#DB2777", SPEED_RANGE, "y", False),
                ]
                for col, sid, label, panel, unit, color, rng, axis, default_on in mapping:
                    if col not in df.columns:
                        continue
                    x, y = clean_xy(t, df[col], *rng)
                    x, y = insert_gap_nans(x, y)
                    if y.size == 0:
                        continue
                    series[sid] = {
                        "id": sid,
                        "label": label,
                        "panel": panel,
                        "unit": unit,
                        "source": "daq_rig",
                        "color": color,
                        "axis": axis,
                        "x": x,
                        "y": y,
                        "default_on": default_on,
                    }

        if _table_exists(cur, "ops_log"):
            df = _read_table(con, "ops_log", ["timestamp_s", "datetime", "comments"])
            if not df.empty:
                texts = df["comments"].fillna("").astype(str).str.strip()
                keep = texts != ""
                df = df.loc[keep]
                texts = texts.loc[keep]
                t = _epoch_ms(df["timestamp_s"].to_numpy())
                for ms, text in zip(t, texts.tolist()):
                    if not np.isfinite(ms):
                        continue
                    comments.append({"t": float(ms), "text": text, "source": "daq"})

        if _table_exists(cur, "nm_events"):
            df = _read_table(con, "nm_events", ["timestamp_s", "event", "mode", "psi"])
            if not df.empty:
                t = _epoch_ms(df["timestamp_s"].to_numpy())
                for i, ms in enumerate(t):
                    if not np.isfinite(ms):
                        continue
                    event = str(df["event"].iloc[i]) if "event" in df.columns else "event"
                    mode = str(df["mode"].iloc[i]) if "mode" in df.columns else ""
                    psi = df["psi"].iloc[i] if "psi" in df.columns else np.nan
                    psi_txt = f" {float(psi):.0f} psi" if pd.notna(psi) and abs(float(psi)) < SENTINEL else ""
                    comments.append(
                        {
                            "t": float(ms),
                            "text": f"Detection {event} ({mode}){psi_txt}".strip(),
                            "source": "daq_event",
                        }
                    )
    finally:
        con.close()

    return {
        "file": str(path),
        "source": "daq",
        "series": series,
        "comments": comments,
    }
