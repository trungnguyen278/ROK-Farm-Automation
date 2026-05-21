---
name: feedback-no-inline-scripts
description: Never run long inline Python scripts via -c flag — write to a file and run that instead
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 186e4197-0f45-4eac-93c0-d4ac98f537bc
---

Do NOT write long Python scripts inline via `python -c @'...'@`. They hang without output, making debugging impossible.

**Why:** A long inline script ran for 30 minutes with no output because PowerShell buffered stdout. User had to kill it manually.

**How to apply:** When test code is more than ~10 lines, write it to a `tools/` file and run that file instead. This gives real-time stdout and the user can see what's happening.
