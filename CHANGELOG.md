# Changelog

## 1.0.1 — 2026-09-02

- Job folder path wraps in a taller box; Browse sits under the path
- If port 8765 is already taken, start on the next free port instead of crashing
- `run.bat` no longer falls through to a second Python that is missing packages
- Clearer timezone label: Intelli-Log / RedHawk local clocks vs DAQ UTC

## 1.0.0 — 2026-09-02

First numbered CTDF release after the move to `Documents/Repo/CTDF`.

- Coil-Tubing Data Fusion (CTDF) branding
- Overlay DAQ, RedHawk, and optional Intelli-Log on stacked time-linked plots
- Comment markers with width control and muted theme-aware lines
- Folder browse, auto-scan, load progress overlay
- Dark/light theme, including scrollbars
- Box zoom applies on mouse release; scroll zoom still live
