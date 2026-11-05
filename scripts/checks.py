"""One check suite for Git hooks, CI and local development (no live API calls)."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def check_dependencies(backend=True, frontend=True):
    if backend:
        missing = [name for name in ('fastapi', 'uvicorn', 'pydantic', 'httpx', 'sqlalchemy', 'psycopg', 'dotenv')
                   if importlib.util.find_spec(name) is None]
        if missing:
            python = r'.\.venv\Scripts\python.exe' if os.name == 'nt' else './.venv/bin/python'
            raise RuntimeError('Missing Python dependencies: ' + ', '.join(missing) + '\n'
                'From the repository root, install and run checks in the same environment:\n'
                'python -m venv .venv\n' + python + ' -m pip install -r "data tools/requirements.txt"\n' +
                python + ' scripts/checks.py')
    if frontend and not (ROOT / 'frontend/node_modules').is_dir():
        raise RuntimeError('Frontend dependencies are missing. Install Node.js 22 and run:\n'
                           'npm --prefix frontend ci')


def check_secrets():
    staged = subprocess.check_output(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM", "-z"], cwd=ROOT).decode().split("\0")
    if not any(staged):
        staged = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    patterns = (rb"gsk_[A-Za-z0-9]{20,}", rb"sk-or-v1-[A-Za-z0-9_-]{20,}", rb"sk-[A-Za-z0-9_-]{24,}", rb"AGE-SECRET-KEY-[A-Z0-9]{40,}", rb"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")
    for name in filter(None, staged):
        if Path(name).name == ".env" or name.endswith((".identity", ".key")):
            raise RuntimeError(f"Private configuration cannot be committed: {name}")
        content = subprocess.check_output(["git", "show", ":" + name], cwd=ROOT)
        if name.endswith(".age"):
            if not content.startswith(b"age-encryption.org/v1\n"):
                raise RuntimeError(f"Expected binary age ciphertext: {name}")
        elif any(re.search(pattern, content) for pattern in patterns):
            raise RuntimeError(f"Possible plaintext credential: {name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    args = parser.parse_args()
    check_dependencies(backend=not args.frontend_only, frontend=not args.backend_only)
    check_secrets()
    env = {**os.environ, "OFFLINE_MODE": "1", "DATABASE_URL": "sqlite:///:memory:",
           "OPENROUTER_API_KEY": "", "GROQ_API_KEY": "", "PYTHONUTF8": "1"}
    if not args.frontend_only:
        subprocess.run([sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=ROOT / "data tools", env=env, check=True)
        subprocess.run([sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", "scripts/tests", "-q"], cwd=ROOT, env=env, check=True)
    if not args.backend_only:
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if not npm:
            raise RuntimeError("Install Node.js 22 and run npm ci in frontend first.")
        for command in ([npm, "test"], [npm, "run", "lint"], [npm, "run", "build"]):
            subprocess.run(command, cwd=ROOT / "frontend", env=env, check=True)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
