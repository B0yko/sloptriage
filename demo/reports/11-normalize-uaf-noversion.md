# Normalising URLs with dot segments reads freed memory

The crash is in pk_url_normalize at src/url.c:241: the pointer `base` is computed
from the old path, which is freed a few lines earlier at line 239.

```sh
parsekit normalize 'http://example.com/a/./b/../c'
```
