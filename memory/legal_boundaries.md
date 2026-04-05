---
name: Claude Code subscription legal boundaries
description: What's allowed and not allowed when using Claude Code subscription programmatically
type: reference
---

Using `claude -p` in automated loops for personal use is explicitly supported by Anthropic. The `--bare` flag is "recommended for scripted and SDK calls."

What's NOT allowed: extracting OAuth tokens, routing third-party tool traffic through subscription endpoints, offering subscription access as a service. This is what got opencode banned (Jan-Feb 2026).

Key constraint: Pro/Max limits assume "ordinary, individual usage." A runaway agent could get throttled.

**Source:** code.claude.com/docs/en/legal-and-compliance, code.claude.com/docs/en/headless

**How to apply:** Always invoke via the `claude` binary, never extract tokens. Include rate limiting (100ms minimum). Design should not look like a competing product — it's a personal automation tool.
