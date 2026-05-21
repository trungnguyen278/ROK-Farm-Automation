---
name: feedback-no-guess-positions
description: Never estimate UI button positions from screenshots — ask user to capture and provide exact coordinates
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 186e4197-0f45-4eac-93c0-d4ac98f537bc
---

Do NOT estimate or guess UI element positions from screenshot analysis. Positions estimated from screenshots are unreliable and cause wrong click targets.

**Why:** Mail tab positions were guessed from a screenshot and turned out wrong. The game UI has precise pixel positions that vary with window size and resolution.

**How to apply:** When implementing any action that clicks a game UI element (button, tab, icon):
1. Check if a template image exists in `templates/`
2. If not, ASK the user to capture a screenshot of that specific element
3. Use template matching or user-provided coordinates — never estimate from visual inspection of screenshots
