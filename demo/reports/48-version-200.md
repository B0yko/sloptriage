# parsekit 2.0.0 URL parser crash

parsekit 2.0.0 crashes on IPv6 hosts in `parse_authority()` (src/url.c). Steps:

```sh
parsekit url 'https://example.com/index.html?q=1'
```
