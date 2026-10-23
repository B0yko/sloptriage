# Traversal in pk_url_set_path

```c
#include <parsekit.h>

int main(void)
{
  pk_url_t *u = pk_url_new();
  pk_url_set_path(u, "/a/../../b");
  return pk_url_resolve_relative(u, NULL);
}
```

`pk_url_set_path()` accepts `..` segments that escape the root.
