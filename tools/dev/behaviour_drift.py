"""Does our behaviour look the same every single day?

Randomness with FIXED parameters still produces a fixed distribution. Over
thousands of samples that is more identifiable than a constant, not less --
the parameters can be estimated precisely. A real player's wander.
"""
import re, glob, datetime, collections
import numpy as np

pat = re.compile(r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d),(\d\d\d).*click target=")
by_day = collections.defaultdict(list)
for f in sorted(glob.glob("logs/gem_farm_test_*.log")):
    prev = None
    try:
        fh = open(f, encoding="utf-8", errors="replace")
    except OSError:
        continue
    with fh:
        for line in fh:
            m = pat.match(line)
            if not m:
                continue
            t = datetime.datetime.strptime(m.group(1) + " " + m.group(2),
                                           "%Y-%m-%d %H:%M:%S").timestamp() + int(m.group(3))/1000
            if prev is not None and 0 < t - prev < 120:
                by_day[m.group(1)].append(t - prev)
            prev = t

print("%-12s %7s %8s %8s %8s %8s" % ("day", "n", "median", "mean", "p25", "p75"))
meds = []
for d in sorted(by_day):
    g = np.array(by_day[d])
    if len(g) < 100:
        continue
    meds.append(np.median(g))
    print("%-12s %7d %8.2f %8.2f %8.2f %8.2f"
          % (d, len(g), np.median(g), g.mean(), np.percentile(g,25), np.percentile(g,75)))
m = np.array(meds)
print("")
print("median click gap across %d days: %.2f to %.2f s" % (len(m), m.min(), m.max()))
print("  spread of the daily medians: sd %.3f s, CV %.3f" % (m.std(), m.std()/m.mean()))
print("  (a person's daily pace wanders; a fixed generator's does not)")
