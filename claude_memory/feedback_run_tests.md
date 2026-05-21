---
name: feedback-run-tests
description: User prefers Claude to run test commands directly instead of asking user to run them
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 89a66c64-0986-4702-a1fc-50a1c7eb2c75
---

Run test/debug commands directly via terminal instead of telling user to run them manually.

**Why:** User said "những lệnh này bạn nên tự chạy dễ hơn" — it's faster when Claude runs commands that can be executed in the terminal.

**How to apply:** For any Python test, debug script, or build command that doesn't require physical hardware interaction, run it directly using PowerShell/Bash tool. Only ask user to run commands that require physical actions (pressing buttons, swapping cables, etc).
