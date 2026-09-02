from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import plotly.graph_objects as go
from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from plotly.subplots import make_subplots
from pydantic import BaseModel, Field

from engine import JobSession, PANEL_TITLES, PANELS

STATIC = ROOT / "static"
DEFAULT_DATA = ROOT.parent / "Raw Data"


def app_version() -> str:
    try:
        text = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return text or "0.0.0"


session = JobSession()
app = FastAPI(title="CTDF — Coil-Tubing Data Fusion")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ScanRequest(BaseModel):
    folder: str = ""


class LoadRequest(BaseModel):
    daq: list[str] = Field(default_factory=list)
    datacan: list[str] = Field(default_factory=list)
    redhawk_field: list[str] = Field(default_factory=list)
    redhawk_job: list[str] = Field(default_factory=list)
    tz: str = "America/Chicago"


class PlotRequest(BaseModel):
    t0: float | None = None
    t1: float | None = None
    n_points: int = 4000
    series_ids: list[str] | None = None
    include_events: bool = False


class ExportRequest(PlotRequest):
    title: str = "CTDF — Coil-Tubing Data Fusion"
    dark: bool = True
    comment_width: float = 1.0


def _classify(path: Path) -> str | None:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix == ".db":
        return "daq"
    if name.startswith("fieldlog") and suffix == ".csv":
        return "redhawk_field"
    if name.startswith("joblog") and suffix == ".csv":
        return "redhawk_job"
    if suffix == ".txt":
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                head = "".join(handle.readline() for _ in range(12))
            if "Serial Number of Tool" in head or ("Date" in head and "Real Time" in head):
                return "datacan"
        except OSError:
            return None
    return None


def _scan_folder(folder: Path) -> dict[str, list[dict]]:
    found = {"daq": [], "datacan": [], "redhawk_field": [], "redhawk_job": []}
    if not folder.exists():
        return found
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        kind = _classify(path)
        if not kind:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        found[kind].append(
            {
                "path": str(path),
                "name": path.name,
                "rel": str(path.relative_to(folder)),
                "size": size,
            }
        )
    for key in found:
        found[key].sort(key=lambda d: d["rel"].lower())
    return found


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    return html.replace("__CTDF_VERSION__", app_version())


@app.get("/api/defaults")
def defaults() -> dict:
    folder = str(DEFAULT_DATA) if DEFAULT_DATA.exists() else str(ROOT.parent)
    return {
        "folder": folder,
        "tz": "America/Chicago",
        "has_raw_data": DEFAULT_DATA.exists(),
        "version": app_version(),
    }


def _pick_folder_tk(start: str) -> str:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.update()
    try:
        root.attributes("-topmost", True)
        root.lift()
        root.focus_force()
    except tk.TclError:
        pass
    path = filedialog.askdirectory(
        parent=root,
        initialdir=start,
        title="Select job folder",
        mustexist=True,
    )
    root.destroy()
    return str(path or "")


def _pick_folder_win(start: str) -> str | None:
    start_lit = start.replace("'", "''")
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = 'Select the job folder'
$d.ShowNewFolderButton = $false
$d.SelectedPath = '{start_lit}'
try {{ $d.UseDescriptionForTitle = $true }} catch {{}}
$r = $d.ShowDialog()
if ($r -eq [System.Windows.Forms.DialogResult]::OK) {{ $d.SelectedPath }}
"""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=600,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (proc.stdout or "").strip()


def _pick_folder(start: str) -> str:
    if sys.platform == "win32":
        picked = _pick_folder_win(start)
        if picked is not None:
            return picked
    return _pick_folder_tk(start)


@app.post("/api/browse-folder")
def browse_folder(req: ScanRequest) -> dict:
    start = req.folder.strip()
    if not start or not Path(start).exists():
        start = str(DEFAULT_DATA if DEFAULT_DATA.exists() else ROOT.parent)
    picked = _pick_folder(start)
    if not picked:
        return {"folder": start, "cancelled": True}
    return {"folder": picked, "cancelled": False}


@app.post("/api/scan")
def scan(req: ScanRequest) -> dict:
    folder = Path(req.folder.strip() or DEFAULT_DATA)
    if not folder.exists():
        raise HTTPException(400, f"Folder not found: {folder}")
    found = _scan_folder(folder)
    counts = {k: len(v) for k, v in found.items()}
    return {"folder": str(folder), "files": found, "counts": counts}


_load_lock = threading.Lock()
_load_state: dict = {
    "busy": False,
    "pct": 0,
    "msg": "",
    "error": None,
    "result": None,
}


def _load_snapshot() -> dict:
    with _load_lock:
        return {
            "busy": _load_state["busy"],
            "pct": _load_state["pct"],
            "msg": _load_state["msg"],
            "error": _load_state["error"],
            "result": _load_state["result"],
        }


def _load_update(**kwargs) -> None:
    with _load_lock:
        _load_state.update(kwargs)


@app.post("/api/load")
async def load(req: LoadRequest) -> dict:
    def _check(paths: list[str]) -> list[str]:
        out = []
        for p in paths:
            path = Path(p)
            if not path.is_file():
                raise HTTPException(400, f"File not found: {p}")
            out.append(str(path))
        return out

    daq_files = _check(req.daq)
    datacan_files = _check(req.datacan)
    redhawk_field = _check(req.redhawk_field)
    redhawk_job = _check(req.redhawk_job)

    with _load_lock:
        if _load_state["busy"]:
            raise HTTPException(409, "A load is already running")
        _load_state.update(busy=True, pct=1, msg="Starting…", error=None, result=None)

    def run() -> None:
        def on_progress(pct: int, msg: str) -> None:
            _load_update(pct=pct, msg=msg)

        try:
            session.load(
                daq_files=daq_files,
                datacan_files=datacan_files,
                redhawk_field=redhawk_field,
                redhawk_job=redhawk_job,
                tz_name=req.tz,
                on_progress=on_progress,
            )
            t0, t1 = session.time_range()
            result = jsonable_encoder(
                {
                    "ok": True,
                    "log": session.log,
                    "files": session.files,
                    "catalog": session.catalog(),
                    "t0": t0,
                    "t1": t1,
                    "n_comments": len(
                        [c for c in session.comments if c["source"] != "daq_event"]
                    ),
                    "n_events": len(
                        [c for c in session.comments if c["source"] == "daq_event"]
                    ),
                    "n_points": int(sum(s["x"].size for s in session.series.values())),
                }
            )
            _load_update(pct=100, msg="Loaded", result=result, error=None)
        except Exception as exc:
            _load_update(error=f"Failed to load files: {exc}", result=None)
        finally:
            _load_update(busy=False)

    await asyncio.get_running_loop().run_in_executor(None, run)
    snap = _load_snapshot()
    if snap["error"]:
        raise HTTPException(400, snap["error"])
    if not snap["result"]:
        raise HTTPException(500, "Load finished without data")
    return snap["result"]


def _progress_view() -> dict:
    snap = _load_snapshot()
    return {
        "busy": snap["busy"],
        "pct": snap["pct"],
        "msg": snap["msg"],
        "error": snap["error"],
    }


@app.get("/api/progress")
def progress() -> dict:
    return _progress_view()


@app.get("/api/load/status")
def load_status() -> dict:
    return _progress_view()


@app.post("/api/plot")
def plot(req: PlotRequest) -> dict:
    if not session.series:
        raise HTTPException(400, "No data loaded")
    traces = session.downsample(req.t0, req.t1, req.n_points, req.series_ids)
    comments = session.comments_in_range(req.t0, req.t1, req.include_events)
    return {
        "traces": traces,
        "comments": comments,
        "panels": PANELS,
        "titles": PANEL_TITLES,
    }


def _export_figure(req: ExportRequest) -> go.Figure:
    if not session.series:
        raise HTTPException(400, "No data loaded")
    traces = session.downsample(req.t0, req.t1, req.n_points, req.series_ids)
    comments = session.comments_in_range(req.t0, req.t1, req.include_events)
    dark = req.dark
    bg = "#11151c" if dark else "#ffffff"
    paper = "#0b0d12" if dark else "#f4f5f7"
    grid = "#2a3140" if dark else "#8b929e"
    text = "#e6e8ee" if dark else "#1c212b"
    muted = "#9aa3b5" if dark else "#2a3038"

    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.055,
        subplot_titles=[PANEL_TITLES[p] for p in PANELS],
        specs=[[{"secondary_y": True}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
    )
    row_of = {p: i + 1 for i, p in enumerate(PANELS)}
    for tr in traces:
        row = row_of[tr["panel"]]
        secondary = tr["axis"] == "y2" and tr["panel"] in ("pressure", "weight")
        fig.add_trace(
            go.Scatter(
                x=tr["x"],
                y=tr["y"],
                name=tr["label"],
                mode="lines",
                line=dict(color=tr["color"], width=1.2),
                hovertemplate="%{x}<br>%{y:.2f} " + tr["unit"] + "<extra>" + tr["label"] + "</extra>",
            ),
            row=row,
            col=1,
            secondary_y=secondary,
        )

    line_color = "rgb(168,176,192)" if req.dark else "rgb(92,102,120)"
    line_opacity = 0.28 if req.dark else 0.22
    for c in comments:
        for row in range(1, 5):
            fig.add_vline(
                x=c["t"],
                row=row,
                col=1,
                line_width=max(0.1, float(req.comment_width)),
                line_color=line_color,
                opacity=line_opacity,
                annotation_text="",
            )

    top_vals = []
    for tr in traces:
        if tr["panel"] == "pressure" and tr["axis"] != "y2":
            top_vals.extend(v for v in tr["y"] if v is not None)
    comment_y = max(top_vals) if top_vals else 1.0
    if comments:
        fig.add_trace(
            go.Scatter(
                x=[c["t"] for c in comments],
                y=[comment_y] * len(comments),
                mode="markers",
                marker=dict(
                    size=10,
                    color=line_color,
                    symbol="line-ns-open",
                    line=dict(width=1.5),
                ),
                name="Comments",
                text=[f"{c['source']}: {c['text']}" for c in comments],
                hovertemplate="%{x}<br>%{text}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    fig.update_layout(
        title=req.title,
        paper_bgcolor=paper,
        plot_bgcolor=bg,
        font=dict(color=text, family="Segoe UI, Arial, sans-serif", size=12),
        legend=dict(orientation="h", y=1.08, x=0, font=dict(size=11)),
        margin=dict(l=70, r=70, t=90, b=50),
        hovermode="x unified",
        height=1100,
        width=1400,
    )
    fig.update_xaxes(showgrid=True, gridcolor=grid, color=muted, type="date", matches="x")
    fig.update_yaxes(showgrid=True, gridcolor=grid, color=muted, zeroline=False)
    fig.update_yaxes(title_text="psi", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="bpm", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="lbf", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="tension lbf", row=2, col=1, secondary_y=True)
    fig.update_yaxes(title_text="ft", row=3, col=1)
    fig.update_yaxes(title_text="ft/min", row=4, col=1)
    fig.update_xaxes(title_text="Time", row=4, col=1)
    return fig


@app.post("/api/export-html")
def export_html(req: ExportRequest) -> Response:
    fig = _export_figure(req)
    html = fig.to_html(
        include_plotlyjs="cdn",
        full_html=True,
        config={"responsive": True, "displaylogo": False, "scrollZoom": True},
    )
    return Response(content=html, media_type="text/html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


def main() -> None:
    import socket

    import uvicorn

    host = "127.0.0.1"
    preferred = int(os.environ.get("CT_OVERLAY_PORT", "8765"))

    def _port_free(port: int) -> bool:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind((host, port))
            return True
        except OSError:
            return False
        finally:
            probe.close()

    port = preferred
    if not _port_free(preferred):
        chosen = None
        for candidate in range(preferred + 1, preferred + 16):
            if _port_free(candidate):
                chosen = candidate
                break
        if chosen is None:
            print(f"Port {preferred} is already in use and no free port was found nearby.")
            print("Close the other CTDF / Job Overlay window, then try again.")
            sys.exit(1)
        print(f"Port {preferred} is already in use (another CTDF window is probably still open).")
        print(f"Starting on http://{host}:{chosen} instead.")
        port = chosen

    url = f"http://{host}:{port}"

    def _open() -> None:
        webbrowser.open(url)

    threading.Timer(1.2, _open).start()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
