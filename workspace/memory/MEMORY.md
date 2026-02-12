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
- Active day: Week 8 Day 2 (Fast Track)
- Current task: completed end-to-end architecture walkthrough; ready for focused deepening track

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
- 2026-02-12: Final environment check passed (`nanobot --version`, `nanobot status`, and model section output shows configured/resolved model).

---

*This file is automatically updated by nanobot when important information should be remembered.*
