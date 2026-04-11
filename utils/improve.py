# utils/improve.py
# Prompt improvement via MiniMax API.
#
# Security Manifest:
#   Reads: ~/.config/crabcakes/config.json (apiKey, baseUrl, model)
#   Reads: <crabcakes_root>/prompts/improve-system-prompt.md (system prompt template)
#   External: POST to baseUrl (MiniMax API), HTTPS
#   No files written; no secrets stored

import json
import os
import threading
import urllib.request

DEFAULT_BASE_URL = "https://api.minimax.io/v1/text/chatcompletion_v2"
DEFAULT_MODEL = "MiniMax-M2.5-Lightning"
DEFAULT_SYSTEM_PROMPT = """You are an expert technical editor. Rewrite all input text to be maximally clear, detailed, and precise.

Specifically:
• Replace vague or ambiguous phrasing with specific, concrete language
• Expand every abbreviation and acronym on first use
• Define unexplained jargon and technical terms inline
• Add precision where statements are general or hand-wavy
• Correct all spelling, grammar, and punctuation errors
• Structure output to mirror input order — do not reorder, summarize, or omit content

Output format:
• Return ONLY the improved text — no preamble, no explanation, no quotes, no labels, no commentary
• Preserve all original meaning and intent
• Be maximally verbose — completeness and precision always outweigh brevity"""

_config = None
_config_lock = threading.Lock()


def _load_config():
    """Load config from ~/.config/crabcakes/config.json (cached)."""
    global _config
    with _config_lock:
        if _config is not None:
            return _config
        path = os.path.join(os.path.expanduser("~/.config/crabcakes/config.json"))
        try:
            with open(path) as f:
                _config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _config = {}
        return _config


def improve_prompt(raw_text, callback, GLib=None):
    """
    Improve a prompt by sending it to the MiniMax API.

    Runs in a background thread. Calls callback(improved_text, error) when done.
    If GLib is provided, callback is dispatched via GLib.idle_add (thread-safe).

    Args:
        raw_text:   The raw prompt text to improve.
        callback:   Function(improved_text, error). error is None on success.
        GLib:       Optional GLib module for GTK main thread dispatch.
    """
    cfg = _load_config()

    api_key = cfg.get("apiKey", "").strip()
    if not api_key:
        _dispatch(callback, None, "MINIMAX_API_KEY not set in ~/.config/crabcakes/config.json", GLib)
        return

    base_url = cfg.get("baseUrl", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    model = cfg.get("model", DEFAULT_MODEL).strip() or DEFAULT_MODEL

    # Load system prompt from file
    prompts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts")
    system_prompt = DEFAULT_SYSTEM_PROMPT
    prompt_path = os.path.join(prompts_dir, "improve-system-prompt.md")
    if os.path.isfile(prompt_path):
        try:
            with open(prompt_path) as f:
                loaded = f.read().strip()
            if loaded:
                system_prompt = loaded
        except (IOError, OSError):
            pass

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_text},
        ],
        "temperature": 0.3,
    }).encode()

    def _thread():
        try:
            req = urllib.request.Request(
                base_url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
            choices = body.get("choices")
            if not choices:
                raise ValueError(f"API error: {body.get('error', 'no choices in response')}")
            msg = choices[0].get("message")
            if not isinstance(msg, dict) or "content" not in msg:
                raise ValueError(f"API error: choices[0].message missing 'content': {msg}")
            improved = msg.get("content")
            if not isinstance(improved, str):
                improved = str(improved) if improved else ""
            _dispatch(callback, improved, None, GLib)
        except Exception as e:
            _dispatch(callback, None, str(e), GLib)

    t = threading.Thread(target=_thread, daemon=True)
    t.start()


def _dispatch(callback, text, error, GLib):
    """Thread-safe callback dispatch.

    If GLib is provided, uses GLib.idle_add to schedule the callback on the GTK
    main thread. This is required whenever the caller is a background thread and the
    callback makes GTK calls (which are not thread-safe).

    GLib.idle_add returns False from _safe to remove the source after one execution."""
    def _safe():
        try:
            callback(text, error)
        except Exception:
            pass
        return False
    if GLib is not None:
        GLib.idle_add(_safe)
    else:
        _safe()
