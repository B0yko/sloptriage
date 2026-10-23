# Off-by-one heap write in pk_header_join

**Affected version:** parsekit 1.2.0
**Component:** `src/header.c`, function `pk_header_join()` (lines 145-177)

When more than one header matches, the function allocates `total` bytes at line
161 and later stores the terminating zero at `out[pos]`, line 175, where
`pos == total`. A caller that only uses the public API hits it:

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

Compile with `-fsanitize=address` against the installed library and run it; ASan
reports a 1-byte WRITE just after the allocated region in `pk_header_join`.
