---
name: feedback-unicode-windows
description: Never use Unicode arrows/em-dashes in Python print() on Windows cp1252 terminal
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f908e428-fbab-4cac-a403-837dc972657a
---

Never use Unicode special characters (arrows, em-dashes, etc.) in Python print() statements.

**Why:** Windows terminal uses cp1252 encoding. Characters like `→` (U+2192), `—` (U+2014) crash with `UnicodeEncodeError`. This has happened multiple times in test scripts.

**How to apply:** Use ASCII alternatives: `->` instead of `→`, `--` instead of `—`. Only use ANSI color codes (which work fine). Check all new print/log strings for non-ASCII before running.
