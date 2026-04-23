from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class ReleaseSmokeTests(unittest.TestCase):
    def test_build_and_install_release_artifacts(self) -> None:
        if os.getenv("OFFERQUEST_RUN_RELEASE_SMOKE") != "1":
            self.skipTest(
                "Set OFFERQUEST_RUN_RELEASE_SMOKE=1 after installing `.[release,web]` to run the release smoke workflow."
            )

        root = Path(__file__).resolve().parents[1]
        build_script = root / "scripts" / "build-release.sh"
        smoke_script = root / "scripts" / "smoke-test-install.sh"
        if not build_script.exists() or not smoke_script.exists():
            self.fail("Release scripts are missing.")
        if shutil.which("bash") is None:
            self.skipTest("bash is required for the release smoke workflow.")

        with tempfile.TemporaryDirectory() as tmpdir:
            dist_dir = Path(tmpdir) / "dist"
            subprocess.run(
                ["bash", str(build_script), str(dist_dir)],
                cwd=root,
                check=True,
            )
            self.assertTrue(list(dist_dir.glob("offerquest-*.whl")))
            self.assertTrue(list(dist_dir.glob("offerquest-*.tar.gz")))

            subprocess.run(
                ["bash", str(smoke_script), str(dist_dir)],
                cwd=root,
                check=True,
            )


if __name__ == "__main__":
    unittest.main()
