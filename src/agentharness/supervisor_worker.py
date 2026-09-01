from __future__ import annotations

import argparse
import json
import os
import sys

from .supervisor import SupervisorError, run_job_worker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agentharness.supervisor_worker")
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--start-fd", type=int)
    args = parser.parse_args(argv)
    try:
        if args.start_fd is not None:
            try:
                if os.read(args.start_fd, 1) != b"1":
                    raise SupervisorError("worker start gate closed before launch")
            finally:
                os.close(args.start_fd)
        result = run_job_worker(args.config, args.run_id)
    except (SupervisorError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("status") == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
