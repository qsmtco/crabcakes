# Features Guide

## Multi-Agent Collaboration

Crabcakes supports multiple agents working together in a shared project chat.

### Project Tabs

When you open a project, a shared chat tab appears where all project members can see each other's responses. Messages sent in the project tab are broadcast to all members.

### Team Management

Click **+** / **−** on agent rows in the left panel to add or remove agents from the active project. Team membership is saved in `.crabcakes/team.json`.

### Agent Commands

Use slash commands to coordinate agents:
- `/ask @Agent "question"` — consult an agent
- `/delegate @Agent "task"` — assign work
- `/tell @Agent "info"` — share info (no response expected)
- `/stop @Agent` — remove an agent from collaboration

### Solo DM

Use `/solo @Agent` to switch a project tab to direct-message mode with a single agent. Use `/solo all` to return to broadcast mode.

## Code Review

Crabcakes has a built-in code review system. Enable review mode from the project settings bar. In review mode, agents that write code (like Coder) will have their changes reviewed before they're applied.

## Self-Improvement

Each agent can learn from its mistakes and adapt to your project:

- **Bug Journal** — Agents log bugs they encounter and their fixes, learning to avoid repeating the same patterns
- **Project Rules** — Agents can read per-project rules defined in `.crabcakes/{agent}-rules.md`
- **Enforcement** — Agents with write access can enforce code quality rules (syntax checks, tests, linting)
- **Structured Feedback** — Detailed feedback on agent decisions and reasoning
- **Dream Consolidation** — Periodic review of bug journals to identify patterns

These are configured per-agent in the agent's YAML definition under the `self_improvement` field.

## Project Awareness

When a project is active, agents receive context from:
- `.crabcakes/project.md` — project description and metadata
- `.crabcakes/workflow.md` — current workflow phase and status
- `.crabcakes/context.md` — recent activity log
- `.crabcakes/context-snapshot.json` — structured state snapshot

## Improve Prompt (💡)

The Improve Prompt button rewrites your message for better AI responses. It uses the MiniMax API to expand vague prompts into detailed instructions. The original and improved prompts are both visible before sending.

## Speech-to-Text

Hold Ctrl+Space to record voice input. Release to transcribe. Uses whisper.cpp for local transcription.