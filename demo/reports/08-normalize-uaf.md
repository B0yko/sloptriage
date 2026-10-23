# Use after free in pk_url_normalize() for paths with dot segments

## Summary

parsekit 1.2.0 reads freed memory in `pk_url_normalize()` when the URL path contains
`.` or `..` segments. The function keeps `base`, a pointer into `u->path`, frees
`u->path` at `src/url.c:239` and then dereferences `base` at line 241.

The code in `src/url.c`:

```c
    char *clean = remove_dot_segments(u->path);
    const char *base;
    if(!clean)
      return PK_ERR_NOMEM;
    base = strrchr(u->path, '/');
    free(u->path);
    u->path = clean;
    if(base && base[1] == '\0')
      u->flags |= PK_URL_TRAILING_SLASH;
```

## AddressSanitizer

```
==977==ERROR: AddressSanitizer: heap-use-after-free on address 0x5030000033a at pc 0x0ac2f8670282 bp 0x4c1c099724ca sp 0xf4941d407201
READ of size 1 at 0x50300000004a thread T0
    #0 0x4b3ce107f80e in pk_url_normalize /home/dev/parsekit-1.2.0/src/url.c:241:17
    #1 0x222f828767ef in cmd_url /home/dev/parsekit-1.2.0/cli/parsekit.c:73:10
    #2 0xc2f91624a894 in main /home/dev/parsekit-1.2.0/cli/parsekit.c:153:12
    #3 0x0f1f836f99ee in __libc_start_main csu/../csu/libc-start.c:392:3

0x50300000004a is located 10 bytes inside of 21-byte region [0x503000000040,0x503000000055)
freed by thread T0 here:
    #0 0xe3692f09e2e8 in free ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:52
    #1 0xc662248b483b in pk_url_normalize /home/dev/parsekit-1.2.0/src/url.c:239:5
    #2 0x7ffc050fec94 in cmd_url /home/dev/parsekit-1.2.0/cli/parsekit.c:73:10

previously allocated by thread T0 here:
    #0 0xdbca3a0aac36 in malloc ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:69
    #1 0x098b2cc2bd81 in pk_strndup /home/dev/parsekit-1.2.0/src/util.c:14:15
    #2 0x8319478da6bd in pk_url_parse /home/dev/parsekit-1.2.0/src/url.c:155:13

SUMMARY: AddressSanitizer: heap-use-after-free /home/dev/parsekit-1.2.0/src/url.c:241:17 in pk_url_normalize
```

## Reproduction

```sh
parsekit normalize 'http://example.com/a/./b/../c'
```
