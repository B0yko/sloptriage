# Request smuggling in src/http_parser.c

parsekit's `src/http_parser.c` accepts both Content-Length and Transfer-Encoding, see
`src/http_parser.c:212`. The chunk parser in `src/chunked.c` also trusts the size line.
