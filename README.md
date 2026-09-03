# CTDF — Coil-Tubing Data Fusion

Local viewer for coil-tubing jobs: DAQ `.db` files, optional Intelli-Log `.txt` exports, and RedHawk FieldLog / JobLog CSVs.

Version is in `VERSION`. Each change set increments it and is recorded in `CHANGELOG.md`.

## Run from source

Double-click `run.bat`, or:

```
cd C:\Users\dvecseri\Documents\Repo\CTDF
py -3 -m pip install -r requirements.txt
py -3 app.py
```

The app opens at http://127.0.0.1:8765

When you run from source, the job folder defaults to the Boling Test Raw Data path on this PC. Set `CTDF_TEST_JOB_FOLDER` to another folder, or to empty, to override that. The packaged exe always starts with a blank folder — use Browse.

## Windows exe

Close any running CTDF window, then double-click `build_exe.bat` (or run it from a command prompt in this folder). Wait until it prints `Built dist\CTDF\CTDF.exe`. That rebuilds the exe with your latest code, including color changes.

Zip the whole `dist\CTDF` folder to share. Job data is not inside the exe; each person uses Browse to pick their own Raw Data folder.

The exe opens the browser with no terminal. Closing that tab (or the browser) stops CTDF after a couple of seconds. A refresh does not quit. If something fails, check `CTDF.log` next to `CTDF.exe`.

Needs a 16 GB machine if they load large Intelli-Log files. 8 GB is often tight.

The exe is **unsigned** unless you sign it. Windows SmartScreen will warn until you do. To sign after a build, set `CTDF_SIGN_CERT` to your `.pfx` (and `CTDF_SIGN_PASSWORD` if the cert is locked) and run `build_exe.bat` again, or:

```
signtool sign /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com /f your.pfx dist\CTDF\CTDF.exe
```

You need a company Authenticode certificate from IT / a CA. This repo cannot sign the file without that cert.

## Use

1. Scan a job `Raw Data` folder (Browse… or paste a path).
2. Leave DAQ, RedHawk, and Intelli-Log files checked. Intelli-Log is optional.
3. Click **Load selected**. Large Intelli-Log files can take a few minutes from OneDrive.
4. Zoom any plot — all four stacked plots stay time-linked and resample from the original points.
5. Hover a vertical line for DAQ or RedHawk comments. Each source can be hidden in Display.
6. **Export HTML** writes an interactive file of the current zoom that fills the browser. Choose HTML points per trace (or all points in view) before exporting. **Export PNG** is a static snapshot.

DAQ `rig_data` overlaps RedHawk FieldLog. Those DAQ rig traces are off by default so RedHawk is the live-stream source of record; turn them on in Series if you want the overlay.

Sentinel values such as `-100000`, empty comment-only rows, and DAQ rig packets whose timestamps do not line up with the logger clock are dropped automatically.
