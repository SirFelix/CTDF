# Changelog

## 1.5.0 — 2026-09-02

- Windows exe has no terminal window and exits when the browser tab is closed
- Rebuild with `build_exe.bat` (errors go to `CTDF.log` next to the exe)

## 1.4.0 — 2026-09-02

- Bundle Plotly so charts work without a CDN
- Packaged Windows exe (`build_exe.bat`) starts with an empty job folder
- Document optional Authenticode signing for the exe

## 1.3.1 — 2026-09-02

- Convert RedHawk pump rate from gpm to bpm (divide by 42)

## 1.3.0 — 2026-09-02

- Separate DAQ and RedHawk comment markers so each source can be shown or hidden

## 1.2.3 — 2026-09-02

- DAQ Tractor Speed is off by default

## 1.2.2 — 2026-09-02

- Keep Intelli-Log tension when it goes into compression below -5,000 lbf

## 1.2.1 — 2026-09-02

- Job timezone dropdown always includes US and Middle East options

## 1.2.0 — 2026-09-02

- Detect job timezone from DAQ `ops_log` (UTC `timestamp_s` vs local `datetime`)
- Hide timezone controls until **Adjust timezone manually** is checked
- Add `tzdata` so Windows can resolve IANA zones

## 1.1.0 — 2026-09-02

- Commentable `TEST_JOB_FOLDER` default for the Boling Raw Data path
- Job timezone dropdown (US and Middle East) instead of a Chicago-only checkbox
- Per-source timezone and extra-hour shift when a PC clock was set wrong
- DAQ stays UTC unless you add extra hours

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
