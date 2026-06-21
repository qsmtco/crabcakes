# Manual Test Plan — ⚙ Settings Dialogue

**Target:** Crabcakes Settings dialog (spec `docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md`)
**Prereq:** Working crabcakes install. A terminal with `cat`, `ls -l`, and `stat` available. At least one real LLM provider API key on hand (any of: MiniMax, ZAI, OpenRouter, or another openai-compatible provider). An obviously bad key (a string starting with `sk-` followed by garbage) for failure tests.
**Reset state:** Before starting, run `rm -f ~/.config/crabcakes/providers.yaml` so you start from the empty case. The agent.json fallback path is tested in step 17 — keep that file around.

Each step lists **what to do**, **what to look for**, and **what would be a bug**. Steps build on each other — don't skip ahead.

---

## 1. Cold start with no providers file

**Do:** Launch crabcakes. Look at the top toolbar.

**Expect:**
- A `⚙ Settings` button is visible on the left cluster, immediately to the right of the `Stream: ON/OFF` toggle.
- A **red dot** is visible at the top-right corner of the ⚙ button (because no provider has been verified yet).
- The right side of the toolbar still shows `● Not connected` status and the `Connect` button as before.

**Bug if:** The red dot is missing with no providers file present.

---

## 2. Open the Settings dialog from a clean slate

**Do:** Click the `⚙ Settings` button.

**Expect:**
- A new window titled **Settings** appears, modal (you cannot click the main window underneath), about 560×480px.
- A `Close` button on the right of the header bar.
- The body shows the empty-state message: **"No providers configured. Add your first provider below."** centered with reduced opacity.
- A **`+ Add Provider`** button at the bottom.

**Bug if:** Dialog doesn't open, opens but isn't modal, or doesn't show the empty state.

---

## 3. Add a new provider (happy path, no API key yet)

**Do:** Click `+ Add Provider`. An empty card appears with four fields (Name, Base URL, Default Model, API Key), a `Untested` status line, and three buttons: `Test Connection`, `Save`, `Remove`.

**Do:** Fill in:
- Name: `test1`
- Base URL: `https://api.example.com/v1`
- Default Model: `some-model`
- Leave API Key blank.

**Do:** Click `Save`.

**Expect:**
- The card stays visible (no error popup).
- The card's status line still reads `Untested` (not verified — Test Connection hasn't been run).
- The empty-state message is gone.
- The file `~/.config/crabcakes/providers.yaml` now exists.

**Verify on disk:** Run `ls -l ~/.config/crabcakes/providers.yaml` and `stat -c '%a' ~/.config/crabcakes/providers.yaml`. **Expect** the file mode to be `600` (owner read/write only). Also `stat -c '%a' ~/.config/crabcakes/` should be `700`.

**Bug if:** Save doesn't create the file, the file is world-readable, the parent dir isn't 700, or the dialog shows an error.

---

## 4. Test Connection — invalid URL/key combo (failure path)

**Do:** On the same card, click `Test Connection`. (It will try `https://api.example.com/v1` with no auth — guaranteed to fail.)

**Expect (within ~8 seconds):**
- The status line changes to `Testing...` while the request is in flight.
- Then it changes to `❌ <some error message>` (the actual provider's error or the network error). The `settings-status-fail` CSS class is applied (text turns red).
- The red dot on the toolbar ⚙ button is **still visible** (no provider is verified yet).
- The app does **not freeze** during the test (you can still move the window, scroll).

**Verify:** The on-disk file `providers.yaml` now has `last_error: "<message>"` and `last_verified_at: null` for the `test1` entry. Run: `cat ~/.config/crabcakes/providers.yaml`.

**Bug if:** The app freezes for 8+ seconds, the test silently succeeds, the red dot disappears, or no error is shown.

---

## 5. Test Connection — valid key, real provider (success path)

**Do:** Pick a real provider you have a working key for. Edit the same card:
- Name: leave as `test1` (or change to the provider's canonical name, e.g. `openrouter`)
- Base URL: the real one, e.g. `https://openrouter.ai/api/v1`
- Default Model: a model that exists on that provider, e.g. `deepseek/deepseek-v4-pro` (or `MiniMax-M2.7` for MiniMax)
- API Key: your real key

**Do:** Click `Test Connection`.

**Expect (within ~8 seconds):**
- Status line shows `Testing...` briefly, then `✅ <N>ms` (the latency).
- The `settings-status-ok` CSS class is applied (text turns green).
- The **red dot on the toolbar ⚙ button disappears** (because at least one provider is now verified).
- The on-disk yaml now has `last_verified_at: "<ISO timestamp>"` and `last_error: null` for this provider.

**Bug if:** Test fails with a valid key, the red dot stays, the latency is missing, or the timestamp isn't ISO 8601 UTC.

---

## 6. API key reveal/hide toggle

**Do:** Click the `👁` button next to the API key field.

**Expect:** The API key becomes visible (plaintext). Click again — it becomes hidden (password dots).

**Bug if:** Toggle does nothing, or the key is visible by default.

---

## 7. Edit an existing provider

**Do:** On the verified `test1` card, change the Default Model field to a different value. Click `Save`.

**Expect:**
- Card stays visible, status flips back to `Untested` (because the model that was verified has now changed — re-test is required).
- Wait — actually, **observe what the code does** and report: does saving a card with a changed `default_model` keep the previous `last_verified_at`, or clear it? The spec is silent on this. If it keeps the old timestamp, the red dot stays off; if it clears it, the red dot comes back. Either is acceptable as long as it is consistent. **What must not happen:** a crash or the timestamp desync from the actual config.

**Bug if:** Save errors, the card disappears, or the yaml file is corrupted.

---

## 8. Add a second provider

**Do:** Click `+ Add Provider` again. Fill in a different provider (any name, valid or invalid doesn't matter for this step). Click `Save`.

**Expect:**
- A second card appears below the first.
- Both cards are independent (editing one doesn't affect the other).
- The yaml file now contains two entries.

**Bug if:** The first card disappears, the cards merge, or saving the second overwrites the first.

---

## 9. Remove an unsaved (new) card

**Do:** Click `+ Add Provider` to create a third empty card. **Do not fill it in or save it.** Click `Remove` on that card.

**Expect:** The card disappears immediately, no confirmation dialog.

**Bug if:** A confirmation dialog appears, or the app tries to remove a non-existent yaml entry.

---

## 10. Remove a saved provider (confirmation path)

**Do:** Click `Remove` on the second saved card (the one from step 8).

**Expect:** A confirmation dialog appears: **"Remove provider '<name>'? This cannot be undone."** with YES / NO buttons. Click **NO**.

**Expect:** Dialog closes, the card remains, nothing on disk changed. Run `cat ~/.config/crabcakes/providers.yaml` to confirm.

**Do:** Click `Remove` again on the same card. This time click **YES**.

**Expect:**
- The card disappears from the dialog.
- The yaml no longer contains that entry.
- The remaining card (the verified one from step 5) is untouched and still shows ✅.
- The red dot on the toolbar is **still hidden** (at least one verified provider remains).

**Bug if:** Wrong card is removed, or removing a non-last verified provider changes the red dot.

---

## 11. Remove the LAST verified provider

**Do:** Click `Remove` on the verified `test1` card. Confirm YES.

**Expect:**
- The dialog is now empty (shows the empty-state greeting again).
- The **red dot reappears on the toolbar ⚙ button** (no verified providers remain).
- `providers.yaml` no longer exists, or is empty.

**Bug if:** The red dot stays hidden, the file still contains a `last_verified_at` entry, or the app crashes.

---

## 12. Close and reopen the dialog — state persistence

**Do:** Click `+ Add Provider`, fill in name=`persist-test`, base_url=`https://x.com`, default_model=`m`, api_key=`sk-test`. Click `Save`. Then click `Close` on the Settings window.

**Do:** Click `⚙ Settings` again to reopen.

**Expect:**
- The dialog reopens, modal, same dimensions.
- The `persist-test` card is still there, fully populated.
- Any previous verification status (verified or failed) is preserved.

**Bug if:** The card is gone, the fields are blank, the dialog becomes unresponsive and blocks the main app, or a Gtk-WARNING appears in the terminal.

---

## 13. Close the dialog mid-edit (unsaved changes)

**Do:** Click `+ Add Provider`. Type something into the Name field. **Do not click Save.** Click `Close`.

**Do:** Reopen the dialog.

**Expect:** The unsaved card is **gone** (it was never saved). Previously saved cards are intact.

**Bug if:** Unsaved data persists across open/close, OR a saved card is lost.

---

## 14. Agent Builder dropdown reflects Settings changes (live sync)

**Do:** With Settings closed, click `+ Agent` in the left panel to open the agent edit dialog.

**Do:** Look at the **Provider dropdown** in that dialog.

**Expect:**
- The dropdown lists exactly the providers you have in `providers.yaml` (not the old hardcoded list of MiniMax/ZAI/OpenRouter). For example, after steps 12 and 8, you should see only `persist-test`.
- If no providers are configured, the dropdown shows `(no providers — open Settings)` as a single entry.

**Do:** Close the agent dialog, go back to Settings, add a new provider, save. Reopen the agent dialog.

**Expect:** The new provider appears in the dropdown without restarting the app.

**Bug if:** The dropdown still shows hardcoded providers, or the new provider doesn't appear until restart.

---

## 15. Agent edit dialog has NO API key field

**Do:** In the agent edit dialog, scan every field.

**Expect:**
- There is **no** API Key entry on the agent edit form.
- There is no `provider_keys` field.
- The Save button enables when name + prompts + tools + provider+model are all set (it should NOT require an API key).

**Bug if:** An API key field exists, or the Save button stays disabled because no key is entered.

---

## 16. Atomic write safety

**Do:** Open Settings. Make an edit, click Save. **Immediately** in another terminal, run:
```
ls -la ~/.config/crabcakes/providers.yaml*
```

**Expect:** At any given instant, you see either `providers.yaml` (complete) or `providers.yaml.tmp` (in-progress) — **never both** as a half-written file. A second later, only `providers.yaml` remains.

**Bug if:** You observe both files for more than a brief moment, or the final file is empty/partial. (This is a quick check — modern filesystems make race observation unlikely; the real test is that the code uses `os.rename` rather than `open(..., 'w')` directly. You can verify by `grep -n "rename\|tmp_path" utils/providers_store.py`.)

---

## 17. agent.json fallback (legacy path)

**Do:** Make sure `~/.config/crabcakes/agent.json` exists and contains a `providers` section with at least one provider entry (any keys — they don't need to be real). Make sure `providers.yaml` does **not** exist.

**Do:** Launch crabcakes.

**Expect:**
- The app starts without crashing.
- The Settings dialog, if opened, will initially show an empty state (because `agent.json` providers are read by `load_agent_config()` for runtime key resolution, not by `load_providers()` for the Settings dialog).
- The terminal/log shows a **one-time warning**: `agent.json: providers section is deprecated and will be ignored once providers.yaml is created...`
- The Connect button is enabled and the app attempts to use the agent.json keys at send-time (test by sending a message to a special agent — it should authenticate using the agent.json key).

**Do:** Now open Settings, add any provider, save. Restart the app.

**Expect:** The agent.json warning does **not** appear again (it was one-time per process). The new providers.yaml is used; agent.json's providers section is ignored.

**Bug if:** The app crashes on startup with a legacy agent.json, the warning repeats every call, or adding a yaml provider doesn't take precedence.

---

## 18. Malformed providers.yaml recovery

**Do:** `cp ~/.config/crabcakes/providers.yaml ~/.config/crabcakes/providers.yaml.bak`, then open the file and replace the contents with garbage like `this is: not: valid: yaml: [[[`. Save.

**Do:** Launch crabcakes, open Settings.

**Expect:** App doesn't crash. The dialog shows the empty state. The log shows a `providers_store: failed to parse: ...` warning.

**Do:** Restore the backup: `mv ~/.config/crabcakes/providers.yaml.bak ~/.config/crabcakes/providers.yaml`.

**Bug if:** The app crashes on launch with a corrupt yaml, or the dialog hangs.

---

## 19. Read-only providers.yaml

**Do:** `chmod 444 ~/.config/crabcakes/providers.yaml` (read-only).

**Do:** Open Settings, edit a card, click Save.

**Expect:**
- The Save click raises an `OSError` from `save_providers` (caught by `_on_save_clicked` and shown in the card's status line as an error).
- The dialog does **not** crash. Other cards remain visible.
- No data is silently lost from the in-memory list.

**Do:** Restore write permission: `chmod 600 ~/.config/crabcakes/providers.yaml`.

**Bug if:** The app crashes, the entire dialog becomes unresponsive, or the error is swallowed silently.

---

## 20. Test Connection timeout

**Do:** On a provider card, set the Base URL to a non-routable address that will hang, e.g. `https://10.255.255.1/v1` (RFC 5737-style blackhole). Set a real-looking key. Click `Test Connection`.

**Expect:**
- Within ~8 seconds, the status changes to `❌ timeout` (or a similar error indicating the request was aborted).
- The card's `last_error` is set.
- The red dot stays visible.
- The app remains responsive throughout.

**Bug if:** The app hangs for 30+ seconds, the GTK main thread is blocked (you cannot move the window), or no error is reported.

---

## 21. Two Test Connections in rapid succession

**Do:** On the same card, click `Test Connection` twice within a second.

**Expect:** Both tests run in their own threads. Each result is delivered as it completes, and the status label updates with the latest result that lands. The final state is consistent with the yaml file (the second test's outcome is the one persisted, since it finishes later — or they may interleave; either is acceptable as long as no exception is raised).

**Bug if:** The dialog crashes, the status flickers between two states indefinitely, or the yaml contains a half-written entry.

---

## 22. First-run empty state messaging (chat area)

**Do:** Delete `providers.yaml` and `agent.json`. Launch crabcakes with no prior config.

**Expect:** Per spec §7 / §10, **a first-run greeting card in the chat area is explicitly OUT OF SCOPE for V1**. Do not expect one. The expected first-run signal is the **red dot on the ⚙ button** plus the **empty state inside the Settings dialog** when opened. Both should be present.

**Bug if:** The red dot is missing, OR a chat-area greeting was promised (it wasn't — don't test for it).

---

## Done

If every step above passes, the Settings dialog implementation is functionally complete against the spec. The remaining spec items (file mode 0o600, modal transient, `app_title` not on providers, no `provider_keys` in agent YAMLs) are best verified by `grep` + reading the code rather than manual UI clicks:

```bash
# 0o600 enforcement
grep -n "chmod.*0o600" utils/providers_store.py

# No app_title on ProviderConfig
grep -n "app_title" models/providers.py   # should return nothing

# No provider_keys in get_values
grep -n "provider_keys" ui/views/agent_builder.py   # only comments should match

# No api_key in agent edit form
grep -n "_api_key_entry" ui/views/agent_builder.py   # should return nothing
```

Any mismatch between these greps and the spec is a code bug, not a UI bug — file it as a defect.

<!-- feed-card manual-test marker: touch -- 2026-06-21 -->
