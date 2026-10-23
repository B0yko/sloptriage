# Double free in header handling

parsekit 1.2.0 frees header values twice in `pk_headers_free()` (src/header.c). Proof:

```c
#include <stdlib.h>
#include <string.h>

int main(void)
{
  char *header = malloc(16);
  strcpy(header, "X-Trace: alpha");
  free(header);
  free(header);
  return 0;
}
```
