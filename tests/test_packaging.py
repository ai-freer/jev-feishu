import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class PackagingTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("rustc"), "requires macOS build tools")
    def test_build_survives_finder_metadata_reappearing_in_output_directory(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp).resolve()
            project = folder / "project"
            packaging = project / "packaging"
            packaging.mkdir(parents=True)
            shutil.copyfile(root / "packaging/build_app.sh", packaging / "build_app.sh")
            (packaging / "launcher.rs").write_text("fn main() {}\n")
            (project / "src/jev_feishu").mkdir(parents=True)
            (project / "src/jev_feishu/__init__.py").write_text("")
            (project / ".venv/lib/python3.12/site-packages").mkdir(parents=True)
            runtime = folder / "runtime"
            (runtime / "bin").mkdir(parents=True)
            (runtime / "lib").mkdir()
            python = runtime / "bin/python3.12"
            # This fixture exercises signing, so even the runtime stub is Mach-O.
            shutil.copyfile(shutil.which("true"), python)
            python.chmod(0o755)
            commands = folder / "commands"
            commands.mkdir()
            uv = commands / "uv"
            uv_calls = folder / "uv-calls.jsonl"
            uv.write_text(f"#!{sys.executable}\nimport json, sys\n"
                          f"with open({str(uv_calls)!r}, 'a') as stream:\n"
                          "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                          f"if sys.argv[1] == 'run': print({str(runtime)!r})\n")
            uv.chmod(0o755)
            output = project / "dist/Jev 飞书助手.app"
            for name in ("rsync", "xattr"):
                command = commands / name
                command.write_text(
                    f"#!{sys.executable}\n"
                    "import subprocess, sys\nfrom pathlib import Path\n"
                    f"subprocess.run([{shutil.which(name)!r}, *sys.argv[1:]], check=True)\n"
                    f"output = Path({str(output)!r})\n"
                    "destination = Path(sys.argv[-1]).resolve()\n"
                    "if output.exists() and (destination == output or output in destination.parents):\n"
                    f"    subprocess.run([{shutil.which('xattr')!r}, '-wx', 'com.apple.FinderInfo', "
                    "(b'APPL????' + bytes(24)).hex(), str(output)], check=True)\n")
                command.chmod(0o755)
            environment = {**os.environ, "PATH": str(commands) + os.pathsep + os.environ["PATH"],
                           "JEV_FEISHU_SIGN_IDENTITY": "-"}
            result = subprocess.run(["bash", str(packaging / "build_app.sh")], cwd=project,
                                    env=environment, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in uv_calls.read_text().splitlines()]
            self.assertEqual(calls, [
                ["sync", "--python", "3.12", "--no-dev", "--quiet"],
                ["run", "--python", "3.12", "python", "-c",
                 "import sys; print(sys.base_prefix)"],
            ])
            attributes = subprocess.run([shutil.which("xattr"), str(output)], check=True,
                                        capture_output=True, text=True, timeout=5).stdout.splitlines()
            self.assertIn("com.apple.FinderInfo", attributes, "simulate reattached metadata")
            self.assertTrue((output / "Contents/MacOS/JevFeishu").is_file())
            clean_copy = folder / "install-preview/Jev 飞书助手.app"
            clean_copy.parent.mkdir()
            subprocess.run([shutil.which("rsync"), "-a", str(output) + "/", str(clean_copy) + "/"],
                           check=True, capture_output=True, timeout=15)
            subprocess.run(["codesign", "--verify", "--deep", "--strict", str(clean_copy)],
                           check=True, capture_output=True, timeout=15)

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("rustc"), "requires macOS build tools")
    def test_launcher_imports_without_writing_into_signed_bundle(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            contents = Path(tmp) / "Contents"
            binary = contents / "MacOS" / "JevFeishu"
            binary.parent.mkdir(parents=True)
            library = contents / "lib"
            library.mkdir()
            runtime = Path(sys.base_prefix)
            shutil.copyfile(runtime / "lib/libpython3.12.dylib", library / "libpython3.12.dylib")
            stdlib = library / "python3.12"
            shutil.copytree(runtime / "lib/python3.12", stdlib,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "site-packages"))
            site = stdlib / "site-packages"
            site.mkdir()
            marker = Path(tmp) / "import-complete"
            (site / "sitecustomize.py").write_text(
                "import encodings.idna, stringprep, os\n"
                f"open({str(marker)!r}, 'w').close()\n"
                "os._exit(0)\n")
            environment = dict(os.environ)
            environment.pop("PYTHONDONTWRITEBYTECODE", None)
            sdk = Path("/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk")
            if not sdk.is_dir():
                sdk = Path("/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk")
            environment["SDKROOT"] = str(sdk)
            subprocess.run(["rustc", "--edition", "2021", "-C", "linker=rust-lld",
                            str(root / "packaging/launcher.rs"), "-o", str(binary)],
                           env=environment, check=True, capture_output=True, timeout=30)
            result = subprocess.run([str(binary)], env=environment, capture_output=True,
                                    stdin=subprocess.DEVNULL, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(marker.exists(), "bundled Python must actually import the modules")
            self.assertEqual(list(contents.rglob("*.pyc")), [], "imports must preserve the signed resources")
