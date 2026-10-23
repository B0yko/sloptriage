# Crash in pk_header_unfold

Backtrace from my fuzzer (parsekit 1.2.0):

```
    #0 0x0110c5751306 in pk_buf_append /src/parsekit/src/buf.c:30:5
    #1 0x4d6d59291f0c in pk_header_unfold /src/parsekit/src/header.c:150:9
    #2 0xde2e5738713a in parse_line /src/parsekit/src/header.c:77:12
```
