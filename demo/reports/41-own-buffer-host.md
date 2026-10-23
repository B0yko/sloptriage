# Buffer overflow in pk_url_parse with long host names

`pk_url_parse()` in src/url.c (lines 123-170) returns host names of any length,
which overflows the caller's buffer. PoC:

```c
#include <stdio.h>
#include <string.h>
#include <parsekit.h>

int main(void)
{
  struct pk_url u;
  char host[8];

  if(pk_url_parse("http://very-long-hostname.example.com/", &u) != PK_OK)
    return 1;
  strcpy(host, u.host);
  printf("%s\n", host);
  pk_url_free(&u);
  return 0;
}
```

AddressSanitizer reports a stack-buffer-overflow.
