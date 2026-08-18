#!/bin/sh
# One-shot health snapshot of the overnight run, safe to call repeatedly.
S="/d/ROK Farm Automation/logs/overnight"
F="$S/farm_run.log"
W="$S/watchdog.log"

echo "=== $(date '+%H:%M:%S') ==="
if tasklist //FI "IMAGENAME eq MASS.exe" //NH 2>/dev/null | grep -qi mass; then
  echo "game: UP"
else
  echo "game: DOWN"
fi
if tasklist //FI "IMAGENAME eq python.exe" //NH 2>/dev/null | grep -qi python; then
  echo "python procs: $(tasklist //FI "IMAGENAME eq python.exe" //NH 2>/dev/null | grep -ci python)"
fi

echo "mines DONE   : $(grep -cE 'Mine [0-9]+ DONE' "$F" 2>/dev/null)"
echo "mines FAILED : $(grep -cE 'Mine [0-9]+ FAILED' "$F" 2>/dev/null)"
echo "march sent   : $(grep -cE 'March sent' "$F" 2>/dev/null)"
echo "empty scans  : $(grep -cE 'no icons' "$F" 2>/dev/null)"
echo "fog bails    : $(grep -ciE 'FOG \(out of kingdom\)|fog: (open water|gray cloud)' "$F" 2>/dev/null)"
echo "scan giveups : $(grep -cE 'consecutive empty scans' "$F" 2>/dev/null)"
echo "restarts     : $(grep -cE 'Restarting the game' "$F" 2>/dev/null)"
echo "last queue   : $(grep -oE 'Queue: [0-9]+/[0-9]+' "$F" 2>/dev/null | tail -1)"
echo "--- watchdog (last 6) ---"
tail -6 "$W" 2>/dev/null
