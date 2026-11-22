"""JSON client for a running PromptAtelier Style Lab backend (run from repo root)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import requests

ACTIVE = {"queued", "running", "cancelling"}


def server_url(explicit: str | None) -> str:
    url = explicit or os.environ.get("PROMPTATELIER_URL")
    if not url:
        try:
            state = json.loads(Path("runtime/dev_web.json").read_text(encoding="utf-8-sig"))
            port = int(state["backend_port"])
        except (OSError, ValueError, TypeError, KeyError):
            port = 53211
        url = f"http://127.0.0.1:{port}"
    url = url.rstrip("/")
    base = url if url.endswith("/api/style-lab") else url.removesuffix("/api") + "/api/style-lab"
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("--server must be an HTTP(S) backend URL without query or fragment")
    return base


class ApiError(ValueError):
    def __init__(self, status: int, payload: Any):
        self.status = status
        self.payload = payload
        super().__init__(f"HTTP {status}: {json.dumps(payload, ensure_ascii=False)}")


class Client:
    def __init__(self, server: str | None = None):
        self.url = server_url(server)
        self.session = requests.Session()
        self.session.trust_env = False

    def request(self, method: str, path: str, *, body: Any = None, timeout: float = 30) -> dict:
        parsed = urlsplit(path)
        if (
            not path.startswith("/")
            or path.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or ".." in parsed.path.split("/")
        ):
            raise ValueError("Use a path relative to /api/style-lab, for example /workspaces")
        try:
            response = self.session.request(method, self.url + path, json=body, timeout=timeout)
        except requests.RequestException as exc:
            raise ValueError(
                f"Request to {self.url} failed ({type(exc).__name__}); check the backend URL. "
                "If this was a write, read existing runs before retrying."
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(
                f"HTTP {response.status_code}: non-JSON response; check the backend port/URL"
            ) from exc
        if not response.ok:
            raise ApiError(response.status_code, payload)
        if not isinstance(payload, dict):
            raise TypeError("Expected a JSON object from Style Lab")
        return payload

    def wait(self, workspace: str, run_id: str, timeout: float = 45, *, plan: bool = False) -> dict:
        deadline = time.monotonic() + timeout
        collection = "test-plans" if plan else "runs"
        path = f"/workspaces/{quote(workspace, safe='')}/{collection}/{quote(run_id, safe='')}"
        while True:
            remaining = deadline - time.monotonic()
            result = self.request("GET", path, timeout=max(0.01, min(30, remaining)))
            if (result if plan else result["run"])["status"] not in ACTIVE:
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {**result, "wait_timed_out": True}
            time.sleep(min(2, remaining))
            if time.monotonic() >= deadline:
                return {**result, "wait_timed_out": True}

    def materials(self) -> dict:
        shelf = self.request("GET", "/shelf")
        resolved = []
        for material in shelf.get("materials", []):
            query = urlencode({"ref": material["ref"], "role": material["role"]})
            node = self.request("GET", f"/library/node?{query}")
            excluded = set(material.get("excluded", []))
            tags = list(
                dict.fromkeys(
                    tag
                    for section in node.get("sections", [])
                    for tag in section["tags"]
                    if tag not in excluded
                )
            )
            resolved.append({**material, "sections": node.get("sections", []), "tags": tags})
        return {"shelf": shelf, "materials": resolved}


def bounded_timeout(value: str) -> float:
    number = float(value)
    if not 0 < number <= 55:
        raise argparse.ArgumentTypeError("timeout must be greater than 0 and at most 55 seconds")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", help="Backend URL; defaults to this project's dev_web.json")
    commands = parser.add_subparsers(dest="command", required=True)
    api = commands.add_parser("api", help="Send one Style Lab API request")
    api.add_argument("method", choices=["GET", "POST", "PUT", "DELETE"])
    api.add_argument("path", help="Relative to /api/style-lab, including optional query string")
    api.add_argument("--body-file", type=Path, help="UTF-8 JSON request body")
    wait = commands.add_parser("wait", help="Wait for an existing run; never submits generation")
    wait.add_argument("workspace")
    wait.add_argument("run_id")
    wait.add_argument("--timeout", type=bounded_timeout, default=45)
    prepare = commands.add_parser(
        "prepare", help="Save groups/recipes only; never generates images"
    )
    prepare.add_argument("workspace")
    prepare.add_argument(
        "--body-file", type=Path, required=True, help="Preparation JSON with a stable id"
    )
    start = commands.add_parser("start-plan", help="Explicitly start an existing test plan")
    start.add_argument("workspace")
    start.add_argument("plan_id")
    wait_plan = commands.add_parser(
        "wait-plan", help="Wait for an existing test plan without resubmitting"
    )
    wait_plan.add_argument("workspace")
    wait_plan.add_argument("plan_id")
    wait_plan.add_argument("--timeout", type=bounded_timeout, default=45)
    commands.add_parser("materials", help="Read selected shelf materials with exclusions applied")
    for command in commands.choices.values():
        command.add_argument(
            "--output", type=Path, help="Save the full JSON response to a UTF-8 file"
        )
    args = parser.parse_args(argv)
    try:
        client = Client(args.server)
        with client.session:
            if args.command == "api":
                body = None
                if args.body_file:
                    body = json.loads(args.body_file.read_text(encoding="utf-8-sig"))
                result = client.request(args.method, args.path, body=body)
            elif args.command == "wait":
                result = client.wait(args.workspace, args.run_id, args.timeout)
            elif args.command == "wait-plan":
                result = client.wait(args.workspace, args.plan_id, args.timeout, plan=True)
            elif args.command == "prepare":
                body = json.loads(args.body_file.read_text(encoding="utf-8-sig"))
                if not isinstance(body, dict) or not body.get("id"):
                    raise ValueError(
                        "Preparation requires a stable id to safely resume the same request"
                    )
                result = client.request(
                    "POST", f"/workspaces/{quote(args.workspace, safe='')}/preparations", body=body
                )
            elif args.command == "start-plan":
                result = client.request(
                    "POST",
                    f"/workspaces/{quote(args.workspace, safe='')}/test-plans/{quote(args.plan_id, safe='')}/start",
                    body={},
                )
            else:
                result = client.materials()
        encoded = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded + "\n", encoding="utf-8")
            print(json.dumps({"output": str(args.output.resolve())}, ensure_ascii=False))
        else:
            print(encoded)
        return 0
    except (TypeError, ValueError, OSError, KeyError) as exc:
        error = {"error": str(exc)}
        if isinstance(exc, ApiError):
            error = {"http_status": exc.status, "response": exc.payload}
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
