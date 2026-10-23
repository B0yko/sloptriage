# Heap buffer overflow in pk_header_join() with repeated headers

## Summary

parsekit 1.2.0 writes one byte past the end of a heap buffer when a header block
contains the same header name twice. `pk_header_join()` in `src/header.c` sizes the
output as the sum of the values plus two bytes per separator, but forgets the
terminating NUL, which it writes at `src/header.c:175`.

The vulnerable code in `src/header.c`:

```c
  total += (n - 1) * 2;
  out = malloc(total);
  if(!out)
    return NULL;
```

## Sanitizer output

```
==4121==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x50200000063 at pc 0x272d1371c171 bp 0x49d439536b32 sp 0x16fdaeeb9757
WRITE of size 1 at 0x50200000020 thread T0
    #0 0x9fae923d5a4f in pk_header_join /src/parsekit/src/header.c:175:12
    #1 0xd12aabfe228f in cmd_header /src/parsekit/cli/parsekit.c:109:13
    #2 0x219e9cb0eb53 in main /src/parsekit/cli/parsekit.c:168:10
    #3 0xf16947ccf25e in __libc_start_call_main csu/../sysdeps/nptl/libc_start_call_main.h:58:16
    #4 0xc84d8dbc7425 in __libc_start_main csu/../csu/libc-start.c:392:3
    #5 0xa4c123b1612d in _start (/src/parsekit/build/parsekit+0x2c364)

0x502000000035 is located 0 bytes after 5-byte region [0x502000000030,0x502000000035)
allocated by thread T0 here:
    #0 0x4770f58904db in malloc ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:145
    #1 0xa41ecccc3fc1 in pk_header_join /src/parsekit/src/header.c:161:9
    #2 0x626e53a13043 in cmd_header /src/parsekit/cli/parsekit.c:109:13

SUMMARY: AddressSanitizer: heap-buffer-overflow /src/parsekit/src/header.c:175:12 in pk_header_join
```

## Steps to reproduce

Save this as `dup-headers.txt` and run `parsekit header --file dup-headers.txt`:

```base64
SG9zdDogZXhhbXBsZS5jb20NClgtVHJhY2U6IGFscGhhDQpYLVRyYWNlOiBiZXRhDQoNCg==
```

## Impact

A one-byte heap overwrite reachable from any input that repeats a header name.
