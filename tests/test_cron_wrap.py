"""Failing-first tests for deploy/cron_wrap.sh (spec item 7).

Contract:
    cron_wrap.sh <job-name> <command...>

* Sources TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID from the env file at
  $CRON_WRAP_ENV (default /opt/social-bot/.env).
* Runs the wrapped command and propagates its exit code.
* On non-zero exit it POSTs a Telegram sendMessage via curl that includes the
  job name and the exit code; on success no curl call is made.
* A missing env file must not mask the wrapped command's exit code.

No live Telegram: a stub `curl` executable prepended to PATH appends its args
to a log file. These tests FAIL right now (assert on the script's existence
and behavior) because deploy/cron_wrap.sh has not been written yet.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "cron_wrap.sh"


@pytest.fixture
def wrap_env(tmp_path):
    """(env, curl_log) with a stub curl on PATH and CRON_WRAP_ENV set."""
    env_file = tmp_path / "cron.env"
    env_file.write_text(
        'TELEGRAM_BOT_TOKEN="tok-abc"\nTELEGRAM_CHAT_ID="chat-999"\n'
    )

    bindir = tmp_path / "bin"
    bindir.mkdir()
    curl_log = tmp_path / "curl.log"
    curl = bindir / "curl"
    curl.write_text('#!/bin/bash\necho "$@" >> "$CURL_LOG"\n')
    curl.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["CRON_WRAP_ENV"] = str(env_file)
    env["CURL_LOG"] = str(curl_log)
    return env, curl_log


def _run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_success_propagates_zero_and_no_curl(wrap_env):
    assert SCRIPT.exists(), "deploy/cron_wrap.sh does not exist yet"
    env, curl_log = wrap_env

    result = _run(env, "nightly-archive", "true")

    assert result.returncode == 0, result.stderr
    # Success must not fire a Telegram notification.
    assert not curl_log.exists() or curl_log.read_text().strip() == ""


def test_failure_notifies_once_and_propagates_exit_code(wrap_env):
    assert SCRIPT.exists(), "deploy/cron_wrap.sh does not exist yet"
    env, curl_log = wrap_env

    result = _run(env, "nightly-archive", "bash", "-c", "exit 7")

    assert result.returncode == 7, result.stderr
    assert curl_log.exists(), "expected exactly one curl (Telegram) call"
    lines = [ln for ln in curl_log.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    assert "nightly-archive" in lines[0]  # job name in the message
    assert "7" in lines[0]  # exit code in the message


def test_missing_env_file_still_propagates_exit_code(wrap_env, tmp_path):
    assert SCRIPT.exists(), "deploy/cron_wrap.sh does not exist yet"
    env, _curl_log = wrap_env
    env["CRON_WRAP_ENV"] = str(tmp_path / "does-not-exist.env")

    result = _run(env, "nightly-archive", "bash", "-c", "exit 5")

    assert result.returncode == 5, result.stderr
