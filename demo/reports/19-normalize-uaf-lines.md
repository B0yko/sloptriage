# pk_url_normalize: stale pointer after free

parsekit 1.2.0

File: src/url.c

Function: pk_url_normalize (lines 225-256)

Lines 238, 239 and 241: `base` is taken from the old path, the old path is
freed, then `base[1]` is read.

```sh
parsekit normalize 'http://example.com/a/./b/../c'
```
