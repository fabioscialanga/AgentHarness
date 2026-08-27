# Streaming CSV quoted records

Implement:

`python -m csv_stream.parse --chunks CHUNKS_JSON --max-field-bytes N --output ROWS_JSON`

`CHUNKS_JSON` is either literal strict RFC 8259 JSON or `@PATH`, where PATH contains those exact UTF-8 JSON bytes. Its value is an array of lowercase, even-length hexadecimal byte chunks with decoded total at most 2 MiB. `N` is a canonical decimal integer in `0..1048576`.

The decoded byte stream is UTF-8 CSV with comma separators and CRLF record endings. Every record, including the final record, ends in CRLF. The first record is exactly `id,name,value`, in that order, with no duplicate, missing, extra, quoted, or reordered header names. It is not emitted as data.

Fields may be unquoted or quoted. A quoted field starts with `"`; inside it, comma and CRLF are data and `""` decodes to one quote. After its closing quote, only comma or CR is valid. Quotes in unquoted fields, bare CR, bare LF, invalid UTF-8, EOF without a complete CRLF record, EOF inside a quote, or EOF after bare CR are invalid. Every data row has exactly three fields; trailing empty fields are retained.

`max-field-bytes` bounds each decoded field's UTF-8 byte length, including headers. A doubled quote counts as one decoded byte. Reject immediately when appending the byte that would exceed the bound, before waiting for quote closure or EOF.

On success atomically replace `ROWS_JSON` with canonical UTF-8 JSON plus LF: an array of objects with exactly `id`, `name`, and `value`. Canonical JSON sorts keys and uses no insignificant whitespace. On rejection emit exactly one LF-terminated stderr line `csv_error:<code>`, no stdout or traceback, and preserve an existing output byte-for-byte or leave an absent output absent. Codes: `invalid_input`, `header`, `row_width`, `field_limit`, `strict_eof`, `output_error`.

The parser is streaming: retain only CSV state, one field bounded by N, the current row, and temporary output state. Do not concatenate the decoded input before parsing.
