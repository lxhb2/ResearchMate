---
name: claude-api
description: "Claude API / Anthropic SDK的参考文献——模型编号，定价，参数，流线，工具使用，MCP,代理，缓存，符号计数，模型迁移。"
metadata:
  version: ""
  github_source: "https://github.com/anthropics/skills"
  category: research_closed_loop
  trigger_keyword:
    - claude-api
    - claude api
    - reference
    - claude
    - api
    - anthropic
    - sdk
    - model
  enabled: "true"
---
## Trigger Keywords
claude-api, claude api, reference, claude, api, anthropic, sdk, model

## System Prompt
**Prefix match.** Any byte change anywhere in the prefix invalidates everything after it. Render order is `tools` → `system` → `messages`. Keep stable content first (frozen system prompt, deterministic tool list), put volatile content (timestamps, per-request IDs, varying questions) after the last `cache_control` breakpoint.

**Mid-conversation operator instructions** (Claude Opus 5, Claude Opus 4.8, Claude Fable 5, Claude Mythos 5; not Claude Sonnet 5; no beta header): append `{"role": "system", ...}` to `messages[]` instead of editing top-level `system`. Preserves the cached history prefix and is the prompt-injection-safe operator channel. See `shared/prompt-caching.md` § Mid-conversation system messages.

**Top-level auto-caching** (`cache_control: {type: "ephemeral"}` on `messages.create()`) is the simplest option when you don't need fine-grained placement. Max 4 breakpoints per request. Minimum cacheable prefix is ~1024 tokens — shorter prefixes silently won't cache.

**Verify with `usage.cache_read_input_tokens`** — if it's zero across repeated requests, a silent invalidator is at work (`datetime.now()` in system prompt, unsorted JSON, varying tool set).

For placement patterns, architectural guidance, and the silent-invalidator audit checklist: read `shared/prompt-caching.md`. Language-specific syntax: `{lang}/claude-api/README.md` (Prompt Caching section).

---
