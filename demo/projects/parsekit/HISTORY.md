# parsekit release history (demo project)

- 1.0.0 – URL parsing, header parsing with obs-fold unfolding, percent decoding, CLI.
  String helpers live in `src/strutil.c`; `pk_header_concat()` joins repeated headers.
- 1.1.0 – `src/strutil.c` renamed to `src/util.c`; `pk_header_concat()` renamed to
  `pk_header_join()`, which now allocates one byte too few for repeated headers
  (heap-buffer-overflow, write of size 1); query-string parsing (`src/query.c`).
- 1.2.0 – URL normalisation removes dot segments; `pk_url_normalize()` reads a pointer into the
  path after freeing it (heap-use-after-free, read of size 1).

Versions 1.3.0 and 2.0.0 do not exist.
