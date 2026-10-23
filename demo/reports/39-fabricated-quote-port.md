# Stack overflow in port parsing

parsekit 1.2.0 copies the port string into a 6-byte stack buffer. From `src/url.c`:

```c
  if(u->port_str) {
    char portbuf[6];
    strcpy(portbuf, u->port_str);
    u->port = atoi(portbuf);
  }
```
