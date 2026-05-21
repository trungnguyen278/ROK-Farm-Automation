---
name: feedback-venv
description: Always use .venv for pip install and python commands — never install globally
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 719a33b1-12ad-4012-82ee-e15b14010f7f
---

Always activate or reference the `.venv` virtual environment when running pip install or python commands.

**Why:** User requires all Python work go through the project venv, not global Python.

**How to apply:** Use `.venv\Scripts\pip` and `.venv\Scripts\python` (or activate venv first) for every Python/pip command in this project.
