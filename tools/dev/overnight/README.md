# Overnight harness

Runs the farm unattended and supervises it. Logs go to `logs/overnight/`.

## Start

```powershell
$py   = "d:\ROK Farm Automation\.venv\Scripts\python.exe"
$here = "d:\ROK Farm Automation\tools\dev\overnight"
Remove-Item "d:\ROK Farm Automation\logs\overnight\*.log" -ErrorAction SilentlyContinue

$farm = Start-Process $py -ArgumentList "`"$here\farm_full.py`"" `
        -WorkingDirectory "d:\ROK Farm Automation" -PassThru -WindowStyle Hidden
Start-Sleep 3
Start-Process $py -ArgumentList "`"$here\watchdog2.py`"", "$($farm.Id)", "`"2026-08-18 19:00`"" `
        -WorkingDirectory "d:\ROK Farm Automation" -WindowStyle Hidden
```

The last argument is the stop time (`YYYY-MM-DD HH:MM`); omit it to run until
stopped.

## Watch

```bash
sh "tools/dev/overnight/status.sh"          # one-shot snapshot
tail -f "logs/overnight/watchdog.log"       # 3-min summaries + alerts
```

## What the watchdog does

It **restarts** the farm rather than only killing it, capped at 6 attempts --
a supervisor whose only action is `kill` turns any false positive into a lost
night (that is exactly how six hours were lost once). Outright stopping is
reserved for the deadline and for a restart loop.

Recoverable, triggers a restart:
- no log growth for 1500s. NOTE: the flow has a *designed* 15-minute silence
  ("waiting for troops to return"), plus a reconnect delay that can reach ~17
  minutes, so this threshold must stay well clear of both.
- 14 consecutive mine failures (the farm itself recovers at 3 and relaunches
  the client at 8, so this only fires when its own healing is not working)
- 75 minutes with no mine started or finished -- deliberately NOT conditioned
  on scans increasing, because a paralysed bot stops producing them
- a serial exception with no progress for 10 minutes

Every 3 minutes it logs deltas for empty scans, fog bails, classifier/colour
rejects, gather misses, occupied skips and the per-mine retry counter. Every 5
minutes it screenshots the client and asks the project's vision oracle what is
on screen, which catches states the log cannot show -- a reconnect overlay, for
instance.
