# Heap overflow when joining Set-Cookie headers

Tested on parsekit 1.2.0, built with `-fsanitize=address,undefined`.

Any application that calls `pk_header_join()` on a header that appears twice
(Set-Cookie is the usual case) corrupts the heap. Trace:

```
==88==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x50200000029 at pc 0xb484e73cf575 bp 0xdcad6ba2b0ae sp 0xe0ca92373288
WRITE of size 1 at 0x50200000015 thread T0
    #0 0x584d8c4fa281 in pk_header_join /work/parsekit/src/header.c:175
    #1 0x5d2802827283 in cmd_header /work/parsekit/cli/parsekit.c:109
    #2 0xe0ad84173581 in main /work/parsekit/cli/parsekit.c:168
    #3 0x569969e58b08 in __libc_start_call_main csu/../sysdeps/nptl/libc_start_call_main.h:58:16
    #4 0x1006f7e3dfc9 in __libc_start_main csu/../csu/libc-start.c:392:3
    #5 0xd3cea27d2693 in _start (/work/parsekit/build/parsekit+0x2c364)

0x502000000035 is located 0 bytes after 5-byte region [0x502000000030,0x502000000035)
allocated by thread T0 here:
    #0 0x67a64cb14028 in malloc ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:145
    #1 0xd512c9791e55 in pk_header_join /work/parsekit/src/header.c:161
    #2 0x8e08baa7196b in cmd_header /work/parsekit/cli/parsekit.c:109

SUMMARY: AddressSanitizer: heap-buffer-overflow /work/parsekit/src/header.c:175 in pk_header_join
```

PoC:

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <parsekit.h>

int main(void)
{
  const char *block = "Set-Cookie: a=1\r\nSet-Cookie: b=2\r\n\r\n";
  struct pk_headers hs;
  char *joined;

  if(pk_header_parse(block, strlen(block), &hs) != PK_OK)
    return 1;
  joined = pk_header_join(&hs, "Set-Cookie");
  printf("%s\n", joined);
  free(joined);
  pk_headers_free(&hs);
  return 0;
}
```
