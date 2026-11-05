import unittest
from unittest.mock import patch
from scripts import checks


class DependencyHelpTests(unittest.TestCase):
    def test_missing_python_packages_explain_installation_in_same_environment(self):
        with patch.object(checks.importlib.util, 'find_spec', return_value=None):
            with self.assertRaises(RuntimeError) as raised:
                checks.check_dependencies(frontend=False)
        message = str(raised.exception)
        self.assertIn('sqlalchemy', message)
        self.assertIn('httpx', message)
        self.assertIn('python -m venv .venv', message)
        self.assertIn('-m pip install -r "data tools/requirements.txt"', message)
        self.assertIn('scripts/checks.py', message)

    def test_backend_only_does_not_require_frontend_installation(self):
        with patch.object(checks.importlib.util, 'find_spec', return_value=object()), \
                patch.object(checks.Path, 'is_dir', return_value=False):
            checks.check_dependencies(frontend=False)

    def test_frontend_only_does_not_require_python_packages(self):
        with patch.object(checks.importlib.util, 'find_spec', side_effect=AssertionError('Backend not requested')), \
                patch.object(checks.Path, 'is_dir', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'npm --prefix frontend ci'):
                checks.check_dependencies(backend=False)
