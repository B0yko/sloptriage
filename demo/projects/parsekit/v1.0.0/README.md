# parsekit

A small URL and HTTP header parsing library in C99 with a command line tool.
It is the demo project bundled with sloptriage and contains two deliberate
memory-safety bugs that the demo reports describe.

    cmake -S . -B build && cmake --build build
    ./build/parsekit url 'https://user@example.com:8080/a/b?q=1#top'
    ./build/parsekit header --file headers.txt

Licensed under the Apache License 2.0.
