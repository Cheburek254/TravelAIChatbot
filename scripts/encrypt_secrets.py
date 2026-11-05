"""Encrypt an env file for a recipient with the official age CLI."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def encrypt(source, output, recipient, executable=None):
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError("Input and encrypted output must be different files.")
    raw = source.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Save the env file as UTF-8 without BOM.")
    for line in raw.decode("utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("Each setting must have NAME=value format.")
        name, value = line.split("=", 1)
        if name != name.strip() or value != value.strip() or (value and value[0] in "\"'"):
            raise ValueError("Use NAME=value without surrounding spaces or quotes.")
    age = executable or shutil.which("age")
    if not age:
        bundled = ROOT / ".venv/tools/age/age.exe"
        age = str(bundled) if bundled.exists() else None
    if not age:
        raise RuntimeError("Install age from https://github.com/FiloSottile/age/releases or pass --age PATH.")
    # -o preserves the binary ciphertext on Windows PowerShell as well.
    subprocess.run([age, "-r", recipient, "-o", str(output), str(source)], check=True)
    if not output.read_bytes().startswith(b"age-encryption.org/v1\n"):
        raise RuntimeError("Unexpected age output; expected the binary v1 file format.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / ".env")
    parser.add_argument("--output", type=Path, default=ROOT / "secrets.env.age")
    parser.add_argument("--recipient", required=True, help="Public age recipient key")
    parser.add_argument("--age")
    args = parser.parse_args()
    encrypt(args.input, args.output, args.recipient, args.age)
    print("Encrypted configuration created:", args.output.name)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
