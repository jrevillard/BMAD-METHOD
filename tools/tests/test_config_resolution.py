"""Priority and isolation tests for the four-layer TOML merge."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "bmad" / "scripts"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip().replace("\\n", "\n"), encoding="utf-8")


class GlobalUserConfigDirTests(unittest.TestCase):
    """``global_user_config_dir`` honors ``BMAD_CONFIG_HOME`` and falls back to ``~/.bmad/config``."""

    def setUp(self) -> None:
        sys.path.insert(0, str(SCRIPTS_DIR))
        for key in ("BMAD_CONFIG_HOME", "HOME"):
            self._orig_env = getattr(self, "_orig_env", {})
            self._orig_env[key] = os.environ.get(key)

    def tearDown(self) -> None:
        sys.path[:] = [p for p in sys.path if p != str(SCRIPTS_DIR)]
        for key, value in self._orig_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for mod in ("config_utils",):
            sys.modules.pop(mod, None)

    def test_default_path(self) -> None:
        os.environ.pop("BMAD_CONFIG_HOME", None)
        os.environ["HOME"] = "/tmp/fake-home"
        import config_utils

        self.assertEqual(config_utils.global_user_config_dir(), Path("/tmp/fake-home/.bmad/config"))

    def test_bmad_config_home_override(self) -> None:
        os.environ["BMAD_CONFIG_HOME"] = "/tmp/isolated-bmad-home"
        import config_utils

        self.assertEqual(config_utils.global_user_config_dir(), Path("/tmp/isolated-bmad-home"))


class CentralConfigPriorityTests(unittest.TestCase):
    """``load_central_config`` merges project default < global user < project team < project user."""

    def setUp(self) -> None:
        sys.path.insert(0, str(SCRIPTS_DIR))
        for key in ("BMAD_CONFIG_HOME",):
            self._orig_env = getattr(self, "_orig_env", {})
            self._orig_env[key] = os.environ.get(key)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name) / "project"
        self.project_root.mkdir()

    def tearDown(self) -> None:
        for key, value in self._orig_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        sys.path[:] = [p for p in sys.path if p != str(SCRIPTS_DIR)]
        for mod in ("config_utils",):
            sys.modules.pop(mod, None)

    def _import(self):
        sys.modules.pop("config_utils", None)
        import config_utils  # noqa: PLC0415

        return config_utils

    def test_global_user_overrides_installer_default(self) -> None:
        """Global user layer must beat installer-shipped defaults."""
        os.environ["BMAD_CONFIG_HOME"] = str(Path(self._tmp.name) / "global")
        bmad = self.project_root / "_bmad"
        _write(bmad / "config.toml", '[installer]\nuser_name = "InstallerDefault"\n')
        config_utils = self._import()
        result = config_utils.load_central_config(self.project_root)
        self.assertEqual(result["installer"]["user_name"], "InstallerDefault")

        _write(Path(os.environ["BMAD_CONFIG_HOME"]) / "config.user.toml", '[installer]\nuser_name = "GlobalAlice"\n')
        config_utils = self._import()
        result = config_utils.load_central_config(self.project_root)
        self.assertEqual(result["installer"]["user_name"], "GlobalAlice")

    def test_project_user_overrides_global(self) -> None:
        """Project-side user layer must beat the global user layer."""
        os.environ["BMAD_CONFIG_HOME"] = str(Path(self._tmp.name) / "global")
        bmad = self.project_root / "_bmad"
        _write(bmad / "config.toml", '[installer]\nuser_name = "InstallerDefault"\n')
        _write(bmad / "custom" / "config.toml", '[installer]\nuser_name = "TeamBob"\n')
        _write(bmad / "custom" / "config.user.toml", '[installer]\nuser_name = "ProjectAlice"\n')
        _write(Path(os.environ["BMAD_CONFIG_HOME"]) / "config.user.toml", '[installer]\nuser_name = "GlobalEve"\n')
        config_utils = self._import()
        result = config_utils.load_central_config(self.project_root)
        self.assertEqual(result["installer"]["user_name"], "ProjectAlice")

    def test_team_overrides_global(self) -> None:
        """Project-side team config must beat the global user layer."""
        os.environ["BMAD_CONFIG_HOME"] = str(Path(self._tmp.name) / "global")
        bmad = self.project_root / "_bmad"
        _write(bmad / "config.toml", '[installer]\nuser_name = "InstallerDefault"\n')
        _write(bmad / "custom" / "config.toml", '[installer]\nuser_name = "TeamBob"\n')
        _write(Path(os.environ["BMAD_CONFIG_HOME"]) / "config.user.toml", '[installer]\nuser_name = "GlobalEve"\n')
        config_utils = self._import()
        result = config_utils.load_central_config(self.project_root)
        self.assertEqual(result["installer"]["user_name"], "TeamBob")

    def test_missing_global_dir_is_silent(self) -> None:
        """No global dir present must not raise — backward-compatible."""
        os.environ["BMAD_CONFIG_HOME"] = str(Path(self._tmp.name) / "absent")
        bmad = self.project_root / "_bmad"
        _write(bmad / "config.toml", '[installer]\nuser_name = "InstallerDefault"\n')
        config_utils = self._import()
        result = config_utils.load_central_config(self.project_root)
        self.assertEqual(result["installer"]["user_name"], "InstallerDefault")


class CustomizationPriorityTests(unittest.TestCase):
    """``load_customization`` merges skill default < global user < project team < project user."""

    def setUp(self) -> None:
        sys.path.insert(0, str(SCRIPTS_DIR))
        for key in ("BMAD_CONFIG_HOME",):
            self._orig_env = getattr(self, "_orig_env", {})
            self._orig_env[key] = os.environ.get(key)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name) / "project"
        self.project_root.mkdir()
        self.skill_dir = Path(self._tmp.name) / "skills" / "bmad-agent-analyst"
        self.skill_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        for key, value in self._orig_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        sys.path[:] = [p for p in sys.path if p != str(SCRIPTS_DIR)]
        for mod in ("config_utils",):
            sys.modules.pop(mod, None)

    def _import(self):
        sys.modules.pop("config_utils", None)
        import config_utils  # noqa: PLC0415

        return config_utils

    def test_global_user_overrides_skill_default(self) -> None:
        """Global user skill customization must beat the skill's default customize.toml."""
        os.environ["BMAD_CONFIG_HOME"] = str(Path(self._tmp.name) / "global")
        _write(self.skill_dir / "customize.toml", '[agent]\nicon = "📊"\n')
        _write(Path(os.environ["BMAD_CONFIG_HOME"]) / "bmad-agent-analyst.user.toml", '[agent]\nicon = "🌐"\n')
        config_utils = self._import()
        result = config_utils.load_customization(self.project_root, self.skill_dir)
        self.assertEqual(result["agent"]["icon"], "🌐")

    def test_project_user_overrides_global_user(self) -> None:
        """Project user customization must beat the global user layer."""
        os.environ["BMAD_CONFIG_HOME"] = str(Path(self._tmp.name) / "global")
        _write(self.skill_dir / "customize.toml", '[agent]\nicon = "📊"\n')
        _write(self.project_root / "_bmad" / "custom" / "bmad-agent-analyst.user.toml", '[agent]\nicon = "🏠"\n')
        _write(Path(os.environ["BMAD_CONFIG_HOME"]) / "bmad-agent-analyst.user.toml", '[agent]\nicon = "🌐"\n')
        config_utils = self._import()
        result = config_utils.load_customization(self.project_root, self.skill_dir)
        self.assertEqual(result["agent"]["icon"], "🏠")


class ResolveScriptSmokeTests(unittest.TestCase):
    """End-to-end CLI invocations return valid JSON after the layer insertion."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._orig_home = os.environ.get("BMAD_CONFIG_HOME")
        os.environ["BMAD_CONFIG_HOME"] = str(Path(self._tmp.name) / "global")
        self.project_root = Path(self._tmp.name) / "project"
        self.project_root.mkdir()
        bmad = self.project_root / "_bmad"
        _write(bmad / "config.toml", '[installer]\nuser_name = "Default"\n')

    def tearDown(self) -> None:
        if self._orig_home is None:
            os.environ.pop("BMAD_CONFIG_HOME", None)
        else:
            os.environ["BMAD_CONFIG_HOME"] = self._orig_home

    def test_resolve_config_json(self) -> None:
        out = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "resolve_config.py"), "--project-root", str(self.project_root)],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(out.stdout)
        self.assertEqual(payload["installer"]["user_name"], "Default")

    def test_resolve_config_picks_up_global(self) -> None:
        _write(Path(os.environ["BMAD_CONFIG_HOME"]) / "config.user.toml", '[installer]\nuser_name = "GlobalAlice"\n')
        out = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "resolve_config.py"), "--project-root", str(self.project_root)],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(out.stdout)
        self.assertEqual(payload["installer"]["user_name"], "GlobalAlice")


if __name__ == "__main__":
    unittest.main()