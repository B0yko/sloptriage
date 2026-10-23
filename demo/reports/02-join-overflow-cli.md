# parsekit header crashes on duplicate header names

Version: parsekit 1.1.0 (also reproduced on 1.2.0)

`parsekit header --file` aborts under AddressSanitizer as soon as one header name
appears twice. The overflow is in `pk_header_join()` (src/header.c:175), called
from `cmd_header()`.

### Reproduce

```sh
printf 'Host: example.com\r\nX-Trace: alpha\r\nX-Trace: beta\r\n\r\n' > dup.txt
parsekit header --file dup.txt
```

### ASan

```
==31337==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x50200000072 at pc 0xeff9243a8f50 bp 0x6b40928b5b7a sp 0x767c76fb008f
WRITE of size 1 at 0x50200000043 thread T0
    #0 0x6bebb2737f6a in pk_header_join /build/parsekit-1.1.0/src/header.c:175:12
    #1 0x6f0fb23c6f5d in cmd_header /build/parsekit-1.1.0/cli/parsekit.c:109:13
    #2 0xa2cec255404e in main /build/parsekit-1.1.0/cli/parsekit.c:168:10
    #3 0x4fb440034d66 in __libc_start_call_main csu/../sysdeps/nptl/libc_start_call_main.h:58:16
    #4 0x08697a8d41be in __libc_start_main csu/../csu/libc-start.c:392:3
    #5 0xb026c48bbf33 in _start (/build/parsekit-1.1.0/build/parsekit+0x2c364)

0x502000000035 is located 0 bytes after 5-byte region [0x502000000030,0x502000000035)
allocated by thread T0 here:
    #0 0xd440e50454f3 in malloc ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:145
    #1 0x1af3176813e0 in pk_header_join /build/parsekit-1.1.0/src/header.c:161:9
    #2 0x2ea68ef786e4 in cmd_header /build/parsekit-1.1.0/cli/parsekit.c:109:13

SUMMARY: AddressSanitizer: heap-buffer-overflow /build/parsekit-1.1.0/src/header.c:175:12 in pk_header_join
```
