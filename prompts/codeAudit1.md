You are performing a comprehensive code audit of the quantum-memory-v2 project at /home/q/projects/quantum-memory-V2.

IMPORTANT: We are not in a race. Slow but 100% correct is better than fast but wrong. Be thorough, be methodical, be exhaustive.

## YOUR RULES

1. NEVER trust documentation. Verify EVERY claim against actual source code.
2. NEVER assume something works because it looks like it should. RUN IT.
3. NEVER leave a fix half-done. If you find a bug, fix it before moving on.
4. NEVER guess at APIs. Look up actual docs and code examples in real-time.
5. Use checkpoint debugging: one narrow goal → write 5-12 lines → verify → fix if broken → green → next.
6. Never write large untested blocks. Always verify after every change.
7. If the code and docs disagree, the code is always right. Update the docs to match.

## AUDIT CHECKLIST

For each item below, you MUST:
- Read the actual source code
- Verify the claim is TRUE (not assumed true)
- If broken: fix it immediately, then mark FIXED
- If working: mark VERIFIED
- If uncertain: write a test to verify, then mark PASS/FAIL

### PHASE 1: VERIFY BUILD & TESTS

1. Run `npm run typecheck` — must pass with zero errors
2. Run `npm run build` — must pass
3. Run `npm test` — all tests must pass (167/167)
4. If any fail: fix them before proceeding

### PHASE 2: VERIFY PLUGIN REGISTRATION

5. Read src/plugin/index.ts — verify quantumMemoryPlugin() calls registerQmTools() with a real QuantumContextEngine instance
6. Read src/plugin/tools.ts — verify it imports and wraps all 5 tool factories (qm-search, qm-entities, qm-relations, qm-recall, qm-projects)
7. Verify each tool's execute() function is properly wired to the actual store methods
8. Run a live test: create an engine, call each tool factory, verify the returned tool has a real execute function

### PHASE 3: VERIFY DATABASE SCHEMA

9. Read src/db/Database.ts inline schema — list every table and column
10. Read src/db/migrations/index.ts — list every table and column
11. VERIFY both files are IDENTICAL in every way (every column, type, constraint, index, trigger)
12. Read src/db/migrations/index.ts — verify it imports and calls runQuantumMigrations
13. Check that FTS5 virtual table and triggers are in BOTH files (Database.ts inline AND migration)
14. Check that importance_score column is in messages table in BOTH files
15. Verify all column names match what the store files actually use in their SQL queries

### PHASE 4: VERIFY STORE SQL QUERIES

For each of these stores, read the file and verify ALL SQL queries use correct column names matching the schema:

16. src/engine/MessageStore.ts — verify all SELECT/INSERT/UPDATE use: id, session_id, role, content, token_count, is_compacted, importance_score, created_at
17. src/dag/SummaryStore.ts — verify all queries use: id, session_id, parent_summary_id, level, content, token_count, source_message_ids, created_at
18. src/entities/EntityStore.ts — verify queries use: id, session_id, name, type, mention_count, first_seen, last_seen, metadata
19. src/entities/RelationStore.ts — verify queries use: id, session_id, from_entity, to_entity, relation_type, confidence, source_message_id, created_at

### PHASE 5: VERIFY ENGINE WIRING

20. Read src/engine/QuantumEngine.ts — verify beforeTurn() is async and calls LargeFileHandler.processMessage() for each message
21. Verify afterTurn() calls inject() on AutoRecallInjector
22. Verify compact() is wired (called from afterTurn when needsCompaction is true)
23. Verify getContext() calls inject() from AutoRecallInjector

24. Verify QuantumContextEngine constructor creates: MessageStore, SessionManager, EntityStore, RelationStore, SearchEngine, MemoryInjectStore, SmartDropper, LargeFileHandler (with LLM + DB)
25. Verify registerQuantumMemory() is exported and accepts onEngineCreated callback

### PHASE 6: VERIFY FTS5 SEARCH

26. Read src/search/SearchEngine.ts — verify searchAll() uses FTS5 MATCH with bm25() ranking
27. Verify LIKE fallback exists when FTS5 fails
28. Verify FTS5 error is caught and logged

### PHASE 7: VERIFY SMART DROP

29. Read src/drop/SmartDropper.ts — verify scoreMessages() exists and is async
30. Verify it calls LLMCaller.generate() for scoring
31. Verify getMessagesToDrop() accepts Map<string, ImportanceScore>
32. Verify dropMessages() calls scoreMessages() then passes scores to getMessagesToDrop()

### PHASE 8: VERIFY LLM INTEGRATION

33. Read src/utils/LLMCaller.ts — verify chat() uses Promise.race with timeout
34. Verify LLMCaller is passed to: LargeFileHandler, SmartDropper, QuantumEngine (for summarization)
35. Verify summarizeContent() in LargeFileHandler calls LLMCaller.generate()

### PHASE 9: VERIFY TOOLS

For each tool file (src/tools/*.ts):
36. Verify the factory function creates an object with: name, description, inputSchema, execute(input)
37. Verify execute() actually calls the real store methods with the input parameters
38. Verify the tool's sessionIdGetter() is called and used in queries

### PHASE 10: VERIFY README ACCURACY

39. Read the README.md Known Gaps section
40. For each item marked ✅: verify it actually works in the code (not just documented)
41. For each item marked not done: verify it truly is not wired
42. Verify the Feature Table at the top of README matches actual implementation
43. Verify the Architecture diagram matches actual file structure

### PHASE 11: FIX EVERYTHING YOU FIND

44. If any check fails: fix it immediately in the same session
45. After each fix: run `npm run build && npm test` to confirm nothing broke
46. Do NOT move to the next phase until the current phase is 100% green

## OUTPUT FORMAT

For each check, report:
CHECK [NUMBER]: [DESCRIPTION]
STATUS: VERIFIED | FIXED | FAILED
FIX APPLIED: [what you changed, if any]

At the end, produce:
- List of all FIXES applied
- Final test count
- Final typecheck status
- Final build status
- Anything that could NOT be fixed (with reason)

## START NOW

Begin with Phase 1. Work through every phase in order. Do not skip any check. Do not summarize until the end.

