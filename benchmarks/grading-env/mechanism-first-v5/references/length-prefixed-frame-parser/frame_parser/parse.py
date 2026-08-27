from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

MUTANT = os.environ.get("AGENTHARNESS_MUTANT", "")
HEX = re.compile(r"(?:[0-9a-f]{2})*")
MAX_TOTAL = 2 * 1024 * 1024


class FrameError(Exception):
    def __init__(self, code: str):
        self.code = code


def load_chunks(text: str) -> list[str]:
    try:
        value = json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except Exception as exc:
        raise FrameError("invalid_input") from exc
    if not isinstance(value, list):
        raise FrameError("invalid_input")
    result: list[str] = []
    total = 0
    for item in value:
        if not isinstance(item, str) or not HEX.fullmatch(item):
            raise FrameError("invalid_input")
        total += len(item) // 2
        if total > MAX_TOTAL:
            raise FrameError("invalid_input")
        result.append(item)
    return result


def parse_normal(chunks: list[str], maximum: int) -> list[bytes]:
    frames: list[bytes] = []
    prefix = bytearray()
    payload = bytearray()
    expected: int | None = None
    oversize = False
    terminated = False
    for encoded_chunk in chunks:
        if MUTANT == "frame_split_prefix_near_miss" and prefix and encoded_chunk:
            raise FrameError("truncated")
        decoded_position = 0
        while decoded_position < len(encoded_chunk):
            chunk = bytes.fromhex(encoded_chunk[decoded_position:decoded_position + 8192])
            decoded_position += len(chunk) * 2
            position = 0
            while position < len(chunk):
                if terminated:
                    position = len(chunk)
                    continue
                if expected is None:
                    take = min(4 - len(prefix), len(chunk) - position)
                    prefix.extend(chunk[position:position + take]); position += take
                    if len(prefix) < 4:
                        continue
                    expected = int.from_bytes(prefix, "little" if MUTANT == "frame_endianness" else "big", signed=False); prefix.clear()
                    if expected > maximum:
                        if MUTANT == "frame_max_before_alloc": oversize = True
                        else: raise FrameError("oversize")
                    if expected == 0:
                        frames.append(b""); expected = None
                        if MUTANT == "frame_zero_and_multiple": terminated = True
                else:
                    take = min(expected - len(payload), len(chunk) - position)
                    payload.extend(chunk[position:position + take]); position += take
                    if len(payload) == expected:
                        if oversize: raise FrameError("oversize")
                        frames.append(bytes(payload)); payload.clear(); expected = None
    if expected is not None or prefix:
        if MUTANT == "frame_truncated_eof":
            return frames
        raise FrameError("truncated")
    return frames


def parse_chunks(chunks: list[str], maximum: int) -> list[bytes]:
    if MUTANT != "frame_split_prefix_payload":
        return parse_normal(chunks, maximum)
    frames: list[bytes] = []
    for chunk in chunks:
        frames.extend(parse_normal([chunk], maximum))
    return frames


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks", required=True)
    parser.add_argument("--max-frame", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"0|[1-9][0-9]*", args.max_frame):
            raise FrameError("invalid_input")
        maximum = int(args.max_frame)
        if maximum > 1048576:
            raise FrameError("invalid_input")
        source = args.chunks
        if source.startswith("@"):
            try:
                source = Path(source[1:]).read_text(encoding="utf-8")
            except Exception as exc:
                raise FrameError("invalid_input") from exc
        chunks = load_chunks(source)
        frames = parse_chunks(chunks, maximum)
        output = (json.dumps([frame.hex() for frame in frames], separators=(",", ":")) + "\n").encode()
        atomic_write(args.output, output)
        return 0
    except FrameError as exc:
        sys.stderr.write(f"frame_error:{exc.code}\n")
        return 2
    except OSError:
        sys.stderr.write("frame_error:output_error\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
