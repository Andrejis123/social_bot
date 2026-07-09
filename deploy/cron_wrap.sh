#!/bin/bash
# cron_wrap.sh <job-name> <command...>
#
# Runs the wrapped cron command and, if it exits non-zero, sends a Telegram
# alert with the job name and exit code. The wrapper is the cron parent
# process, so it survives what the wrapped container doesn't: a kernel OOM
# SIGKILL of `docker run` (exit 137) is silent from inside the container —
# no traceback, no in-app Telegram, no log line (the 4 Jul 2026 ecig archive
# died exactly this way). Alerting is best-effort: a missing env file or a
# failed curl must never mask the wrapped command's exit code.
#
# Telegram credentials are read from the env file at $CRON_WRAP_ENV
# (default /opt/social-bot/.env).

set -u

# Extract one KEY's value from the env file. Deliberately not `source`d:
# other values in .env may contain spaces/quotes/$ that break sourcing.
env_val() {
    grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'"
}

notify() {
    ENV_FILE="${CRON_WRAP_ENV:-/opt/social-bot/.env}"
    [ -f "$ENV_FILE" ] || return 0
    local token chat stamp
    token=$(env_val TELEGRAM_BOT_TOKEN)
    chat=$(env_val TELEGRAM_CHAT_ID)
    [ -n "$token" ] && [ -n "$chat" ] || return 0
    stamp="$(hostname) at $(date -u +'%d-%m-%Y %H:%M UTC')"
    curl -s -m 20 -X POST \
        "https://api.telegram.org/bot${token}/sendMessage" \
        --data-urlencode "chat_id=${chat}" \
        --data-urlencode "text=$1 on ${stamp}" \
        >/dev/null 2>&1 || true
}

if [ "$#" -lt 2 ]; then
    # A truncated crontab line (job name but no command) would otherwise fail
    # silently forever — the exact failure class this wrapper exists to catch.
    notify "🚨 cron_wrap misconfigured: job '${1:-<no job name>}' has no command (exit 64)"
    echo "usage: cron_wrap.sh <job-name> <command...>" >&2
    exit 64
fi

JOB_NAME="$1"
shift

"$@"
EXIT_CODE=$?

if [ "$EXIT_CODE" -ne 0 ]; then
    notify "🚨 cron job '${JOB_NAME}' failed (exit ${EXIT_CODE})"
fi

exit "$EXIT_CODE"
