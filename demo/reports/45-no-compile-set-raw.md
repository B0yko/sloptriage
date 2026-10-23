# Heap overflow through pk_header_set_raw

Calling `pk_header_set_raw()` with a large length corrupts memory:

```c
#include <parsekit.h>

int main(void)
{
  struct pk_headers hs;
  pk_headers_init(&hs);
  pk_header_set_raw(&hs, "X-Trace", 4096);
  return pk_header_merge_continuation(&hs, 0);
}
```
