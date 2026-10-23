# Use-after-free when normalising https://example.com/docs/./guide/../index.html

Affected: parsekit 1.2.0, `src/url.c`

Steps:

```c
#include <stdio.h>
#include <stdlib.h>
#include <parsekit.h>

int main(void)
{
  struct pk_url u;
  char *s;

  if(pk_url_parse("https://example.com/docs/./guide/../index.html", &u) != PK_OK)
    return 1;
  pk_url_normalize(&u);
  s = pk_url_to_string(&u);
  puts(s ? s : "(null)");
  free(s);
  pk_url_free(&u);
  return 0;
}
```

Result (excerpt):

```
==2024==ERROR: AddressSanitizer: heap-use-after-free on address 0x5030000064a at pc 0xff02cee73744 bp 0x3e210471948d sp 0x33296c87009e
READ of size 1 at 0x50300000004a thread T0
    #0 0x8a7f770d9106 in pk_url_normalize /src/parsekit/src/url.c:241:17
    #1 0xfd287db7f1ad in cmd_url /src/parsekit/cli/parsekit.c:73:10
    #2 0xbc60926f6967 in main /src/parsekit/cli/parsekit.c:153:12
    #3 0xe7893f57fd14 in __libc_start_main csu/../csu/libc-start.c:392:3

0x50300000004a is located 10 bytes inside of 21-byte region [0x503000000040,0x503000000055)
freed by thread T0 here:
    #0 0xc1604d115cea in free ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:52
    #1 0x325a65e19cba in pk_url_normalize /src/parsekit/src/url.c:239:5
    #2 0xe530282bd36c in cmd_url /src/parsekit/cli/parsekit.c:73:10

previously allocated by thread T0 here:
    #0 0xb9d21f6be6ab in malloc ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:69
    #1 0xf0d7c1c1e218 in pk_strndup /src/parsekit/src/util.c:14:15
    #2 0x62ab8a18a890 in pk_url_parse /src/parsekit/src/url.c:155:13

SUMMARY: AddressSanitizer: heap-use-after-free /src/parsekit/src/url.c:241:17 in pk_url_normalize
```
