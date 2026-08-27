from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import BinaryIO, NoReturn

MUTANT = os.environ.get("AGENTHARNESS_MUTANT", "")
MAX_TOTAL = 2 * 1024 * 1024
HEX = re.compile(r"(?:[0-9a-f]{2})*")
HEADER = ["id", "name", "value"]


class CsvError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class StrictArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CsvError("invalid_input")


def load_chunks(text: str) -> list[str]:
    try:
        value = json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except Exception as exc:
        raise CsvError("invalid_input") from exc
    if not isinstance(value, list):
        raise CsvError("invalid_input")
    total = 0
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or len(item) % 2 or any(character not in "0123456789abcdef" for character in item):
            raise CsvError("invalid_input")
        total += len(item) // 2
        if total > MAX_TOTAL:
            raise CsvError("invalid_input")
        result.append(item)
    return result


class JsonArraySink:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        self.temporary = Path(temporary)
        self.handle: BinaryIO = os.fdopen(descriptor, "wb")
        self.first = True
        self.handle.write(b"[")

    def emit(self, value: dict[str, str]) -> None:
        if not self.first:
            self.handle.write(b",")
        self.first = False
        self.handle.write(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

    def commit(self) -> None:
        self.handle.write(b"]\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.handle.close()
        os.replace(self.temporary, self.path)

    def abort(self) -> None:
        try:
            self.handle.close()
        except Exception:
            pass
        try:
            self.temporary.unlink()
        except FileNotFoundError:
            pass


class Parser:
    def __init__(self, maximum: int, sink: JsonArraySink):
        self.maximum = maximum
        self.sink = sink
        self.field = bytearray()
        self.row: list[str] = []
        self.row_quoted: list[bool] = []
        self.in_quotes = False
        self.after_quote = False
        self.pending_cr = False
        self.at_field_start = True
        self.field_quoted = False
        self.completed_records = 0

    def append(self, byte: int, quoted: bool) -> None:
        self.field.append(byte)
        if len(self.field) > self.maximum and not (MUTANT == "csv_field_limit" and quoted):
            raise CsvError("field_limit")

    def finish_field(self) -> None:
        if len(self.field) > self.maximum:
            raise CsvError("field_limit")
        try:
            value = bytes(self.field).decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise CsvError("invalid_input") from exc
        self.row.append(value)
        self.row_quoted.append(self.field_quoted)
        self.field.clear()
        self.at_field_start = True
        self.field_quoted = False
        self.after_quote = False

    def finish_record(self) -> None:
        self.finish_field()
        if self.completed_records == 0:
            exact = self.row == HEADER and not any(self.row_quoted)
            if MUTANT == "csv_header_exact":
                exact = set(self.row) == set(HEADER) and len(self.row) == len(HEADER)
            if not exact:
                raise CsvError("header")
        else:
            values = list(self.row)
            if MUTANT == "csv_row_width":
                while values and values[-1] == "":
                    values.pop()
                if len(values) > len(HEADER):
                    raise CsvError("row_width")
                self.sink.emit(dict(zip(HEADER, values)))
            else:
                if len(values) != len(HEADER):
                    raise CsvError("row_width")
                self.sink.emit(dict(zip(HEADER, values, strict=True)))
        self.row.clear()
        self.row_quoted.clear()
        self.completed_records += 1

    def feed_byte(self, byte: int) -> None:
        if self.pending_cr:
            if byte != 0x0A:
                raise CsvError("strict_eof")
            self.pending_cr = False
            self.finish_record()
            return
        if self.in_quotes:
            if self.after_quote:
                if byte == 0x22:
                    self.append(0x22, True)
                    self.after_quote = False
                    return
                self.in_quotes = False
                if byte == 0x2C:
                    self.finish_field()
                    return
                if byte == 0x0D:
                    self.pending_cr = True
                    return
                raise CsvError("invalid_input")
            if byte == 0x22:
                self.after_quote = True
            else:
                self.append(byte, True)
            return
        if self.at_field_start and byte == 0x22:
            self.in_quotes = True
            self.field_quoted = True
            self.at_field_start = False
            return
        if byte == 0x22:
            raise CsvError("invalid_input")
        if byte == 0x2C:
            self.finish_field()
        elif byte == 0x0D:
            self.pending_cr = True
        elif byte == 0x0A:
            raise CsvError("invalid_input")
        else:
            self.at_field_start = False
            self.append(byte, False)

    def finish(self) -> None:
        if MUTANT == "csv_strict_eof" and self.in_quotes:
            self.in_quotes = False
            self.after_quote = False
            self.finish_record()
            return
        if self.pending_cr or self.in_quotes or self.after_quote or self.field or self.row or not self.at_field_start:
            raise CsvError("strict_eof")
        if self.completed_records == 0:
            raise CsvError("header")


def feed_chunks(chunks: list[str], maximum: int, sink: JsonArraySink) -> None:
    parser = Parser(maximum, sink)
    for encoded in chunks:
        first = True
        position = 0
        while position < len(encoded):
            block = bytes.fromhex(encoded[position:position + 8192])
            position += len(block) * 2
            for byte in block:
                if MUTANT == "csv_quoted_escape_near_miss" and first and parser.in_quotes and parser.after_quote and byte == 0x22:
                    raise CsvError("invalid_input")
                first = False
                parser.feed_byte(byte)
    parser.finish()


def parse_chunks(chunks: list[str], maximum: int, sink: JsonArraySink) -> None:
    if MUTANT != "csv_quoted_chunk_state":
        feed_chunks(chunks, maximum, sink)
        return
    for chunk in chunks:
        feed_chunks([chunk], maximum, sink)


def main(argv: list[str] | None = None) -> int:
    parser = StrictArgumentParser(add_help=False)
    parser.add_argument("--chunks", required=True)
    parser.add_argument("--max-field-bytes", required=True)
    parser.add_argument("--output", required=True)
    sink: JsonArraySink | None = None
    try:
        args = parser.parse_args(argv)
        if re.fullmatch(r"0|[1-9][0-9]*", args.max_field_bytes) is None:
            raise CsvError("invalid_input")
        maximum = int(args.max_field_bytes)
        if maximum > 1048576:
            raise CsvError("invalid_input")
        source = args.chunks
        if source.startswith("@"):
            try:
                source = Path(source[1:]).read_text(encoding="utf-8")
            except Exception as exc:
                raise CsvError("invalid_input") from exc
        chunks = load_chunks(source)
        sink = JsonArraySink(Path(args.output))
        parse_chunks(chunks, maximum, sink)
        sink.commit()
        return 0
    except CsvError as exc:
        if sink is not None:
            sink.abort()
        sys.stderr.write(f"csv_error:{exc.code}\n")
        return 2
    except OSError:
        if sink is not None:
            sink.abort()
        sys.stderr.write("csv_error:output_error\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
