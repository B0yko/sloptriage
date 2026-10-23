# kvconf

A small `key = value` configuration file parser with `[sections]`, `@include` lines
and `${name}` interpolation. It is the Python demo project bundled with sloptriage
and contains one deliberate bug that the demo reports describe.

    pip install .
    kvconf settings.conf
    kvconf settings.conf --get server.port

Licensed under the Apache License 2.0.
