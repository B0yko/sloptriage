# URL API overflow (Curl_parse_url)

In `lib/urlapi.c`, `Curl_parse_url()` copies the scheme into a fixed buffer, and `curl_url_set()`
passes the user string straight through. `lib/url.c:1840` shows the same pattern.
