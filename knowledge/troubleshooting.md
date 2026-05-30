# Troubleshooting Guide

## Common Issues

### App Won't Start

**Symptom:** Crabcakes crashes on launch or won't open.

**Check:**
1. Python version: `python3 --version` (needs 3.12+)
2. GTK installation: `python3 -c "import gi; gi.require_version('Gtk', '4.0')"`
3. Dependencies: `pip install -e .` from the Crabcakes directory

### "No API key configured" Error

**Symptom:** Special agents fail with "No API key configured for provider X".

**Fix:**
1. Edit `~/.config/crabcakes/agent.json`
2. Add your API key for the relevant provider
3. Restart Crabcakes

The Crabcakes help agent uses a built-in Google Gemini key as fallback, so it should work even without a configured key.

### Gateway Won't Connect

**Symptom:** Toolbar shows "Offline" or "Connecting..." indefinitely.

**Check:**
1. Gateway is running: `openclaw gateway status`
2. Gateway URL is correct in settings
3. Port is accessible (not blocked by firewall)
4. Device key is registered: `openclaw device list`

### Agent Not Responding

**Symptom:** Messages sent but no response from an agent.

**Check:**
1. For gateway agents: verify the agent has an active session
2. For special agents: verify the provider has a valid API key
3. Check the Crabcakes logs at `~/.config/crabcakes/logs/`

### Project Tab Shows Wrong Content

**Symptom:** Project tab shows messages from the wrong project or no messages at all.

**Fix:**
1. Close the project tab (right-click → Close)
2. Re-open the project from the left panel
3. If issue persists, check `.crabcakes/team.json` for corrupted entries

### Config Reset

To completely reset Crabcakes configuration:

```bash
# Backup first
cp -r ~/.config/crabcakes ~/.config/crabcakes.backup

# Remove config (fresh start on next launch)
rm -rf ~/.config/crabcakes
```

### Log Files

Crabcakes logs are located at:

```
~/.config/crabcakes/logs/
```

Set `CRABCAKES_LOG_LEVEL=DEBUG` for verbose logging. Useful when reporting bugs.

## Getting Help

- The Crabcakes 🦀 agent can answer most questions — just ask in its tab
- For gateway issues, check OpenClaw documentation at `https://docs.openclaw.ai`
- For bugs, check the GitHub issues at the Crabcakes repository