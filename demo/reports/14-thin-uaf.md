# parsekit normalize crash

parsekit 1.2.0, `pk_url_normalize()`: heap-use-after-free with dot segments.

```sh
parsekit normalize 'http://example.com/a/./b/../c'
```
