# UAF: parsekit normalize with ../ in path

parsekit 1.2.0

```
==5150==ERROR: AddressSanitizer: heap-use-after-free on address 0x5030000013a at pc 0xc621de49f145 bp 0xfda9988c79fc sp 0x35526f7eaed4
READ of size 1 at 0x50300000004a thread T0
    #0 0x6725a2a7b860 in pk_url_normalize /home/dev/parsekit-1.2.0/src/url.c:241:17
    #1 0xdcd6c8a1f8b4 in cmd_url /home/dev/parsekit-1.2.0/cli/parsekit.c:73:10
    #2 0x6287cced9041 in main /home/dev/parsekit-1.2.0/cli/parsekit.c:153:12

SUMMARY: AddressSanitizer: heap-use-after-free /home/dev/parsekit-1.2.0/src/url.c:241:17 in pk_url_normalize
```

```sh
parsekit normalize 'http://example.com/a/./b/../c'
```
