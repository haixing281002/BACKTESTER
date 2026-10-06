"""Where Lightyear reads and writes. Everything a run produces lives under outputs/lightyear/<run_id>/."""
import glob
import os
import re
import shutil

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAPERS = os.path.join(REPO, "docs", "papers")
CARDS = os.path.join(REPO, "cards")
INTERP = os.path.join(REPO, "outputs", "interpretation")
RUNS = os.environ.get("LIGHTYEAR_RUNS") or os.path.join(REPO, "outputs", "lightyear")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
LEDGER = os.path.join(RUNS, "decisions.jsonl")


def rel(p: str) -> str:
    """Repo-relative with forward slashes when inside the repo, else absolute."""
    p = os.path.abspath(p)
    if p.startswith(os.path.abspath(REPO) + os.sep):
        return os.path.relpath(p, REPO).replace("\\", "/")
    return p.replace("\\", "/")


def run_dir(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", run_id or ""):
        raise ValueError(f"bad run id: {run_id!r}")
    return os.path.join(RUNS, run_id)


def slugify(filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename))[0].lower()
    return re.sub(r"[^a-z0-9]+", "_", base).strip("_")[:90] or "paper"


def find_claude() -> str:
    """The Claude Code CLI: $LIGHTYEAR_CLAUDE, then PATH, then the newest VS Code extension binary."""
    env = os.environ.get("LIGHTYEAR_CLAUDE")
    if env and os.path.exists(env):
        return env
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    pattern = os.path.expanduser(os.path.join("~", ".vscode", "extensions", "anthropic.claude-code-*",
                                              "resources", "native-binary", "claude*"))
    hits = [h for h in glob.glob(pattern) if os.path.basename(h).lower() in ("claude", "claude.exe")]
    if hits:
        def ver(p):
            m = re.search(r"claude-code-(\d+)\.(\d+)\.(\d+)", p)
            return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)
        return max(hits, key=ver)
    raise FileNotFoundError("Claude Code CLI not found. Install it, or set LIGHTYEAR_CLAUDE to claude.exe's full path.")
