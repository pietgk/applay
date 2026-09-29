import subprocess
import sys
import unittest


class PackageImportTests(unittest.TestCase):
    def test_apply_imports_from_project_environment(self):
        result = subprocess.run(
            [sys.executable, "-c", "import apply; print(apply.__file__)"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("src/apply/__init__.py", result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
