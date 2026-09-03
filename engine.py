from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from parsers.clean import insert_gap_nans
from parsers.daq import parse_daq
from parsers.datacan import parse_datacan
from parsers.redhawk import parse_redhawk_fieldlog, parse_redhawk_joblog


PANELS = ["pressure", "weight", "depth", "speed"]
PANEL_TITLES = {
    "pressure": "Pressure & Flow",
    "weight": "Weight & Tension",
    "depth": "Depth",
    "speed": "Speed",
}


def lttb(x: np.ndarray, y: np.ndarray, n_out: int) -> tuple[np.ndarray, np.ndarray]:
    """Largest-Triangle-Three-Buckets downsampling. Keeps first/last points."""
    n = int(x.size)
    if n <= n_out or n_out < 3:
        return x, y
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    valid = np.isfinite(x) & np.isfinite(y)
    if valid.sum() <= n_out:
        return x, y
    xv = x[valid]
    yv = y[valid]
    n = xv.size
    if n <= n_out:
        return xv, yv

    bucket_size = (n - 2) / (n_out - 2)
    sampled_x = np.empty(n_out, dtype=np.float64)
    sampled_y = np.empty(n_out, dtype=np.float64)
    sampled_x[0] = xv[0]
    sampled_y[0] = yv[0]
    sampled_x[-1] = xv[-1]
    sampled_y[-1] = yv[-1]

    a_index = 0
    for i in range(n_out - 2):
        range_start = int(np.floor((i + 1) * bucket_size)) + 1
        range_end = int(np.floor((i + 2) * bucket_size)) + 1
        range_end = min(range_end, n)
        avg_start = range_end
        avg_end = int(np.floor((i + 3) * bucket_size)) + 1
        avg_end = min(avg_end, n)
        if avg_end <= avg_start:
            avg_start = range_end
            avg_end = min(range_end + 1, n)
        avg_x = np.mean(xv[avg_start:avg_end]) if avg_end > avg_start else xv[range_end - 1]
        avg_y = np.mean(yv[avg_start:avg_end]) if avg_end > avg_start else yv[range_end - 1]

        point_ax = xv[a_index]
        point_ay = yv[a_index]
        rng = slice(range_start, range_end)
        areas = np.abs(
            (point_ax - avg_x) * (yv[rng] - point_ay) - (point_ax - xv[rng]) * (avg_y - point_ay)
        )
        if areas.size == 0:
            a_index = range_start
        else:
            a_index = range_start + int(np.argmax(areas))
        sampled_x[i + 1] = xv[a_index]
        sampled_y[i + 1] = yv[a_index]
    return sampled_x, sampled_y


def lttb_preserve_gaps(x: np.ndarray, y: np.ndarray, n_out: int) -> tuple[np.ndarray, np.ndarray]:
    if x.size == 0:
        return x, y
    finite = np.isfinite(x) & np.isfinite(y)
    if finite.all():
        return lttb(x, y, n_out)
    padded = np.concatenate([[False], finite, [False]])
    d = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    total = int(finite.sum())
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    for start, end in zip(starts, ends):
        n_seg = max(3, int(round(n_out * (end - start) / max(total, 1))))
        xa, ya = lttb(x[start:end], y[start:end], n_seg)
        if xs:
            xs.append(np.array([xa[0] - 1.0], dtype=np.float64))
            ys.append(np.array([np.nan], dtype=np.float64))
        xs.append(xa)
        ys.append(ya)
    if not xs:
        return x[:0], y[:0]
    return np.concatenate(xs), np.concatenate(ys)


def window_series(x: np.ndarray, y: np.ndarray, t0: float | None, t1: float | None):
    if x.size == 0:
        return x, y
    mask = np.ones(x.size, dtype=bool)
    if t0 is not None:
        mask &= x >= t0
    if t1 is not None:
        mask &= x <= t1
    if not mask.any():
        return x[:0], y[:0]
    idx = np.flatnonzero(mask)
    left = max(idx[0] - 1, 0)
    right = min(idx[-1] + 2, x.size)
    return x[left:right], y[left:right]


def _concat_xy(items: list[tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    xs = [a for a, _ in items if a.size]
    ys = [b for _, b in items if b.size]
    if not xs:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
    x = np.concatenate(xs)
    y = np.concatenate(ys)
    order = np.argsort(x)
    return x[order], y[order]


def _resolve_tz(name: str | None, job_tz: str) -> str:
    if not name or name in ("job", "same", "same_as_job"):
        return job_tz
    return name


def _shift_parsed(parsed: dict, hours: float) -> dict:
    if not hours:
        return parsed
    dt = float(hours) * 3_600_000.0
    for ser in parsed["series"].values():
        ser["x"] = np.asarray(ser["x"], dtype=np.float64) + dt
    for c in parsed["comments"]:
        c["t"] = float(c["t"]) + dt
    return parsed


def _dedupe_comments(comments: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out = []
    for c in sorted(comments, key=lambda d: (d["t"], d["source"], d["text"])):
        text = " ".join(c["text"].split())
        if not text:
            continue
        key = (round(c["t"] / 1000.0), c["source"], text.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"t": c["t"], "text": text, "source": c["source"]})
    return out


@dataclass
class JobSession:
    tz_name: str = "America/Chicago"
    series: dict[str, dict] = field(default_factory=dict)
    comments: list[dict] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    def clear(self) -> None:
        self.series = {}
        self.comments = []
        self.files = []
        self.log = []

    def _note(self, msg: str) -> None:
        self.log.append(msg)

    def _merge_parsed(self, parsed: dict) -> None:
        self.files.append(
            {
                "file": parsed["file"],
                "source": parsed["source"],
                "series": list(parsed["series"].keys()),
                "comments": len(parsed["comments"]),
            }
        )
        for sid, ser in parsed["series"].items():
            if sid in self.series:
                x, y = _concat_xy(
                    [(self.series[sid]["x"], self.series[sid]["y"]), (ser["x"], ser["y"])]
                )
                x, y = insert_gap_nans(x, y)
                self.series[sid]["x"] = x
                self.series[sid]["y"] = y
            else:
                self.series[sid] = ser
        self.comments.extend(parsed["comments"])

    def load(
        self,
        daq_files: list[str],
        datacan_files: list[str],
        redhawk_field: list[str],
        redhawk_job: list[str],
        tz_name: str | None = None,
        tz_job: str | None = None,
        tz_datacan: str = "job",
        tz_redhawk: str = "job",
        shift_daq: float = 0,
        shift_datacan: float = 0,
        shift_redhawk: float = 0,
        on_progress=None,
    ) -> None:
        self.clear()
        job_tz = tz_job or tz_name or "America/Chicago"
        self.tz_name = job_tz
        il_tz = _resolve_tz(tz_datacan, job_tz)
        rh_tz = _resolve_tz(tz_redhawk, job_tz)

        def report(pct: float, msg: str, log: bool = True) -> None:
            if log:
                self._note(msg)
            if on_progress:
                on_progress(max(0, min(100, int(pct))), msg)

        def daq_reader(path: str) -> dict:
            return _shift_parsed(parse_daq(path), shift_daq)

        def il_reader(path: str) -> dict:
            return _shift_parsed(parse_datacan(path, tz_name=il_tz), shift_datacan)

        def rh_field_reader(path: str) -> dict:
            return _shift_parsed(parse_redhawk_fieldlog(path, tz_name=rh_tz), shift_redhawk)

        def rh_job_reader(path: str) -> dict:
            return _shift_parsed(parse_redhawk_joblog(path, tz_name=rh_tz), shift_redhawk)

        jobs: list[tuple[str, str, object, int]] = []

        def enqueue(kind: str, paths: list[str], reader) -> None:
            for path in paths:
                try:
                    size = max(Path(path).stat().st_size, 1)
                except OSError:
                    size = 1
                jobs.append((kind, path, reader, size))

        enqueue("DAQ", daq_files, daq_reader)
        enqueue("Intelli-Log", datacan_files, il_reader)
        enqueue("RedHawk FieldLog", redhawk_field, rh_field_reader)
        enqueue("RedHawk JobLog", redhawk_job, rh_job_reader)

        report(
            1,
            f"Time zones: DAQ UTC{shift_daq:+g}h, Intelli-Log {il_tz}{shift_datacan:+g}h, "
            f"RedHawk {rh_tz}{shift_redhawk:+g}h",
        )

        total = sum(item[3] for item in jobs) or 1
        done = 0
        report(2, f"Starting {len(jobs)} file{'s' if len(jobs) != 1 else ''}")
        for kind, path, reader, size in jobs:
            name = Path(path).name
            report(2 + 90 * done / total, f"Loading {kind} {name}")
            self._merge_parsed(reader(path))
            done += size
            report(2 + 90 * done / total, f"Loaded {kind} {name}")

        report(94, "Combining comments")
        self.comments = _dedupe_comments(self.comments)
        report(
            100,
            f"Loaded {len(self.series)} series, "
            f"{sum(int(s['x'].size) for s in self.series.values()):,} raw points, "
            f"{len(self.comments)} comments",
        )

    def time_range(self) -> tuple[float | None, float | None]:
        mins = []
        maxs = []
        for ser in self.series.values():
            x = ser["x"]
            if x.size:
                finite = x[np.isfinite(x)]
                if finite.size:
                    mins.append(float(finite.min()))
                    maxs.append(float(finite.max()))
        if not mins:
            return None, None
        return min(mins), max(maxs)

    def catalog(self) -> list[dict]:
        items = []
        for ser in self.series.values():
            x = ser["x"]
            items.append(
                {
                    "id": ser["id"],
                    "label": ser["label"],
                    "panel": ser["panel"],
                    "unit": ser["unit"],
                    "source": ser["source"],
                    "color": ser["color"],
                    "axis": ser["axis"],
                    "default_on": ser.get("default_on", True),
                    "n": int(np.isfinite(ser["y"]).sum()) if ser["y"].size else 0,
                    "t0": float(x[np.isfinite(x)].min()) if x.size and np.isfinite(x).any() else None,
                    "t1": float(x[np.isfinite(x)].max()) if x.size and np.isfinite(x).any() else None,
                }
            )
        order = {p: i for i, p in enumerate(PANELS)}
        items.sort(key=lambda d: (order.get(d["panel"], 99), d["label"]))
        return items

    def downsample(
        self,
        t0: float | None,
        t1: float | None,
        n_points: int,
        series_ids: list[str] | None = None,
        full_resolution: bool = False,
    ) -> list[dict]:
        n_points = max(int(n_points), 200)
        ids = series_ids or list(self.series.keys())
        out = []
        for sid in ids:
            ser = self.series.get(sid)
            if not ser:
                continue
            x, y = window_series(ser["x"], ser["y"], t0, t1)
            if full_resolution:
                xs, ys = x, y
            else:
                xs, ys = lttb_preserve_gaps(x, y, n_points)
            out.append(
                {
                    "id": ser["id"],
                    "label": ser["label"],
                    "panel": ser["panel"],
                    "unit": ser["unit"],
                    "source": ser["source"],
                    "color": ser["color"],
                    "axis": ser["axis"],
                    "x": xs.tolist(),
                    "y": [None if not np.isfinite(v) else float(v) for v in ys],
                    "n_raw": int(x.size),
                    "n_plot": int(xs.size),
                }
            )
        return out

    def comments_in_range(self, t0: float | None, t1: float | None, include_events: bool) -> list[dict]:
        out = []
        for c in self.comments:
            if not include_events and c["source"] == "daq_event":
                continue
            if t0 is not None and c["t"] < t0:
                continue
            if t1 is not None and c["t"] > t1:
                continue
            out.append(c)
        return out
