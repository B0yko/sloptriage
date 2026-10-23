# heap-use-after-free in URL normalisation

Version: parsekit 1.2.0

`pk_url_normalize()` (src/url.c, lines 225-256) frees the old path and then
reads `base[1]`, where `base` came from `strrchr()` on the freed string. Reached through
the public API:

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

ASan reports `heap-use-after-free` READ of size 1 in `pk_url_normalize` at src/url.c:241.
