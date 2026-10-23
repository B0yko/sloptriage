# Out-of-bounds read in header indexing

```c
#include <stdio.h>

int main(void)
{
  int values[4] = {1, 2, 3, 4};
  int i;
  for(i = 0; i <= 4; i++)
    printf("%d\n", values[i]);
  return 0;
}
```

This shows the same off-by-one that `pk_header_get()` has.
