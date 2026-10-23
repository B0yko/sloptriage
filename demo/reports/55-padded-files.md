# Memory corruption across the parser

Files involved: `src/url.c`, `src/header.c`, `src/buf.c`, `src/util.c`, `src/query.c`,
`cli/parsekit.c`, `include/parsekit.h`, and the new `src/http_parser.c` and `src/chunked.c`.
Functions: `pk_url_parse()`, `pk_query_parse()`, `pk_header_parse()`, `pk_chunk_decode()` and
`pk_http_read_body()`.
