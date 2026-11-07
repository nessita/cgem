"""Keep development CSS current without a separate watcher process."""

import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.utils.autoreload import autoreload_started, file_changed

SOURCE_DIRS = ("gemcore/templates",)
SOURCE_FILES = (
    "gem/forms.py",
    "gemcore/forms.py",
)
SOURCE_SUFFIXES = {".html", ".css", ".js", ".py"}
BUILD_OUTPUT = "gemcore/static/css/styles.css"


def run_build():
    base_dir = settings.BASE_DIR
    command = [
        str(base_dir / "tailwindcss"),
        "-o",
        str(base_dir / BUILD_OUTPUT),
        "--minify",
    ]
    try:
        subprocess.run(command, cwd=base_dir, check=True)
    except OSError as exc:
        sys.stderr.write(
            f"[assets] unable to run {command[0]!r}: {exc}. "
            "See the Tailwind setup in README.md.\n"
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"[assets] build failed: {exc}\n")
    else:
        sys.stdout.write(f"[assets] rebuilt {BUILD_OUTPUT}\n")


def watch_sources(sender, **kwargs):
    base_dir = settings.BASE_DIR
    for directory in SOURCE_DIRS:
        sender.watch_dir(base_dir / directory, "**/*")
    for filename in SOURCE_FILES:
        source = base_dir / filename
        sender.watch_dir(source.parent, source.name)
    run_build()


def rebuild_on_change(sender, file_path, **kwargs):
    base_dir = settings.BASE_DIR
    file_path = Path(file_path).resolve()
    if file_path == base_dir / BUILD_OUTPUT:
        return True
    if file_path.suffix not in SOURCE_SUFFIXES:
        return None
    source_files = {base_dir / filename for filename in SOURCE_FILES}
    in_source_dir = any(
        file_path.is_relative_to(base_dir / directory)
        for directory in SOURCE_DIRS
    )
    if file_path not in source_files and not in_source_dir:
        return None
    # Python changes need a server restart; startup then rebuilds the CSS.
    if file_path.suffix == ".py":
        return None
    run_build()
    return True


def connect():
    autoreload_started.connect(
        watch_sources, dispatch_uid="gemcore_assets_watch_sources"
    )
    file_changed.connect(
        rebuild_on_change, dispatch_uid="gemcore_assets_rebuild"
    )
