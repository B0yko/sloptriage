# Cookie parsing overflow

The cookie jar code in `lib/parsekit/cookie.c` and `src/cookie_jar.c` copies cookie names into
a fixed buffer. This affects every application that uses parsekit for HTTP.
