"""Run the local workbench and API on one loopback origin."""

import argparse
from pathlib import Path

from fastapi.staticfiles import StaticFiles
import uvicorn

from xagent.api import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default=".local/xagent.sqlite3")
    args = parser.parse_args()
    app = create_app(args.db)
    web = Path(__file__).resolve().parents[1] / "web"
    if web.is_dir():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
