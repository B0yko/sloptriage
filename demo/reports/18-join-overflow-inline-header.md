# One-byte heap overwrite via `parsekit header "<text>"`

parsekit 1.2.0. The inline form of the header command goes through `cmd_header()`
(cli/parsekit.c:109) into `pk_header_join()`, which overflows when a header
repeats.

```sh
parsekit header "$(printf 'Accept: a\r\nAccept: b\r\n')"
```

```
==6060==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x50200000033 at pc 0x0947aaeb26c5 bp 0x7d21fa5d3282 sp 0x63dfe574de73
WRITE of size 1 at 0x50200000047 thread T0
    #0 0x988b886e7577 in pk_header_join /opt/src/parsekit/src/header.c:175:12
    #1 0x496a2c8773e1 in cmd_header /opt/src/parsekit/cli/parsekit.c:109:13
    #2 0x30f7eb197316 in main /opt/src/parsekit/cli/parsekit.c:168:10
    #3 0x62b5e803b61b in __libc_start_call_main csu/../sysdeps/nptl/libc_start_call_main.h:58:16
    #4 0xa4168160adb5 in __libc_start_main csu/../csu/libc-start.c:392:3
    #5 0x2073fec8df4f in _start (/opt/src/parsekit/build/parsekit+0x2c364)

0x502000000035 is located 0 bytes after 5-byte region [0x502000000030,0x502000000035)
allocated by thread T0 here:
    #0 0x9261ff2d3c42 in malloc ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:145
    #1 0x5c8d99d19bdd in pk_header_join /opt/src/parsekit/src/header.c:161:9
    #2 0x0b6cc60d5d32 in cmd_header /opt/src/parsekit/cli/parsekit.c:109:13

SUMMARY: AddressSanitizer: heap-buffer-overflow /opt/src/parsekit/src/header.c:175:12 in pk_header_join
```
