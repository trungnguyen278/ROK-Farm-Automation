---
name: feedback-vibe-token-save
description: "Docs must be optimized for vibe coding - concise, self-contained specs to minimize token usage when coding"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 0fe1fe23-61c3-4de1-a41a-6fa45a9a1dec
---

Structure all docs for minimal token consumption during vibe coding sessions.

**Why:** User wants to feed docs to LLM for code generation. Verbose docs waste tokens and dilute signal.

**How to apply:**
- Each doc is self-contained — no need to cross-read other files to understand it
- Use tables/specs over prose. Code examples over descriptions
- Include exact function signatures, data types, constants
- Put "AI Implementation Notes" section at top of each doc with tl;dr
- Keep docs under ~200 lines each — split if larger
- Use `## Quick Spec` sections for copy-paste into prompts
