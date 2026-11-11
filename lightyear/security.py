# Quant AI Researcher
"""Who may change state on the Lightyear server.

- Host: only 127.0.0.1:<port> or localhost:<port>. Anything else (another site's name resolving to 127.0.0.1, i.e.
  DNS rebinding) is refused, so a web page cannot read this server's answers.
- Origin: a POST that carries an Origin header must come from the page itself.
- Token: a random token made at each launch. The page receives it when it loads and sends it in the
  X-Lightyear-Token header on every state-changing request. A web page on another site cannot read it (same-origin
  policy) and a headless Claude Code session is never given it.

The token is also written to TOKEN_FILE (outside the repository, removed on shutdown) so that
`run_pipeline.py --decision ... --token <token>` can check a human copied it from the page. Headless sessions are
denied reads of that folder (lightyear/jobs.py).
"""
import hmac
import os
import secrets

HEADER = "X-Lightyear-Token"
TOKEN = secrets.token_urlsafe(32)
TOKEN_FILE = os.environ.get("LIGHTYEAR_TOKEN_FILE") or os.path.join(
    os.path.expanduser("~"), ".lightyear", "session_token")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def port() -> int:
    return int(os.environ.get("LIGHTYEAR_PORT", "8100"))


def allowed_hosts() -> set[str]:
    p = port()
    return {f"127.0.0.1:{p}", f"localhost:{p}"}


def allowed_origins() -> set[str]:
    return {f"http://{h}" for h in allowed_hosts()}


def token_ok(value: str | None, expected: str | None = None) -> bool:
    expected = TOKEN if expected is None else expected
    return bool(value) and bool(expected) and hmac.compare_digest(str(value), str(expected))


def write_token_file() -> str:
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
        fh.write(TOKEN)
    return TOKEN_FILE


def remove_token_file() -> None:
    try:
        with open(TOKEN_FILE, encoding="utf-8") as fh:
            if fh.read().strip() != TOKEN:      # another launch owns it now
                return
        os.remove(TOKEN_FILE)
    except OSError:
        pass


def read_token_file(path: str | None = None) -> str | None:
    """The running server's token, for run_pipeline.py --decision. None when no Lightyear server is running."""
    try:
        with open(path or TOKEN_FILE, encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None
