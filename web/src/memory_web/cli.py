"""Command-line entry: `memory-web` starts the local server."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from threading import Timer

import uvicorn

from .app import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="memory-web", description="Local web browser for using-memory")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    parser.add_argument("--config", default=None, help="Path to using-memory config.yaml (defaults to env / ~/.skills/using-memory/config.yaml)")
    parser.add_argument("--open", action="store_true", help="Open browser tab after start")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev)")
    args = parser.parse_args(argv)

    app = create_app(config_path=args.config)

    if args.open:
        url = f"http://{args.host}:{args.port}"
        Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
