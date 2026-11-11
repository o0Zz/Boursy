from pathlib import Path

DEV_VERSION = "0.0.0-dev"


def _read_version() -> str:
    """The Docker build writes the computed version to /app/VERSION; a dev checkout has none."""
    try:
        version = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return DEV_VERSION
    return version or DEV_VERSION


__version__ = _read_version()
