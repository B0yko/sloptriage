# Regression in parsekit 1.3.0

After upgrading to parsekit 1.3.0, `pk_header_parse()` accepts header names with spaces, which
enables header injection. `pk_header_validate_name()` was removed in this release.
