# Memory leak in src/session.c

`src/session.c` leaks the session object when `src/transport/tls.c` fails to connect. Over time
this causes denial of service.
