# Heap overflow involving pk_strerror

`pk_strerror()` returns strings longer than expected. Reproducer:

```c
#include <string.h>
#include <stdlib.h>
#include <parsekit.h>

int main(void)
{
  char *copy = malloc(4);
  const char *value = pk_strerror(PK_ERR_SYNTAX);
  memcpy(copy, value, strlen(value) + 1);
  free(copy);
  return 0;
}
```
