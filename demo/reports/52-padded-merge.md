# Heap overflow in header folding (pk_header_unfold -> pk_header_merge_continuation)

## Details

parsekit 1.2.0 parses headers in `pk_header_parse()` (src/header.c:89), which calls
`parse_line()` (src/header.c:57) and `pk_header_unfold()` (src/header.c:30). Values are
appended with `pk_buf_append()` in src/buf.c and duplicated with `pk_strndup()` in src/util.c.
`pk_header_get()` and `pk_header_count()` then read them back.

The overflow is in `pk_header_merge_continuation()`, which calls `pk_buf_grow_exact()` with a length
computed by `pk_header_measure()`.
