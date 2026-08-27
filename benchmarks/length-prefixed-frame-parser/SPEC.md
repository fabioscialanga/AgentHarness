# Length-prefixed frame parser

Implement:

`python -m frame_parser.parse --chunks CHUNKS_JSON --max-frame N --output FRAMES_JSON`

`CHUNKS_JSON` is either the literal JSON text or `@PATH`, which reads that exact UTF-8 JSON text from a caller-supplied file; the file carrier exists because valid inputs can exceed operating-system argv limits. The JSON value is a strict RFC 8259 array of lowercase even-length hexadecimal strings whose decoded total is at most 2 MiB. Duplicate keys, non-array roots, uppercase/odd/nonhex chunks, `NaN`, and infinities are rejected. `N` is a canonical decimal integer in `0..1048576`.

The decoded stream is zero or more frames. Each frame is a four-byte unsigned big-endian length followed by exactly that many payload bytes. A zero-length payload is valid. Prefix and payload bytes may cross arbitrary chunk boundaries. EOF with a partial prefix or payload is invalid. A declared length greater than `N` is rejected immediately after its fourth prefix byte, before payload buffering or EOF classification.

On success, atomically replace `FRAMES_JSON` with one canonical UTF-8 JSON array plus LF. Elements are lowercase payload hex in stream order. Canonical JSON uses no insignificant whitespace. On every rejection, emit exactly one LF-terminated stderr line `frame_error:<code>`, no stdout or traceback, and preserve an existing output byte-for-byte or leave an absent output absent. Codes are `invalid_input`, `oversize`, `truncated`, and `output_error` (atomic replacement could not be completed).

The parser is streaming: retained parser state is at most four prefix bytes, one payload bounded by `N`, and temporary output state. It must not concatenate the full decoded input before parsing.
