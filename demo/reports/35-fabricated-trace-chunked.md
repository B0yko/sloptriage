# Heap-buffer-overflow in chunked body decoding

parsekit 1.2.0 crashes when decoding a chunked body:

```
==7781==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x60c000000140
WRITE of size 8 at 0x60c000000140 thread T0
    #0 0xcbe54014c2b5 in pk_chunk_decode /src/parsekit/src/chunked.c:88:14
    #1 0x4b95523cf694 in pk_http_read_body /src/parsekit/src/http_body.c:214:9
    #2 0x1fa1c257c6f5 in pk_session_feed /src/parsekit/src/session.c:57:5
    #3 0x61c5cb347611 in main /src/parsekit/cli/parsekit.c:131:10

SUMMARY: AddressSanitizer: heap-buffer-overflow /src/parsekit/src/chunked.c:88:14 in pk_chunk_decode
```

```sh
parsekit url 'https://example.com/index.html?q=1'
```
