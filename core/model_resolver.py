"""Dynamic model and path resolver for the Vosk Raspberry Pi Voice Controller.

Automatically discovers the Vosk speech model across any project location or
operating system, eliminating the need for hardcoded paths.
"""

import os
from pathlib import Path
from typing import Optional


def get_project_root() -> Path:
    """Return the absolute path to the repository root directory."""
    # This file is in <root>/core/model_resolver.py -> parents[1] is <root>
    return Path(__file__).resolve().parents[1]


def get_audio_dir(custom_path: Optional[str] = None) -> Path:
    """Resolve the path to the sample audio directory."""
    if custom_path:
        p = Path(custom_path).expanduser().resolve()
        if p.exists():
            return p

    project_audio = get_project_root() / "audio"
    if project_audio.exists():
        return project_audio

    return project_audio


def is_valid_vosk_model(path: Path) -> bool:
    """Check whether a directory contains necessary Vosk model files."""
    if not path.is_dir():
        return False
    # A standard Vosk model contains at least one of these indicator folders/files
    indicators = [
        path / "am",
        path / "conf" / "model.conf",
        path / "conf" / "mfcc.conf",
        path / "model.conf",
        path / "graph",
    ]
    return any(p.exists() for p in indicators)


def resolve_model_path(custom_path: Optional[str] = None) -> str:
    """Dynamically find and return the path to a valid Vosk model directory.

    Search priority:
    1. Explicit custom path passed as parameter or CLI flag.
    2. VOSK_MODEL_PATH environment variable.
    3. Project repository root (any folder named `vosk-model*` or `*model*`).
    4. Parent directories (up to 2 levels above project root).
    5. Standard Raspberry Pi & user home paths (~/vosk-model*, ~/model, etc.).
    6. System shared locations (/usr/local/share/vosk-models, /opt/vosk, etc.).

    Returns:
        str: Absolute path to the detected model directory.

    Raises:
        FileNotFoundError: If no valid Vosk model directory can be located.
    """
    searched_locations: list[str] = []

    # 1. Custom path explicitly supplied
    if custom_path:
        p = Path(custom_path).expanduser().resolve()
        searched_locations.append(f"CLI / Argument: {p}")
        if is_valid_vosk_model(p):
            return str(p)

    # 2. Environment variable
    env_path = os.environ.get("VOSK_MODEL_PATH")
    if env_path:
        p = Path(env_path).expanduser().resolve()
        searched_locations.append(f"VOSK_MODEL_PATH env: {p}")
        if is_valid_vosk_model(p):
            return str(p)

    # 3. Dynamic search in repository root
    root = get_project_root()
    searched_locations.append(f"Repository root: {root}")

    # Direct match for standard folder name
    standard_name = root / "vosk-model-small-en-us-0.15"
    if is_valid_vosk_model(standard_name):
        return str(standard_name)

    # Glob search in repo root for any vosk-model folder
    for candidate in sorted(root.glob("vosk-model*")):
        if is_valid_vosk_model(candidate):
            return str(candidate.resolve())

    for candidate in sorted(root.glob("*model*")):
        if is_valid_vosk_model(candidate):
            return str(candidate.resolve())

    # 4. Search in parent directory (in case repo is nested or model is shared)
    parent = root.parent
    searched_locations.append(f"Parent directory: {parent}")
    for candidate in sorted(parent.glob("vosk-model*")):
        if is_valid_vosk_model(candidate):
            return str(candidate.resolve())

    # 5. Search user home directory (common on Raspberry Pi: /home/pi/...)
    home = Path.home()
    searched_locations.append(f"User home directory: {home}")
    home_candidates = [
        home / "vosk-model-small-en-us-0.15",
        home / "vosk-model",
        home / "model",
        home / "Vosk_Project" / "vosk-model-small-en-us-0.15",
        home / ".cache" / "vosk" / "vosk-model-small-en-us-0.15",
    ]
    for candidate in home_candidates:
        if is_valid_vosk_model(candidate):
            return str(candidate.resolve())

    # 6. Linux system-wide paths
    system_candidates = [
        Path("/usr/local/share/vosk-models/vosk-model-small-en-us-0.15"),
        Path("/usr/share/vosk-models/vosk-model-small-en-us-0.15"),
        Path("/opt/vosk/vosk-model-small-en-us-0.15"),
    ]
    for candidate in system_candidates:
        searched_locations.append(f"System path: {candidate}")
        if is_valid_vosk_model(candidate):
            return str(candidate.resolve())

    # Model not found: provide clear error message
    nl = "\n  - "
    raise FileNotFoundError(
        f"Could not automatically locate a valid Vosk model directory.\n"
        f"Searched locations:{nl}{nl.join(searched_locations)}\n\n"
        f"To fix this, you can:\n"
        f"  1. Ensure the 'vosk-model-small-en-us-0.15' directory is in the project root: {root}\n"
        f"  2. Or set the VOSK_MODEL_PATH environment variable: export VOSK_MODEL_PATH=/path/to/model\n"
        f"  3. Or pass the --model flag when running the script: --model /path/to/model\n"
    )
