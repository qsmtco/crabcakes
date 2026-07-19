# Coder Briefing — Fix 17 Spec Accuracy Issues from Debugger Audit

Debugger audited the refreshed `docs/specs/SPEC-RUNTIME-MODULAR-EXTRACTION-PHASE-1.md` and found 17 line-anchor and prose errors. Your job: fix ALL 17 in the spec file. This is a documentation-only task — no code changes, only `docs/specs/SPEC-RUNTIME-MODULAR-EXTRACTION-PHASE-1.md`.

## The 17 fixes (grouped by area)

### §B.4 call-site refactor examples (4 fixes — all HIGH)

**BUG #1 (§B.4.1):** Change "lines 2719–2726" to "lines 2762–2765" for `_PROVIDER_CALLERS.get(caller_key)`. Actual line is 2762. Verify: `grep -n "_PROVIDER_CALLERS.get(caller_key)" agent/runtime.py`

**BUG #2 (§B.4.2):** Change "lines 2807–2809" to "lines 2815–2820" for `_PROVIDER_STREAMERS.get(caller_key)`. Actual line is 2815. Verify: `grep -n "_PROVIDER_STREAMERS.get(caller_key)" agent/runtime.py`

**BUG #3 (§B.4.4):** Two fixes: (a) Change "line ~3285" to "line 3295" for `_call_for_summary`'s `from agent.runtime import _extract_text_content`. Actual line is 3295. (b) Remove the mention of `_cost_for_model` from §B.4.4 entirely — `_call_for_summary` does NOT use it. Verify: `grep -n "_cost_for_model" agent/runtime.py` shows no usage in `_call_for_summary` (lines 3229-3297).

**BUG #9 (§0 discovery table):** Change "15 module-level LLM functions" to "16 module-level LLM functions". Actual count: `awk 'NR>=195 && NR<=1168 && /^def _/' agent/runtime.py | wc -l` = 16.

### §A Track A (4 fixes — MEDIUM)

**BUG #7 (§A.2.3/§A.2.4):** (a) Change "line 2519" to "line 2521" for `allowed_tools=conv.allowed_tools`. Verify: `grep -n "allowed_tools=conv.allowed_tools" agent/runtime.py` = 2521. (b) Change "line 2541–2549" to "line 2540–2549" for the enforcement status dispatch.

**BUG #8 (§A.1):** Change "_run_loop (lines 2101–2599)" to "_run_loop (lines 2101–2600)". The method body ends at 2600; `_dispatch_approval` starts at 2601.

**BUG #11 (§A.4):** Change "~45 lines" to "~37 lines (enforcement 2525–2551 = 27 lines, stuck 2553–2562 = 10 lines)". The actual block sizes sum to 37, not 45.

**BUG #12 (§A.1):** Change "lines 2455–2583" to "lines 2455–2581" for the tool-execution block. The block ends at 2581 (cost-limit check); 2582 is blank, 2583 is the next section.

### §0 discovery table (3 fixes — MEDIUM)

**BUG #5 (§0):** Change "execute_tool function (line ~1161)" to "line 1155". Verify: `grep -n "def execute_tool" agent/tools.py` = 1155.

**BUG #6 (§0):** Change "AgentConfig (line 74)" to "line 70". Verify: `grep -n "class AgentConfig" agent/config.py` = 70.

**BUG #10 (§0):** Change "3 cost functions" to "2 cost functions (`_model_id`, `_cost_for_model`) and 4 cost constants (`_OPENAI_COST`, `_MINIMAX_COST`, `_ANTHROPIC_COST`, `_PROVIDER_COSTS`)". Verify: `awk 'NR>=162 && NR<=190 && /^def /' agent/runtime.py` = 2 functions.

### §B.3 (3 fixes — MEDIUM/LOW)

**BUG #4 (§B.3.6):** Change "_is_empty_content ... used at lines 2386, 2423" to "lines 2320 and 2442". Verify: `grep -n "_is_empty_content" agent/runtime.py` shows call sites at 2320, 2442.

**BUG #13 (§B.3.5):** Change "SSE helpers at 476–1164" to "476–1163". The `_PROVIDER_STREAMERS` dict ends at 1163, not 1164. Verify: `awk 'NR>=1155 && NR<=1170' agent/runtime.py`.

**BUG #16 (§B.3.6 / §0):** §0 says "tool call extractors (lines 1170–1310)" but §B.3.6 says `_is_empty_content` (1245) and `_format_chunks_for_llm` (1297) stay in runtime.py. Add a note in §0: "note: `_is_empty_content` (line 1245) and `_format_chunks_for_llm` (line 1297) stay in runtime.py; only 3 functions move to extractors."

### §B.5/B.8 (3 fixes — LOW)

**BUG #14 (§B.5):** The re-export list duplicates symbols already in `__all__` (lines 62-74). Add a note: "Note: the following symbols are already in `agent/runtime.py`'s `__all__` (lines 62-74): SSEEvent, _PROVIDER_CALLERS, _PROVIDER_STREAMERS, _extract_tool_calls, _extract_text_content, _extract_usage, _cost_for_model, _is_retryable_ssl_error, _stream_with_ssl_retry, _friendly_error_message. These only need to be re-imported as aliases from the new modules; the `__all__` entries do not need to change."

**BUG #15 (§B.5):** Add a note that `_call_openai = OpenAIProvider("openai").call` produces a bound method, not a free function. No tests use `inspect.signature()` on these, so it's compatible, but the implementer should be aware.

**BUG #17 (§B.8):** The "~970 lines freed" breakdown double-counts overlapping ranges. Fix: either de-overlap the ranges or state "approximately 970 lines from the non-overlapping range 162-1310 minus the keepers (`_is_empty_content`, `_format_chunks_for_llm`)".

## Verification after fixes

For EVERY fixed line number, run the grep command listed in the fix and paste the output proving the new number is correct. The spec must be 100% accurate against the current source.

## Do NOT change
- The extraction design or architecture
- The code samples' logic (only the line-number citations and prose around them)
- Any section that Debugger verified as CLEAN (the full list of verified-clean elements is in the audit report)
