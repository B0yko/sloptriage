# UAF in pk_url_normalize via pk_percent_decode

```
==61==ERROR: AddressSanitizer: heap-use-after-free on address 0x503000000044
READ of size 1 at 0x503000000044 thread T0
    #0 0xf71010b93b7d in pk_url_normalize /src/parsekit/src/url.c:133:7
    #1 0x946bf54074e3 in pk_percent_decode /src/parsekit/src/util.c:55:3
    #2 0x248c801bef75 in cmd_url /src/parsekit/cli/parsekit.c:73:10
```

`pk_percent_decode()` frees the path and `pk_url_normalize()` uses it afterwards.
