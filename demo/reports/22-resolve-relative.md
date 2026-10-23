# Path traversal in pk_url_resolve_relative

`pk_url_resolve_relative()` and `pk_url_join_base()` in src/url.c do not reject `../` segments,
allowing access to arbitrary files when parsekit is used in a web server.

Severity: high (CVSS 8.1)
