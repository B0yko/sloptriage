# Crash in pk_url_parse

parsekit 1.2.0 crashes in `pk_url_parse()` (src/url.c:128) on ordinary URLs:

```sh
parsekit url 'https://example.com/index.html?q=1'
```
