# tests/test_status_report.py
# Tests for utils/status_report.py — the AGENTCTRL1 Phase 1a status reporter.
# Scope: collect()/assess()/renderers + the five stall classes + the §11.3
# content policy + feed cache + the §2.4/§4.4 alert-state helpers.
#
# HERMETICITY: every test runs under tmp_path with HOME / XDG_CACHE_HOME /
# XDG_CONFIG_HOME redirected, and the module's PROC_ROOT / CRASH_DIR pointed at
# fixture trees. Nothing here may read or write the real ~/.config/crabcakes,
# the real /proc, or /var/crash.
#
# HEADLESS: this suite must never import GTK (that is the point of the module)
# — it runs without xvfb.

import copy
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

import utils.feed_store as feed_store
import utils.status_report as status_report


NOW = 1_800_000_000.0  # fixed clock for deterministic reports

SECRET = "AKIA-SUPER-SECRET-KEY-1234567890"  # must never appear in any output


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Redirect HOME/XDG + /proc + /var/crash into tmp_path for every test."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    # Default: /proc readable but no app running, no crash reports.
    (home / "proc").mkdir()
    monkeypatch.setattr(status_report, "PROC_ROOT", str(home / "proc"))
    monkeypatch.setattr(status_report, "CRASH_DIR", str(home / "crash"))
    return home


def _project(tmp_path, name="proj"):
    project = tmp_path / name
    (project / "docs" / "specs").mkdir(parents=True)
    (project / ".crabcakes").mkdir(parents=True)
    (project / "docs" / "specs" / "SPEC-DEMO.md").write_text("# demo\n")
    (project / ".crabcakes" / "tasks.md").write_text(
        "# Work Units\n\n## 00000007 - Demo unit\n- **Status:** Done\n- **Priority:** High\n"
    )
    return project


def _config_dir(tmp_path):
    d = tmp_path / "home" / ".config" / "crabcakes"
    (d / "conversations").mkdir(parents=True, exist_ok=True)
    return d


def _msg(role, content, ts, tool_calls=None):
    return {
        "role": role,
        "content": content,
        "tool_calls": tool_calls or [],
        "tool_call_id": "call_deadbeef" if role == "tool" else "",
        "tokens_used": 1,
        "timestamp": datetime.fromtimestamp(ts).isoformat(),
    }


def _tool_call(name, args=None):
    return {"call_id": "call_1", "tool_name": name, "arguments": args or {}}


def _write_conversation(config_dir, session_key, project, messages,
                        mtime=None, agent_name="Coder", model="test/model",
                        raw=None):
    path = Path(config_dir) / "conversations" / f"{session_key}.json"
    if raw is not None:
        path.write_text(raw)
    else:
        path.write_text(json.dumps({
            "session_key": session_key,
            "agent_name": agent_name,
            "project_path": str(project),
            "model": model,
            "provider": "test",
            "messages": messages,
        }))
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _audit_record(ts, tool_name="exec_command", approved=True):
    return {"tool_name": tool_name, "args_hash": "h", "approved": approved,
            "user": "", "timestamp": ts, "result_hash": "r", "exit_code": 0}


def _write_audit_log(config_dir, records):
    path = Path(config_dir) / "audit-log.jsonl"
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return path


def _feed_card(title, body="body", ts=NOW, tool_name=None, tool_args=None,
               card_type="agent_action", source="agent", author="Coder",
               needs_approval=False):
    metadata = {}
    if tool_name:
        metadata["tool_name"] = tool_name
    if tool_args:
        metadata["tool_args"] = tool_args
    if needs_approval:
        metadata["needs_approval"] = True
    return {
        "card_type": card_type, "source": source, "title": title, "body": body,
        "author": author, "timestamp": datetime.fromtimestamp(ts).isoformat(),
        "project_name": "proj", "file_path": None, "commit_sha": None,
        "additions": None, "deletions": None, "task_id": None,
        "metadata": metadata, "card_id": "c1", "reviewed": False,
        "accepted": None, "seq_num": 1,
    }


def _write_feed(project, cards):
    path = Path(project) / ".crabcakes" / "feed.json"
    path.write_text(json.dumps(cards))
    return path


def _stat_line(pid, state, utime, stime, starttime=0, num_threads=1):
    """Build a /proc/<pid>/stat line with correct field offsets.

    After `)`, index 0 = field 3 (state), 11 = field 14 (utime),
    12 = field 15 (stime), 17 = field 20 (num_threads), 19 = field 22 (starttime).
    """
    rest = ["0", "1", "2", "3", "4", "5", "0", "0", "0", "0", "0",
            str(utime), str(stime), "0", "0", "20", "0", str(num_threads),
            "0", str(starttime), "1000000", "1000"]
    return f"{pid} (python3) {state} " + " ".join(rest) + "\n"


def _fake_app(tmp, project, pid=4242, state="S", wchan="poll", utime=100,
              cmdline=b"python3\x00main.py\x00", cwd=None, starttime=1000,
              rss_pages=45000):
    """Fabricate a /proc tree containing a running main.py for `project`.

    `tmp` is pytest's tmp_path; the tree lands at <tmp>/home/proc — the path the
    autouse fixture pinned PROC_ROOT to.
    """
    root = Path(tmp) / "home" / "proc"
    (root).mkdir(parents=True, exist_ok=True)
    (root / "stat").write_text("cpu 1 2 3 4\nbtime 1700000000\n")
    base = root / str(pid)
    (base / "task" / str(pid)).mkdir(parents=True, exist_ok=True)
    (base / "cmdline").write_bytes(cmdline)
    os.symlink(str(cwd if cwd is not None else project), base / "cwd")
    (base / "stat").write_text(_stat_line(pid, state, utime, 0, starttime))
    (base / "statm").write_text(f"{rss_pages} {rss_pages} 0 0 0 0 0\n")
    (base / "wchan").write_text(wchan + "\n")
    return base


def _git_repo(project):
    """Init a git repo with one commit; returns the commit timestamp."""
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=project, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=project,
                   check=True, env=env)
    return float(subprocess.run(["git", "log", "-1", "--format=%ct"], cwd=project,
                                check=True, capture_output=True, text=True).stdout.strip())


def _collect(project, config_dir, **kwargs):
    """collect() with the CPU sample window disabled (no sleeping in tests)."""
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("sample_interval", 0.0)
    return status_report.collect(str(project), str(config_dir), **kwargs)


def _sessions(report):
    return {s["session_key"]: s for s in report["agents"]["sessions"]}


def _stall_classes(report):
    return {s["class"] for s in report["stalls"]}


# ── app / exit-code basics ───────────────────────────────────────────────────

def test_report_healthy_exit0(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _fake_app(tmp_path, project)
    _write_conversation(config, "special:coder", project,
                        [_msg("user", "go", NOW - 600),
                         _msg("tool", "ok", NOW - 590)],
                        mtime=NOW - 590)
    report = _collect(project, config)

    assert report["app"]["running"] is True
    assert report["app"]["pid"] == 4242
    assert report["app"]["main_thread"] == "idle"
    assert report["app"]["rss_kb"] == 45000 * (os.sysconf("SC_PAGE_SIZE") // 1024)
    assert report["stalls"] == []
    summary, code = status_report.assess(report)
    assert code == 0
    assert "healthy" in summary.lower()


def test_report_runs_with_app_closed_returns_exit3(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    report = _collect(project, config)

    assert report["app"]["running"] is False
    assert report["app"]["pid"] is None
    # a closed app is a normal state, not a degradation (ruling 3 degrades only
    # when /proc itself is unreadable — see the degraded-path test below)
    assert report["app"]["degraded"] is False
    assert report["app"]["app_running_degraded"] is False
    assert "app" not in report["degraded_sections"]
    # the filesystem side still emits
    assert report["work"]["spec"] == "SPEC-DEMO.md"
    assert report["work"]["unit"] == "00000007 - Demo unit"
    assert report["work"]["unit_status"] == "Done"
    assert "AGENTS" in status_report.render_text(report)
    summary, code = status_report.assess(report)
    assert code == 3
    assert summary.startswith("app_not_running")
    assert "no main.py" in summary


# ── turn_stalled ─────────────────────────────────────────────────────────────

def test_turn_stalled_detected(tmp_path):
    """The 2026-09-11 shape: assistant-final, idle > threshold, no repo writes."""
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _fake_app(tmp_path, project)
    last = "Confirmed the bug. Writing the red tests first."
    _write_conversation(config, "special:coder", project,
                        [_msg("user", "fix it", NOW - 4000),
                         _msg("assistant", last, NOW - 3600,
                              tool_calls=[_tool_call("exec_command",
                                                     {"command": SECRET})])],
                        mtime=NOW - 3600)
    report = _collect(project, config)

    assert "turn_stalled" in _stall_classes(report)
    session = _sessions(report)["special:coder"]
    assert session["last_role"] == "assistant"
    assert session["idle_seconds"] == pytest.approx(3600, abs=5)
    # a dangling tool call is reported by NAME only — never its arguments
    assert session["tool_names"] == ["exec_command"]
    assert session["pending_tool_calls"] is True
    assert SECRET not in json.dumps(report)
    summary, code = status_report.assess(report)
    assert code == 2
    assert "turn_stalled" in summary
    assert "special:coder" in summary and "Coder" in summary
    assert "60" in summary or "60 minutes" in summary or "60m" in summary


def test_turn_stalled_not_fired_when_tool_follows(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _fake_app(tmp_path, project)
    _write_conversation(config, "special:coder", project,
                        [_msg("assistant", "running tests", NOW - 4000),
                         _msg("tool", "1 passed", NOW - 3600,
                              tool_calls=None)],
                        mtime=NOW - 3600)
    report = _collect(project, config)

    assert report["stalls"] == []
    assert _sessions(report)["special:coder"]["last_role"] == "tool"
    assert status_report.assess(report)[1] == 0


def test_turn_stalled_not_fired_when_repo_write_is_newer(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _fake_app(tmp_path, project)
    _write_conversation(config, "special:coder", project,
                        [_msg("assistant", "writing tests", NOW - 3600)],
                        mtime=NOW - 3600)
    edited = project / "utils.py"
    edited.write_text("x = 1\n")
    os.utime(edited, (NOW - 60, NOW - 60))  # a real repo write after the message
    report = _collect(project, config)

    assert report["stalls"] == []
    assert status_report.assess(report)[1] == 0


def test_turn_stalled_not_fired_within_threshold(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _fake_app(tmp_path, project)
    _write_conversation(config, "special:coder", project,
                        [_msg("assistant", "still working", NOW - 120)],
                        mtime=NOW - 120)
    report = _collect(project, config)

    assert report["stalls"] == []
    assert _sessions(report)["special:coder"]["idle_seconds"] == pytest.approx(120, abs=5)


def test_turn_stalled_threshold_uses_module_constant(tmp_path, monkeypatch):
    monkeypatch.setattr(status_report, "STALL_THRESHOLD_MINUTES", 60)
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _fake_app(tmp_path, project)
    _write_conversation(config, "special:coder", project,
                        [_msg("assistant", "idle 30m", NOW - 1800)],
                        mtime=NOW - 1800)
    report = _collect(project, config)
    assert report["stalls"] == []


def test_truncated_conversation_json_degrades_only_that_section(tmp_path):
    """Non-atomic writer artefact: torn JSON must degrade one session only."""
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _fake_app(tmp_path, project)
    _write_conversation(config, "special:supervisor", project,
                        [_msg("assistant", "fine", NOW - 30)], mtime=NOW - 30)
    _write_conversation(config, "special:coder", project, [],
                        mtime=NOW - 30,
                        raw='{"session_key": "special:coder", "messages": [{"role"')
    report = _collect(project, config)

    sessions = _sessions(report)
    assert sessions["special:coder"]["unreadable"] is True
    assert sessions["special:coder"]["last_role"] is None
    assert sessions["special:supervisor"]["unreadable"] is False
    assert "special:supervisor" in status_report.render_text(report)
    assert report["agents"]["degraded"] is True


# ── feed: no lock, cache ─────────────────────────────────────────────────────

def test_report_never_acquires_feed_lock(tmp_path, monkeypatch):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _write_feed(project, [_feed_card("Coder is reading x", ts=NOW - 10)])

    def _boom(*a, **kw):
        raise AssertionError("status reporter must never take the feed lock")

    monkeypatch.setattr(feed_store, "_acquire_lock", _boom)
    monkeypatch.setattr(feed_store, "load_feed", _boom)
    report = _collect(project, config)

    assert report["activity"]["count"] == 1  # parsed without the lock path
    assert report["activity"]["total_cards"] == 1


def test_feed_summary_cached_by_mtime(tmp_path, monkeypatch):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    feed = _write_feed(project, [_feed_card("card A", ts=NOW - 10)])

    real = status_report._parse_feed_cards
    calls = []

    def counting(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(status_report, "_parse_feed_cards", counting)
    first = _collect(project, config)
    second = _collect(project, config)

    assert len(calls) == 1, "second collect() re-parsed the feed"
    assert first["activity"]["cache"] == "miss"
    assert second["activity"]["cache"] == "hit"
    assert [c["title"] for c in second["activity"]["cards"]] == ["card A"]
    cache_path = Path(status_report.cache_dir()) / status_report.CACHE_FILENAME
    assert cache_path.is_file()
    cached = json.loads(cache_path.read_text())
    assert cached["key"]["size"] == feed.stat().st_size
    assert cached["key"]["mtime"] == pytest.approx(feed.stat().st_mtime, abs=1e-6)

    # invalidate: the feed changed
    feed.write_text(json.dumps([_feed_card("card A", ts=NOW - 10),
                                _feed_card("card B", ts=NOW - 5)]))
    third = _collect(project, config)
    assert len(calls) == 2
    assert third["activity"]["cache"] == "miss"
    assert third["activity"]["count"] == 2


def test_feed_skipped_when_include_feed_false(tmp_path, monkeypatch):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _write_feed(project, [_feed_card("card A", ts=NOW - 10)])

    real = status_report._parse_feed_cards
    calls = []

    def counting(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(status_report, "_parse_feed_cards", counting)
    report = _collect(project, config, include_feed=False)

    assert calls == []
    assert report["activity"]["cache"] == "skipped"
    assert report["activity"]["cards"] == []
    # ruling 2: the other sections still run
    assert report["work"]["spec"] == "SPEC-DEMO.md"
    assert report["agents"]["sessions"] == []


# ── content policy (§2.1 / §11.3) ────────────────────────────────────────────

def test_content_truncated_by_default(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    long_text = "A" * 90 + SECRET + "B" * 90
    _write_conversation(config, "special:coder", project,
                        [_msg("assistant", long_text, NOW - 30)], mtime=NOW - 30)
    report = _collect(project, config)

    session = _sessions(report)["special:coder"]
    assert len(session["last_message"]) <= status_report.BODY_CAP_DEFAULT
    assert SECRET not in json.dumps(report)
    text = status_report.render_text(report)
    assert SECRET not in text
    assert "A" * 90 in text


def test_full_flag_raises_message_cap_only(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    # body is 2500 chars of message + a secret beyond the 2 000-char --full cap
    body = "M" * 1500 + "P" * 1000 + SECRET
    _write_conversation(config, "special:coder", project,
                        [_msg("assistant", body, NOW - 30)], mtime=NOW - 30)
    report = _collect(project, config, body_cap=status_report.BODY_CAP_FULL)

    session = _sessions(report)["special:coder"]
    assert len(session["last_message"]) == status_report.BODY_CAP_FULL
    full_text = status_report.render_text(report, show_content=True)
    assert "M" * 1500 in full_text          # message bodies raised to 2000
    assert "P" * 500 in full_text           # …which is 1500 M's + 500 P's
    assert "P" * 501 not in full_text       # …and stops exactly at the cap
    assert SECRET not in full_text          # …so the secret is never rendered
    default_text = status_report.render_text(report)
    assert "M" * 1500 not in default_text   # render-time cap holds at 120


def test_feed_card_command_never_rendered(tmp_path):
    """Tool args / exec commands / outputs are never rendered at any verbosity."""
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    command = f"cd /tmp && export TOKEN={SECRET} && rm -rf /"
    _write_feed(project, [
        _feed_card(f"Coder is running: {command}",
                   body=f"$ {command}\noutput: {SECRET}",
                   tool_name="exec_command", tool_args={"command": command},
                   ts=NOW - 10),
        _feed_card("Coder requests approval to run command",
                   body=f"$ {command}", tool_name="exec_command",
                   tool_args={"command": command}, needs_approval=True,
                   ts=NOW - 5),
        _feed_card("docs: post-mortem", body=f"notes {SECRET}",
                   card_type="git_commit", source="git", author="git",
                   ts=NOW - 3),
        _feed_card("long non-tool title " + "T" * 400, card_type="system",
                   source="system", author="system", ts=NOW - 2),
    ])
    # tool output lands in the conversation too
    _write_conversation(config, "special:coder", project,
                        [_msg("assistant", "run it", NOW - 20),
                         _msg("tool", f"stdout: {SECRET}", NOW - 10)],
                        mtime=NOW - 10)
    report = _collect(project, config, body_cap=status_report.BODY_CAP_FULL)

    dumped = json.dumps(report) + status_report.render_json(report)
    dumped += status_report.render_text(report)
    dumped += status_report.render_text(report, show_content=True)
    assert SECRET not in dumped
    assert command not in dumped

    cards = report["activity"]["cards"]
    assert [c["tool_name"] for c in cards[:2]] == ["exec_command", "exec_command"]
    assert cards[0]["title"] == ""            # command-bearing title dropped
    assert cards[0]["needs_approval"] is False
    assert cards[1]["needs_approval"] is True
    assert cards[2]["tool_name"] is None
    assert cards[2]["title"] == "docs: post-mortem"   # non-tool title kept
    # titles are capped at COMMAND_CAP at every verbosity — --full widens bodies
    # only, so a command hiding in a title cannot be widened either
    assert len(cards[3]["title"]) == status_report.COMMAND_CAP
    assert "T" * 400 not in dumped
    # the tool OUTPUT in the conversation is reported, never its content
    session = _sessions(report)["special:coder"]
    assert session["last_role"] == "tool"
    assert session["last_message"] == ""
    assert "tool output omitted" in status_report.render_text(report)


def test_render_json_round_trips_report(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _write_feed(project, [_feed_card("card A", ts=NOW - 10)])
    report = _collect(project, config)

    rendered = status_report.render_json(report)
    assert rendered.startswith("{\n  ")          # indent=2
    assert json.loads(rendered) == report


# ── blocked_on_sendback ──────────────────────────────────────────────────────

def test_blocked_on_sendback_detected(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _fake_app(tmp_path, project)
    commit_ts = _git_repo(project)
    sendback = project / "docs" / "specs" / "SPEC-DEMO-SENDBACK.md"
    sendback.write_text("rejected — fix X\n")
    stamp = commit_ts + 120
    os.utime(sendback, (stamp, stamp))
    report = _collect(project, config, now=commit_ts + 3600)

    assert "blocked_on_sendback" in _stall_classes(report)
    assert report["work"]["is_repo"] is True
    assert report["work"]["newest_commit_ts"] == pytest.approx(commit_ts, abs=1)
    summary, code = status_report.assess(report)
    assert code == 2
    assert "SENDBACK" in summary


def test_sendback_older_than_commit_not_detected(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _fake_app(tmp_path, project)
    sendback = project / "docs" / "specs" / "SPEC-DEMO-SENDBACK.md"
    sendback.write_text("rejected — fixed already\n")
    commit_ts = _git_repo(project)
    stamp = commit_ts - 120
    os.utime(sendback, (stamp, stamp))
    report = _collect(project, config, now=commit_ts + 3600)

    assert "blocked_on_sendback" not in _stall_classes(report)


# ── app_spinning ─────────────────────────────────────────────────────────────

def test_app_spinning_detected_from_two_samples(tmp_path, monkeypatch):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _fake_app(tmp_path, project, state="R", wchan="0", utime=100)

    real = status_report._read_proc_stat
    seen = []

    def ramping(pid, proc_root=None):
        stat = real(pid, proc_root)
        # each successive sample shows 500 more ticks of CPU: the reporter's
        # scan-phase read, then the two samples of the busy check
        bumped = (dict(stat, utime=stat["utime"] + 500.0 * len(seen))
                  if stat is not None else stat)
        seen.append(stat)
        return bumped

    monkeypatch.setattr(status_report, "_read_proc_stat", ramping)
    report = _collect(project, config, sample_interval=0.05,
                      now=time.time())

    app = report["app"]
    assert app["main_thread"] == "busy"
    assert app["cpu_percent"] > 80
    assert app["cpu_percent"] <= 100
    assert "app_spinning" in _stall_classes(report)
    assert status_report.assess(report)[1] == 2


def test_app_idle_reported_when_sleeping(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _fake_app(tmp_path, project, state="S", wchan="poll_schedule_timeout")
    report = _collect(project, config)

    app = report["app"]
    assert app["main_thread"] == "idle"
    assert app["state"] == "S"
    assert app["wchan"] == "poll_schedule_timeout"
    assert app["cpu_percent"] is None      # no second sample for a sleeping app
    assert app["thread_count"] == 1
    assert "app_spinning" not in _stall_classes(report)


def test_app_running_degraded_when_proc_unreadable(tmp_path, monkeypatch):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    monkeypatch.setattr(status_report, "PROC_ROOT", str(tmp_path / "nope"))
    report = _collect(project, config)

    assert report["app"]["running"] is False
    assert report["app"]["app_running_degraded"] is True
    assert report["app"]["degraded_reason"]
    assert "app" in report["degraded_sections"]


def test_write_scan_truncation_is_flagged(tmp_path, monkeypatch):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    monkeypatch.setattr(status_report, "WALK_FILE_CAP", 3)
    for i in range(8):
        (project / f"f{i}.py").write_text("x = 1\n")
    report = _collect(project, config)

    scan = report["work"]["write_scan"]
    assert scan["truncated"] is True
    assert scan["files"] <= 3
    assert report["work"]["degraded"] is True


# ── approvals_pending ────────────────────────────────────────────────────────

def test_approvals_pending_detected(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _fake_app(tmp_path, project)
    _write_audit_log(config, [_audit_record(NOW - 900),
                              _audit_record(NOW - 600),
                              _audit_record(NOW - 300, approved=False)])
    report = _collect(project, config)

    assert report["approvals"]["entries"] == 3
    assert report["approvals"]["grants"] == 2
    assert report["approvals"]["denials"] == 1
    assert "approvals_pending" in _stall_classes(report)
    assert status_report.assess(report)[1] == 2


def test_approvals_pending_not_fired_when_write_follows(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _fake_app(tmp_path, project)
    written = project / "out.py"
    written.write_text("x = 1\n")
    os.utime(written, (NOW - 100, NOW - 100))
    _write_audit_log(config, [_audit_record(NOW - 900),
                              _audit_record(NOW - 600),
                              _audit_record(NOW - 300)])
    report = _collect(project, config)

    assert report["approvals"]["entries"] == 3
    assert "approvals_pending" not in _stall_classes(report)

    # …and not when the window is quiet
    two = _collect(project, config, now=NOW + 4000)
    assert "approvals_pending" not in _stall_classes(two)
    assert two["approvals"]["entries"] == 0


# ── crash_after_start ────────────────────────────────────────────────────────

def test_crash_after_start_detected_and_cmdline_capped(tmp_path, monkeypatch):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    crash_dir = tmp_path / "home" / "crash"
    crash_dir.mkdir()
    _fake_app(tmp_path, project)  # boot time 1700000000, starttime 1000
    long_cmd = "python3 -m pytest " + "x" * 400
    crash = crash_dir / "crash_after.crash"
    crash.write_text(
        "ProblemType: Crash\n"
        "ExecutablePath: /usr/bin/python3.12\n"
        f"ProcCmdline: {long_cmd}\n"
        "Date: %s\n"
        "Signal: 11\n" % datetime.fromtimestamp(1789228000).strftime("%a %b %d %H:%M:%S %Y")
    )
    monkeypatch.setattr(status_report, "CRASH_DIR", str(crash_dir))
    report = _collect(project, config, now=1789229000.0)

    crashes = report["health"]["crashes"]
    assert len(crashes) == 1
    assert crashes[0]["signal"] == "11"
    assert crashes[0]["executable"] == "python3.12"
    assert len(crashes[0]["proc_cmdline"]) <= status_report.COMMAND_CAP
    assert "crash_after_start" in _stall_classes(report)
    assert status_report.assess(report)[1] == 2


# ── assess precedence ────────────────────────────────────────────────────────

def test_assess_precedence_and_worst_class(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    # app down beats everything
    down = _collect(project, config)
    assert status_report.assess(down)[1] == 3

    # app up + two stall classes -> worst = app_spinning (order, not list order)
    _fake_app(tmp_path, project, state="R", wchan="0", utime=0)
    commit_ts = _git_repo(project)
    sendback = project / "docs" / "specs" / "SPEC-DEMO-SENDBACK.md"
    sendback.write_text("rejected\n")
    stamp = commit_ts + 120
    os.utime(sendback, (stamp, stamp))
    report = _collect(project, config, now=commit_ts + 3600)
    # force the busy classification without a second sample window
    report["app"]["main_thread"] = "busy"
    status_report.assess(report)  # stamps stalls from the mutated report
    report["stalls"] = [s for s in report["stalls"] if s["class"] != "app_spinning"]
    report["stalls"].insert(0, {"class": "app_spinning", "detail": "pid 4242 spinning"})
    summary, code = status_report.assess(report)
    assert code == 2
    assert summary.startswith("app_spinning")


# ── alert-state helpers (§2.4 / §4.4) ────────────────────────────────────────

def test_alert_deduped_by_episode(tmp_path):
    state_file = tmp_path / "state.json"
    state = status_report.load_alert_state(str(state_file))
    assert state == {}

    episode = status_report.episode_id("special:coder", NOW - 3600, "abc123")
    alert, state = status_report.should_alert(state, episode, NOW)
    assert alert is True
    assert state["episodes"][episode]["first_seen"] == NOW
    assert state["episodes"][episode]["attempts"] == 1
    status_report.save_alert_state(str(state_file), state)

    # re-loaded state: same episode inside the re-alert floor -> silence
    reloaded = status_report.load_alert_state(str(state_file))
    alert, reloaded = status_report.should_alert(reloaded, episode, NOW + 60)
    assert alert is False
    assert reloaded["episodes"][episode]["attempts"] == 1

    # …until the floor elapses
    alert, reloaded = status_report.should_alert(reloaded, episode, NOW + 3700)
    assert alert is True
    assert reloaded["episodes"][episode]["attempts"] == 2
    assert reloaded["episodes"][episode]["last_alert"] == NOW + 3700

    # a new episode alerts immediately (state change)
    other = status_report.episode_id("special:coder", NOW - 60, "def456")
    alert, reloaded = status_report.should_alert(reloaded, other, NOW + 3701)
    assert alert is True
    assert set(reloaded["episodes"]) == {episode, other}

    # healthy (no episode) never alerts and is not recorded
    alert, reloaded = status_report.should_alert(reloaded, None, NOW + 4000)
    assert alert is False
    alert, reloaded = status_report.should_alert(reloaded, "", NOW + 4000)
    assert alert is False
    assert set(reloaded["episodes"]) == {episode, other}


def test_episode_id_stable_then_changes():
    a = status_report.episode_id("special:coder", 1234.5, "sha")
    assert a == status_report.episode_id("special:coder", 1234.5, "sha")
    assert len(a) == 16 and all(c in "0123456789abcdef" for c in a)
    assert a != status_report.episode_id("special:debugger", 1234.5, "sha")
    assert a != status_report.episode_id("special:coder", 1234.6, "sha")
    assert a != status_report.episode_id("special:coder", 1234.5, "other")


def test_load_alert_state_tolerant(tmp_path):
    missing = tmp_path / "nope.json"
    assert status_report.load_alert_state(str(missing)) == {}

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json")
    assert status_report.load_alert_state(str(corrupt)) == {}

    wrong_type = tmp_path / "list.json"
    wrong_type.write_text("[1, 2, 3]")
    assert status_report.load_alert_state(str(wrong_type)) == {}

    garbage_shape = tmp_path / "shape.json"
    garbage_shape.write_text('{"episodes": "not a dict"}')
    assert status_report.load_alert_state(str(garbage_shape)) == {}


def test_save_alert_state_atomic_and_0600(tmp_path):
    path = tmp_path / "sub" / "state.json"
    status_report.save_alert_state(str(path), {"episodes": {"x": {"attempts": 1}},
                                              "last_exit": 2})
    assert path.is_file()
    assert (path.stat().st_mode & 0o777) == 0o600
    assert json.loads(path.read_text())["last_exit"] == 2
    leftovers = [p.name for p in path.parent.iterdir() if p.name != "state.json"]
    assert leftovers == [], f"atomic write left debris: {leftovers}"

    # overwrite is also atomic + still 0600
    status_report.save_alert_state(str(path), {"episodes": {}, "last_exit": 0})
    assert json.loads(path.read_text())["episodes"] == {}
    assert (path.stat().st_mode & 0o777) == 0o600


def test_alert_helpers_do_not_mutate_caller_state():
    state = {"episodes": {"old": {"first_seen": 1.0, "last_alert": 1.0,
                                 "attempts": 1}}, "last_exit": 2}
    before = copy.deepcopy(state)
    episode = status_report.episode_id("special:coder", NOW, "sha")

    _, updated = status_report.should_alert(state, episode, NOW)
    assert state == before, "should_alert mutated the caller's state"
    assert "old" in updated["episodes"] and episode in updated["episodes"]

    again = status_report.mark_alerted(state, episode, NOW)
    assert state == before, "mark_alerted mutated the caller's state"
    assert again["episodes"][episode]["last_alert"] == NOW
    assert again["last_exit"] == 2


# ── hermeticity ──────────────────────────────────────────────────────────────

def test_cache_dir_is_0700_under_xdg_cache_home(tmp_path):
    cache = Path(status_report.cache_dir())
    assert cache.is_dir()
    assert (cache.stat().st_mode & 0o777) == 0o700
    assert str(cache).startswith(str(tmp_path / "home" / ".cache"))
    assert Path(status_report.state_path()).parent == cache
    assert status_report.state_path().endswith(status_report.STATE_FILENAME)


def test_report_writes_nothing_outside_cache(tmp_path):
    project = _project(tmp_path)
    config = _config_dir(tmp_path)
    _fake_app(tmp_path, project)
    _write_feed(project, [_feed_card("card A", ts=NOW - 10)])
    _write_conversation(config, "special:coder", project,
                        [_msg("assistant", "hi", NOW - 60)], mtime=NOW - 60)

    def snapshot():
        seen = set()
        for root, dirs, files in os.walk(tmp_path):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in files:
                seen.add(os.path.join(root, name))
        return seen

    before = snapshot()
    _collect(project, config, body_cap=status_report.BODY_CAP_FULL)
    status_report.render_text(_collect(project, config))
    cache_root = status_report.cache_dir()
    new = {p for p in snapshot() - before if not p.startswith(cache_root + os.sep)}
    assert new == set(), f"reporter wrote outside its cache dir: {sorted(new)}"


def test_module_imports_headless_without_gtk(tmp_path):
    """§2.3.1: the reporter imports in a fresh interpreter and pulls in no GTK.

    A clean process is the real cron/headless shape. The child inherits this
    process's `sys.path` (so user-site packages like GitPython resolve even
    though the autouse fixture has redirected HOME for hermeticity).
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = (
        "import importlib.util, sys;"
        "print('GI_AVAILABLE', importlib.util.find_spec('gi') is not None);"
        "import utils.status_report as sr;"
        "assert 'gi' not in sys.modules, sorted(m for m in sys.modules if m.startswith('gi'));"
        "assert 'ui' not in sys.modules, 'ui/ was imported';"
        "print('OK', sr.STALL_THRESHOLD_MINUTES)"
    )
    env = {"PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=60, env=env, cwd=root)
    assert proc.returncode == 0, f"headless import failed:\n{proc.stdout}\n{proc.stderr}"
    # GTK is installed on this box, so the no-GTK assertion above is not vacuous
    assert "GI_AVAILABLE True" in proc.stdout
    assert "OK 10" in proc.stdout
