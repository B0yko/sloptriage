# Heap overflow in header joining (ASan confirmed)

parsekit 1.2.0. AddressSanitizer output:

```
==4410==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x502000000035
WRITE of size 1 at 0x502000000035 thread T0
    #0 0xc5831be38cb8 in pk_header_join /src/parsekit/src/header.c:38:12
    #1 0xcb4ba2e75198 in parse_line /src/parsekit/src/header.c:128:9
    #2 0x9a01749ddb14 in pk_header_parse /src/parsekit/src/header.c:60:10

SUMMARY: AddressSanitizer: heap-buffer-overflow /src/parsekit/src/header.c:38
```

The overflow happens because `pk_header_join()` trusts `value_len`.
