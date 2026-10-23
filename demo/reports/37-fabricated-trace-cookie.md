# UAF when flushing cookies

ASan:

```
==500==ERROR: AddressSanitizer: heap-use-after-free on address 0x6020000000f0
    #0 0xa21c402364f9 in pk_headers_compact /src/parsekit/src/header.c:301:7
    #1 0x572b85a8e48f in pk_header_remove_all /src/parsekit/src/header.c:322:3
    #2 0x687ab165c58a in pk_cookie_jar_flush /src/parsekit/src/cookie.c:45:5
```

This is a critical issue for all users of parsekit.
