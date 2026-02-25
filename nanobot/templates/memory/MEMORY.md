# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Project Context

(Information about ongoing projects)

## Important Notes

(Things to remember)

## Learning Plan (Saved: 2026-02-09)

User wants a complete beginner-to-full-project study path for this repository.
Follow this 8-week sequence unless user changes priorities:

Week 1: Setup and core runtime flow
- Read README, pyproject, CLI entrypoints
- Run onboarding, status, and first agent chat

Week 2: Config and provider pipeline
- Study config loading and schema
- Trace model/provider selection and LiteLLM calls

Week 3: Tooling system
- Study tool base, registry, filesystem/shell/web tools
- Add one custom tool and register it

Week 4: Context, memory, and sessions
- Study prompt assembly, memory, and session persistence
- Test behavior changes via AGENTS.md / USER.md

Week 5: Skills and subagents
- Study skills loader and spawn/subagent workflow
- Run one background task end-to-end

Week 6: Cron and heartbeat automation
- Study cron types/service and heartbeat service
- Build one recurring and one one-time task

Week 7: Multi-channel architecture
- Study bus and channel manager
- Trace Telegram/Discord/WhatsApp adapter flows

Week 8: Bridge, Docker, and delivery
- Study bridge TypeScript code, Dockerfile, tests
- Perform one full demo flow

Current progress:
- Active day: Week 3 Day 1 (Fast Track)
- Current task: accelerated code-first track (merge 2 learning days per session, quiz-first)

Progress log:
- 2026-02-09: Virtual environment setup completed successfully.
- 2026-02-09: `pip install -e .` validated in venv (`nanobot --version` works).
- 2026-02-09: `nanobot onboard` and `nanobot status` both successful.
- 2026-02-09: User prefers local LLM deployment via Ollama, targeting qwen3-coder-next.
- 2026-02-09: Local provider configured via `providers.vllm.apiBase=http://localhost:11434/v1`.
- 2026-02-09: First successful real agent chat completed with local model (`qwen3-coder-next`).
- 2026-02-09: User synced latest upstream code; confirmed new Email channel integration and provider matching refactor are present locally.
- 2026-02-09: Day3 validation completed; custom `now_time` tool call succeeded in `nanobot agent`.
- 2026-02-10: Day4 proof completed in fresh session (`cli:day4-proof`), preference answer still returned, confirming long-term memory usage.
- 2026-02-10: Progress log date policy aligned to local machine date (UTC+08:00).
- 2026-02-10: Day5 subagent workflow verified in interactive mode with `spawn` and delayed result callback.
- 2026-02-10: Added hourly cron job `hourly-git-pull` (`5c3f08b9`) to pull repository updates.
- 2026-02-10: Day7 gateway/cron behavior understood; runtime cron cache requires gateway restart to reflect add/remove changes.
- 2026-02-10: Entered Week 2 code-first track; focusing on provider matching and model routing internals.
- 2026-02-11: Week2 Day2 quiz accepted: `find_gateway` miss in standard mode, `_resolve_model` applies `litellm_prefix`, and model-specific overrides are injected in `chat()`.
- 2026-02-11: Fixed session-key override path (`process_direct` now sets `InboundMessage.session_key_override`), verified new CLI sessions write separate files (e.g. `heartbeat.jsonl`).
- 2026-02-11: Switched to fast-track learning mode: prioritize architecture spine, practical debugging, and merge multiple day topics per session.
- 2026-02-13: Diagnosed online search behavior: `online_search` still uses DuckDuckGo; observed Google URL came from model fallback (`web_search`/`web_fetch`) after tool/network failure on the other machine.
- 2026-02-13: Completed Day8 session isolation checks with `-s cli:*`; confirmed session history is keyed by `session_key`, while long-term memory remains global across sessions.
- 2026-02-13: Completed Day9 boundary test (`cli:u1` vs `cli:u2`): session-local identity can differ, and answers may still reference shared memory when available.
- 2026-02-13: Progress logging resumed; policy restored to record one entry after each learning checkpoint/quiz acceptance.
- 2026-02-13: Completed Day10 routing check: with identical `session_key`, cross-channel calls (CLI then telegram) still shared history and correctly returned identity `X`.
- 2026-02-13: Day11 history-window experiment completed: `get_history(max_messages=50)` confirmed in code; model self-report on earliest visible turn can be incorrect, so window boundaries should be validated from session file/script instead of natural-language answer.
- 2026-02-13: Day12 context-order quiz accepted: confirmed order is identity -> bootstrap -> memory -> skills in system prompt, then history, then current user message; clarified bootstrap files as user-editable behavioral overlays.
- 2026-02-13: Day13 validation-vs-execution quiz accepted: invalid enum (e.g., `recency=weekly`) is caught by `validate_params` before execution, while URL scheme checks in `web_fetch` happen inside `execute()` and return tool-level error payloads.
- 2026-02-13: Day14 tool-error flow validated end-to-end via direct registry execution: schema enum mismatch returned `Invalid parameters`, while `web_fetch` rejected `javascript:` during execution and returned structured URL-validation error JSON.
- 2026-02-13: Day15 write-path safety checks passed: leading/trailing-space paths and absolute-like relative paths (`Users/...`) were rejected; normal relative write (`notes/safe.txt`) succeeded.
- 2026-02-13: Day16 filesystem safety coverage accepted: `read/edit/list` path failures are not schema errors (path is plain string in schema) but execution-time compliance errors raised by shared path resolver; workspace enforcement switch identified as `tools.restrict_to_workspace`.
- 2026-02-13: Fixed consolidation reliability bug: when memory-consolidation LLM output is empty/invalid JSON, loop now applies fallback parsing/history entry and still trims session to stop repeated consolidation stalls.
- 2026-02-13: Day21 monitoring landed: added `scripts/memory_health_monitor.py` to report memory-file integrity, oversized session counts, JSONL parse health, and consolidation fallback ratio with WARN thresholds.

---

*This file is automatically updated by nanobot when important information should be remembered.*
