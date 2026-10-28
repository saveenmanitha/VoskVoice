#!/usr/bin/env python3
"""Release Packaging Script for Offline Voice-Controlled Light & Appliance System.

Generates clean distribution ZIP archives in the `dist/` directory:
1. `vosk-voice-server-v1.0.0.zip`   - Raspberry Pi server scripts & core modules
2. `vosk-web-client-v1.0.0.zip`     - Web client server, static assets & launchers
3. `vosk-project-v1.0.0-full.zip`   - Complete unified project release

Usage:
    python scripts/package_release.py
"""

import os
import shutil
import zipfile
from pathlib import Path

VERSION = "1.0.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"

# Files and directories to always exclude from releases
EXCLUDE_NAMES = {
    ".git",
    ".github",
    ".vscode",
    ".idea",
    "__pycache__",
    "dist",
    "build",
    ".DS_Store",
    "Thumbs.db",
    "vosk-model-small-en-us-0.15",  # Exclude heavy 40MB+ model from zip (downloaded separately)
}

EXCLUDE_EXTENSIONS = {".pyc", ".pyo", ".pyd", ".log"}


def should_exclude(path: Path) -> bool:
    for part in path.parts:
        if part in EXCLUDE_NAMES:
            return True
    if path.suffix in EXCLUDE_EXTENSIONS:
        return True
    return False


def create_zip_from_list(output_zip: Path, file_mapping: list[tuple[Path, str]]) -> None:
    """Creates a zip archive from a list of (source_path, arcname_relative)."""
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    if output_zip.exists():
        output_zip.unlink()

    print(f"[*] Creating archive: {output_zip.name} ...")
    count = 0
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arcname in file_mapping:
            if src.is_file():
                zf.write(src, arcname)
                count += 1
            elif src.is_dir():
                for root, _, files in os.walk(src):
                    for f in files:
                        p = Path(root) / f
                        if not should_exclude(p):
                            rel = p.relative_to(src)
                            target_arc = f"{arcname}/{rel}".replace("\\", "/")
                            zf.write(p, target_arc)
                            count += 1
    size_mb = output_zip.stat().st_size / (1024 * 1024)
    print(f"   [+] Done! {count} files packaged ({size_mb:.2f} MB)")


def package_voice_server():
    """Package Raspberry Pi backend."""
    zip_path = DIST_DIR / f"vosk-voice-server-v{VERSION}.zip"
    mapping = [
        (PROJECT_ROOT / "servers", "servers"),
        (PROJECT_ROOT / "core", "core"),
        (PROJECT_ROOT / "audio", "audio"),
        (PROJECT_ROOT / "tests" / "test_voice_commands.py", "tests/test_voice_commands.py"),
        (PROJECT_ROOT / "tests" / "__init__.py", "tests/__init__.py"),
        (PROJECT_ROOT / "start_voice_server.sh", "start_voice_server.sh"),
        (PROJECT_ROOT / "requirements.txt", "requirements.txt"),
        (PROJECT_ROOT / "README.md", "README.md"),
        (PROJECT_ROOT / "CHANGELOG.md", "CHANGELOG.md"),
        (PROJECT_ROOT / "RELEASE_NOTES_v1.0.0.md", "RELEASE_NOTES.md"),
    ]
    create_zip_from_list(zip_path, mapping)


def package_web_client():
    """Package Web Client implementation."""
    zip_path = DIST_DIR / f"vosk-web-client-v{VERSION}.zip"
    mapping = [
        (PROJECT_ROOT / "clients", "clients"),
        (PROJECT_ROOT / "certs", "certs"),
        (PROJECT_ROOT / "tests" / "test_web_server.py", "tests/test_web_server.py"),
        (PROJECT_ROOT / "tests" / "__init__.py", "tests/__init__.py"),
        (PROJECT_ROOT / "start_web_client.bat", "start_web_client.bat"),
        (PROJECT_ROOT / "start_web_client.sh", "start_web_client.sh"),
        (PROJECT_ROOT / "requirements.txt", "requirements.txt"),
        (PROJECT_ROOT / "README.md", "README.md"),
        (PROJECT_ROOT / "CHANGELOG.md", "CHANGELOG.md"),
        (PROJECT_ROOT / "RELEASE_NOTES_v1.0.0.md", "RELEASE_NOTES.md"),
    ]
    create_zip_from_list(zip_path, mapping)


def package_full_project():
    """Package complete repository excluding caches and heavy model binary."""
    zip_path = DIST_DIR / f"vosk-project-v{VERSION}-full.zip"
    mapping = []
    for item in PROJECT_ROOT.iterdir():
        if should_exclude(item):
            continue
        mapping.append((item, item.name))
    create_zip_from_list(zip_path, mapping)


def main():
    print(f"==================================================")
    print(f" Building Release Packages for Vosk Project v{VERSION}")
    print(f"==================================================")
    package_voice_server()
    package_web_client()
    package_full_project()
    print("\nAll release packages created successfully in `dist/`!")


if __name__ == "__main__":
    main()
