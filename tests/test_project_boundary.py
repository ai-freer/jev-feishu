"""Guard the independent app boundary without touching installed applications."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectBoundaryTests(unittest.TestCase):
    def test_source_has_no_wechat_dependencies_or_embedded_credentials(self):
        forbidden = (
            "com.tencent.xinWeChat",
            "WECHAT_APP_NAMES",
            "/Applications/jev-jarvis.app",
            ".config/jev-jarvis",
        )
        for path in (ROOT / "src").rglob("*.py"):
            with self.subTest(file=path.name):
                source = path.read_text()
                for value in forbidden:
                    self.assertNotIn(value, source)
                self.assertIsNone(re.search(r"sk-[A-Za-z0-9_-]{16,}", source))
                self.assertIsNone(re.search(
                    r"(?i)(?:api_key|access_token|secret)\s*=\s*['\"][^'\"]+['\"]",
                    source,
                ))

    def test_project_mit_license_retains_upstream_notice(self):
        license_text = (ROOT / "LICENSE").read_text()
        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026 ai-freer", license_text)
        self.assertIn("Copyright (c) 2026 eatmoreduck", license_text)
        self.assertIn("Permission is hereby granted, free of charge", license_text)
        self.assertIn("THE SOFTWARE IS PROVIDED", license_text)

    def test_package_import_is_inert(self):
        import importlib.util
        import tomllib
        spec = importlib.util.spec_from_file_location(
            "jev_feishu", ROOT / "src/jev_feishu/__init__.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(module.__version__, project["project"]["version"])


if __name__ == "__main__":
    unittest.main()
