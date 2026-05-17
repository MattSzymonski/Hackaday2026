#!/usr/bin/env python3

# I've now realized mpremote does everything this script does and more, so it should
# probably be deleted.

import argparse
import binascii
import hashlib
import os
import pathlib
import subprocess
import sys
import time
from typing import Iterable

# Always run relative to the firmware/ directory (parent of scripts/)
os.chdir(pathlib.Path(__file__).resolve().parent.parent)

MPREMOTE = [sys.executable, "-m", "mpremote"]
MPREMOTE_DELAY = 1.5   # seconds between mpremote calls to let badge recover
MPREMOTE_RETRIES = 5  # number of times to retry the first connection


def mpremote(*args, **kwargs):
    """Run an mpremote command with a short delay before to let the badge recover."""
    time.sleep(MPREMOTE_DELAY)
    return subprocess.run(MPREMOTE + list(args), **kwargs)


def check_path(path: str, ) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    top_path = pathlib.Path(path)
    for file_path in top_path.iterdir():
        if file_path.is_file():
            with open(file_path, "rb") as file:
                hasher = hashlib.sha256(file.read())
                files[file_path.as_posix()] = hasher.digest()
        else:
            if file_path.name in ["__pycache__", ".git"]:
                continue
            files.update(check_path(str(file_path)))
            files[file_path.as_posix()] = b""
    return files

def check_dir(path: str) -> dict[str, str]:
    files_uncleaned = check_path(path)
    files = {fn.replace(path.strip() + "/", "/").replace("\\", "/"): binascii.hexlify(hash).decode() for fn, hash in files_uncleaned.items()}
    return files

def sort_paths_recursively(paths: Iterable[str]) -> list[str]:
    """Return paths sorted depth-first so parents appear before children."""
    return sorted(paths, key=lambda name: (name.count("/"), name))

def format_recursive_path(name: str) -> str:
    """Indent nested entries to make the hierarchy clearer."""
    depth = max(name.count("/") - 1, 0)
    return f"{'  ' * depth}{name}"

def get_badge_files() -> dict[str, str]:
    """Get the files on the badge and their checksums."""
    for attempt in range(MPREMOTE_RETRIES):
        result = mpremote("run", "./scripts/check_filesystem.py", capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            break
        print(f"Badge not ready, retrying ({attempt + 1}/{MPREMOTE_RETRIES})...")
        time.sleep(2.0)
    else:
        print("ERROR: Could not connect to badge after retries. Is it plugged in and not held by another program?")
        sys.exit(1)
    badge_files_text = result.stdout
    badge_files = {}
    skipped = 0
    for line in badge_files_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Expected format: "/path/to/file b'hexhash'" or "/path/to/dir b''"
        space_idx = line.rfind(" ")  # use rfind so paths with spaces still work
        if space_idx == -1:
            skipped += 1
            continue
        name = line[:space_idx]
        checksum_raw = line[space_idx + 1:].strip()
        # Strip b' prefix and ' suffix: b'abcd' -> abcd
        if checksum_raw.startswith("b'") and checksum_raw.endswith("'"):
            checksum = checksum_raw[2:-1]
        else:
            checksum = checksum_raw
        badge_files[name] = checksum
    if args.verbose and skipped:
        print(f"  (skipped {skipped} unrecognised lines from badge output)")
    return badge_files

if __name__ == "__main__":
    parser = argparse.ArgumentParser("Badge Updater")
    parser.add_argument("action", type=str, nargs="?", default="ls", help="Action to perform: 'ls' to list files (default), 'push' to push files, 'pull' to pull files.")
    parser.add_argument("--reset", action="store_true", default=False, help="Reset the badge after.")
    parser.add_argument("--verbose", "-v", action="store_true", default=False)
    args = parser.parse_args()
    if args.action not in ("ls", "list", "push", "pull"):
        print(f"Unknown action '{args.action}'. Use 'ls', 'push', or 'pull'.")
        exit(1)

    if args.action == "push":
        print("Checking badge/ directory...")
        local_files = check_dir("badge")
        print("Checking files on badge...")
        badge_files = get_badge_files()
        for name in sorted(local_files.keys()):
            hash = local_files[name]
            if name not in badge_files and hash == "":
                print(f"Creating directory {name}...")
                mpremote("mkdir", name, check=True)
            elif name not in badge_files or badge_files[name] != hash:
                if name not in badge_files:
                    print(f"Creating {name}...")
                else:
                    print(f"Updating {name}...")
                mpremote("cp", f"badge{name}", f":{name}", check=True)
            else:
                if args.verbose:
                    print(f"{name} is up to date.")
        files_to_delete = set(badge_files.keys()) - set(local_files.keys())
        for name in sorted(files_to_delete, reverse=True):
            if name.startswith("/data"):  # Don't delete the data/ directory.
                continue
            if "__pycache__" in name:  # Don't delete cache files
                continue
            if badge_files[name] == "":
                # Can't use rmdir because __pycache__ will linger
                print(f"Removing directory {name} from badge...")
                mpremote("rm", "-r", name, check=True)
            else:
                print(f"Deleting {name} from badge...")
                mpremote("rm", name, check=True)

    if args.action == "pull":
        print("Pulling files from badge...")
        badge_files = get_badge_files()
        if not os.path.exists("badge-backup"):
            os.makedirs("badge-backup")
        file_text = mpremote("cp", "-r", ":", "badge-backup/", check=True)
        # for name in badge_files.keys():
        #     print(f"Pulling {name}...")
        #     with open(f"badge-backup/{name}", "w") as file:
        #         file.write(file_text)
        print("Files pulled successfully.")

    if args.action in ("ls", "list"):
        local_files = check_dir("badge")
        badge_files = get_badge_files()
        print("Files on badge:")
        print("Status values: * different, + only on local (push will add), - only on badge (push will delete)")
        print(f"Status {'Filename':<40s} SHA256")
        all_files = set(local_files.keys()).union(set(badge_files.keys()))
        for name in sort_paths_recursively(all_files):
            if name in local_files and name in badge_files:
                if local_files[name] == badge_files[name]:
                    status = " "
                else:
                    status = "*"
            elif name in badge_files:
                status = "-"
            elif name in local_files:
                status = "+"
            else:
                status = "?"
            hash = badge_files[name] if name in badge_files else local_files[name]
            if hash == "":
                hash = "directory"
            print(f"{status}      {format_recursive_path(name):<40s} {hash}")

    if args.reset:
        print("Resetting badge...")
        mpremote("reset", check=True)
