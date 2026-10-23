# Stack overflow when resolving relative URLs

```
==19==ERROR: AddressSanitizer: stack-buffer-overflow on address 0x7ffc1a2b
READ of size 4 at 0x7ffc1a2b thread T0
    #0 0xa3ce9d97dcbe in pk_url_resolve_relative /src/parsekit/src/url.c:402:11
    #1 0xe500fe7ee5fc in pk_url_join_base /src/parsekit/src/url.c:451:8
    #2 0x324bdb2e1142 in cmd_url /src/parsekit/cli/parsekit.c:66:3

SUMMARY: AddressSanitizer: stack-buffer-overflow /src/parsekit/src/url.c:402:11
```
