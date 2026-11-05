#!/usr/bin/env python3
"""Send a prompt to a locally running NeonByte agent and print the reply (stdlib only).

    python local/ask.py "Best noise cancelling earbuds under $300?"
    python local/ask.py --url http://127.0.0.1:8091 --user user003 "Compare the Nimbus X12 and Pixelon 9a"

Handles both the orchestrator's streamed (text/event-stream) replies and the
sub-agents' JSON replies. Keeps one session id per run so follow-ups have context.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
import uuid


def ask(url: str, prompt: str, user: str, session: str) -> None:
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise SystemExit(f"--url must be an http(s) URL, got {url!r}")
    body = json.dumps({"prompt": prompt, "userId": user, "sessionId": session}).encode()
    req = urllib.request.Request(f"{url.rstrip('/')}/invocations", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:  # nosec B310 - scheme restricted to http(s) above
        if "text/event-stream" in resp.headers.get("Content-Type", ""):
            for raw in resp:
                line = raw.decode().strip()
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    try:
                        chunk = json.loads(chunk)
                    except ValueError:
                        pass
                    print(chunk if isinstance(chunk, str) else json.dumps(chunk), end="", flush=True)
            print()
        else:
            data = json.loads(resp.read() or b'""')
            print(data if isinstance(data, str) else json.dumps(data, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("prompt", nargs="*", help="prompt; omit for an interactive chat")
    p.add_argument("--url", default="http://127.0.0.1:8090", help="agent base URL (orchestrator default)")
    p.add_argument("--user", default="user001", help="shopper id (user001-user010 have addresses on file)")
    args = p.parse_args()
    session = f"local-{uuid.uuid4().hex}"
    if args.prompt:
        ask(args.url, " ".join(args.prompt), args.user, session)
        return
    print(f"Chatting with {args.url} as {args.user} (Ctrl-D to quit)")
    for line in sys.stdin if not sys.stdin.isatty() else iter(lambda: input("you> "), None):
        if line.strip():
            ask(args.url, line.strip(), args.user, session)


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print()
