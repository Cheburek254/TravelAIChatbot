import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("encrypt_secrets", ROOT / "scripts/encrypt_secrets.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EncryptionTests(unittest.TestCase):
    def test_plaintext_bom_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / ".env"
            source.write_bytes(b"\xef\xbb\xbfKEY=test\n")
            with self.assertRaises(ValueError):
                module.encrypt(source, Path(folder) / "secrets.env.age", "unused-recipient")

    def test_real_age_round_trip_without_committing_identity(self):
        age = shutil.which("age") or str(ROOT / ".venv/tools/age/age.exe")
        if not Path(age).exists():
            self.skipTest("Install the official age CLI for the encryption round-trip test.")
        keygen = str(Path(age).with_name("age-keygen.exe" if age.endswith(".exe") else "age-keygen"))
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            identity = folder / "test.identity"
            subprocess.run([keygen, "-o", str(identity)], check=True, capture_output=True)
            public = next(line.split(": ", 1)[1] for line in identity.read_text().splitlines() if line.startswith("# public key:"))
            source = folder / ".env"
            source.write_text("OPENROUTER_API_KEY=unit-test-token\n", encoding="utf-8")
            ciphertext = folder / "secrets.env.age"
            module.encrypt(source, ciphertext, public, age)
            self.assertNotIn(b"unit-test-token", ciphertext.read_bytes())
            output = folder / "decrypted.env"
            subprocess.run([age, "-d", "-i", str(identity), "-o", str(output), str(ciphertext)], check=True, capture_output=True)
            self.assertEqual(output.read_bytes(), source.read_bytes())
