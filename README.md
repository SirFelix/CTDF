# CTDF — Coil-Tubing Data Fusion

Local viewer for coil-tubing jobs: DAQ `.db` files, optional Intelli-Log `.txt` exports, and RedHawk FieldLog / JobLog CSVs.

Version is in `VERSION` (currently 1.0.0). Each change set increments it and is recorded in `CHANGELOG.md`.

## Run

Double-click `run.bat`, or:

```
cd C:\Users\dvecseri\Documents\Repo\CTDF
py -3 -m pip install -r requirements.txt
py -3 app.py
```

The app opens at http://127.0.0.1:8765

## Use

1. Scan a job `Raw Data` folder (Browse… or paste a path).
2. Leave DAQ, RedHawk, and Intelli-Log files checked. Intelli-Log is optional.
3. Click **Load selected**. Large Intelli-Log files can take a few minutes from OneDrive.
4. Zoom any plot — all four stacked plots stay time-linked and resample from the original points.
5. Hover a vertical line for DAQ ops comments or RedHawk job comments.
6. **Export HTML** writes a smaller interactive file of the current zoom (anyone can open it in a browser). **Export PNG** is a static snapshot.

DAQ `rig_data` overlaps RedHawk FieldLog. Those DAQ rig traces are off by default so RedHawk is the live-stream source of record; turn them on in Series if you want the overlay.

Sentinel values such as `-100000`, empty comment-only rows, and DAQ rig packets whose timestamps do not line up with the logger clock are dropped automatically.
