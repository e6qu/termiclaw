---
name: User preferences and feedback
description: How the user wants to work — lean, no over-engineering, Terminus-faithful, vanilla Python
type: feedback
---

When in doubt, mirror what Terminus does. The user consistently chose "what does Terminus do here?" for every open question.

**Why:** The user values simplicity and proven patterns over novel architecture. The PLAN.md was too heavy (7 bounded contexts, 50 files) — the user preferred Terminus's ~5 file approach.

**How to apply:** Default to Terminus's choices. Keep architecture lean (~8 files). No DDD ceremony. No external dependencies. When presenting options, always include "what Terminus does" as a choice.
