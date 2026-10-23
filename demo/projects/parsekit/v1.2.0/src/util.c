/*
 * parsekit string helpers.
 *
 * Copyright 2026 Andrii Boiko
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdlib.h>
#include <string.h>

#include "internal.h"

char *pk_strndup(const char *s, size_t n)
{
  char *out = malloc(n + 1);
  if(!out)
    return NULL;
  memcpy(out, s, n);
  out[n] = '\0';
  return out;
}

void pk_str_lower(char *s)
{
  for(; s && *s; s++)
    *s = (char)PK_TOLOWER(*s);
}

int pk_strcaseeq(const char *a, const char *b)
{
  while(*a && *b) {
    if(PK_TOLOWER(*a) != PK_TOLOWER(*b))
      return 0;
    a++;
    b++;
  }
  return *a == *b;
}

/* skip leading and trailing whitespace; returns the trimmed length */
size_t pk_trim(const char **start, size_t len)
{
  const char *s = *start;
  while(len && PK_ISSPACE(*s)) {
    s++;
    len--;
  }
  while(len && PK_ISSPACE(s[len - 1]))
    len--;
  *start = s;
  return len;
}

int pk_hexval(int c)
{
  if(c >= '0' && c <= '9')
    return c - '0';
  if(c >= 'a' && c <= 'f')
    return c - 'a' + 10;
  if(c >= 'A' && c <= 'F')
    return c - 'A' + 10;
  return -1;
}

/* RFC 7230 tchar */
int pk_token_char(int c)
{
  if(PK_ISALPHA(c) || PK_ISDIGIT(c))
    return 1;
  return c && strchr("!#$%&'*+-.^_`|~", c) != NULL;
}

/* decode %XX escapes; invalid escapes are copied unchanged */
char *pk_percent_decode(const char *in, size_t len, size_t *outlen)
{
  char *out = malloc(len + 1);
  size_t i, o = 0;

  if(!out)
    return NULL;
  for(i = 0; i < len; i++) {
    if(in[i] == '%' && i + 2 < len) {
      int hi = pk_hexval((unsigned char)in[i + 1]);
      int lo = pk_hexval((unsigned char)in[i + 2]);
      if(hi >= 0 && lo >= 0) {
        out[o++] = (char)((hi << 4) | lo);
        i += 2;
        continue;
      }
    }
    out[o++] = in[i];
  }
  out[o] = '\0';
  if(outlen)
    *outlen = o;
  return out;
}

const char *pk_strerror(pk_code code)
{
  switch(code) {
  case PK_OK:
    return "no error";
  case PK_ERR_NOMEM:
    return "out of memory";
  case PK_ERR_SYNTAX:
    return "syntax error";
  case PK_ERR_TOO_LONG:
    return "input too long";
  case PK_ERR_TOO_MANY:
    return "too many headers";
  case PK_ERR_PORT:
    return "invalid port";
  case PK_ERR_NOT_FOUND:
    return "not found";
  }
  return "unknown error";
}
