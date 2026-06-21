#!/usr/bin/env python3
"""Upload G-code to OctoPrint, optionally selecting and starting it."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib import request
from urllib.error import HTTPError


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Upload G-code to OctoPrint.")
    p.add_argument("gcode", type=Path)
    p.add_argument("--env", type=Path, default=Path(".env"))
    p.add_argument("--select", action="store_true")
    p.add_argument("--print", action="store_true", dest="start_print")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    env = parse_env(args.env)
    url = os.environ.get("OCTOPRINT_URL", env.get("OCTOPRINT_URL", "")).rstrip("/")
    key = os.environ.get("OCTOPRINT_API_KEY", env.get("OCTOPRINT_API_KEY", ""))
    if not url or not key:
        raise SystemExit("OCTOPRINT_URL and OCTOPRINT_API_KEY are required.")
    if not args.gcode.exists():
        raise SystemExit(f"Missing G-code file: {args.gcode}")

    boundary = "----fluidicsboundary"
    fields = {
        "select": "true" if args.select or args.start_print else "false",
        "print": "true" if args.start_print else "false",
    }
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(f"{value}\r\n".encode())
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="file"; filename="{args.gcode.name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
    )
    body.extend(args.gcode.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode())

    req = request.Request(
        f"{url}/api/files/local",
        data=bytes(body),
        headers={
            "X-Api-Key": key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            print(resp.read().decode("utf-8", "replace"))
    except HTTPError as exc:
        print(exc.read().decode("utf-8", "replace"))
        raise


if __name__ == "__main__":
    main()
