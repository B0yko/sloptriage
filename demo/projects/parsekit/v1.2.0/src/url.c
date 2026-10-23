/*
 * parsekit URL parsing and normalisation.
 *
 * Copyright 2026 Andrii Boiko
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "internal.h"

#define PK_MAX_URL 16384

static void url_clear(struct pk_url *u)
{
  memset(u, 0, sizeof(*u));
}

void pk_url_free(struct pk_url *u)
{
  if(!u)
    return;
  free(u->scheme);
  free(u->user);
  free(u->password);
  free(u->host);
  free(u->path);
  free(u->query);
  free(u->fragment);
  url_clear(u);
}

/* scheme = ALPHA *( ALPHA / DIGIT / "+" / "-" / "." ) */
static size_t parse_scheme(const char *s, size_t len)
{
  size_t i;
  if(!len || !PK_ISALPHA(s[0]))
    return 0;
  for(i = 1; i < len; i++) {
    char c = s[i];
    if(c == ':')
      return i;
    if(!PK_ISALPHA(c) && !PK_ISDIGIT(c) && c != '+' && c != '-' && c != '.')
      return 0;
  }
  return 0;
}

static pk_code parse_port(const char *s, size_t len, unsigned int *port)
{
  unsigned long value = 0;
  size_t i;
  if(!len || len > 5)
    return PK_ERR_PORT;
  for(i = 0; i < len; i++) {
    if(!PK_ISDIGIT(s[i]))
      return PK_ERR_PORT;
    value = value * 10 + (unsigned long)(s[i] - '0');
  }
  if(value > 65535)
    return PK_ERR_PORT;
  *port = (unsigned int)value;
  return PK_OK;
}

/* authority = [ userinfo "@" ] host [ ":" port ] */
static pk_code parse_authority(const char *s, size_t len, struct pk_url *u)
{
  const char *at = NULL;
  const char *host;
  const char *colon = NULL;
  size_t hostlen, i;

  for(i = 0; i < len; i++)
    if(s[i] == '@')
      at = s + i;
  host = s;
  if(at) {
    const char *pw = memchr(s, ':', (size_t)(at - s));
    if(pw) {
      u->user = pk_strndup(s, (size_t)(pw - s));
      u->password = pk_strndup(pw + 1, (size_t)(at - pw - 1));
      if(!u->user || !u->password)
        return PK_ERR_NOMEM;
    }
    else {
      u->user = pk_strndup(s, (size_t)(at - s));
      if(!u->user)
        return PK_ERR_NOMEM;
    }
    host = at + 1;
  }
  hostlen = len - (size_t)(host - s);
  if(hostlen && host[0] == '[') {
    const char *end = memchr(host, ']', hostlen);
    if(!end)
      return PK_ERR_SYNTAX;
    if((size_t)(end - host) + 1 < hostlen) {
      if(end[1] != ':')
        return PK_ERR_SYNTAX;
      colon = end + 1;
    }
  }
  else {
    for(i = 0; i < hostlen; i++)
      if(host[i] == ':')
        colon = host + i;
  }
  if(colon) {
    pk_code rc = parse_port(colon + 1, hostlen - (size_t)(colon - host) - 1, &u->port);
    if(rc != PK_OK)
      return rc;
    u->flags |= PK_URL_HAS_PORT;
    hostlen = (size_t)(colon - host);
  }
  if(!hostlen)
    return PK_ERR_SYNTAX;
  u->host = pk_strndup(host, hostlen);
  return u->host ? PK_OK : PK_ERR_NOMEM;
}

pk_code pk_url_parse(const char *text, struct pk_url *u)
{
  size_t len = strlen(text);
  size_t schemelen, i;
  const char *rest, *end;
  pk_code rc;

  url_clear(u);
  if(len > PK_MAX_URL)
    return PK_ERR_TOO_LONG;
  schemelen = parse_scheme(text, len);
  if(!schemelen)
    return PK_ERR_SYNTAX;
  u->scheme = pk_strndup(text, schemelen);
  if(!u->scheme)
    return PK_ERR_NOMEM;
  rest = text + schemelen + 1;
  end = text + len;
  if(end - rest >= 2 && rest[0] == '/' && rest[1] == '/') {
    const char *auth = rest + 2;
    const char *auth_end = auth;
    while(auth_end < end && *auth_end != '/' && *auth_end != '?' && *auth_end != '#')
      auth_end++;
    rc = parse_authority(auth, (size_t)(auth_end - auth), u);
    if(rc != PK_OK) {
      pk_url_free(u);
      return rc;
    }
    rest = auth_end;
  }
  for(i = 0; rest + i < end && rest[i] != '?' && rest[i] != '#'; i++)
    ;
  u->path = pk_strndup(rest, i);
  rest += i;
  if(rest < end && *rest == '?') {
    const char *q = ++rest;
    while(rest < end && *rest != '#')
      rest++;
    u->query = pk_strndup(q, (size_t)(rest - q));
  }
  if(rest < end && *rest == '#')
    u->fragment = pk_strndup(rest + 1, (size_t)(end - rest - 1));
  if(!u->path) {
    pk_url_free(u);
    return PK_ERR_NOMEM;
  }
  return PK_OK;
}

/* RFC 3986 section 5.2.4 */
static char *remove_dot_segments(const char *path)
{
  struct pk_buf out;
  const char *p = path;

  pk_buf_init(&out);
  while(*p) {
    if(!strncmp(p, "../", 3))
      p += 3;
    else if(!strncmp(p, "./", 2))
      p += 2;
    else if(!strncmp(p, "/./", 3))
      p += 2;
    else if(!strcmp(p, "/."))
      p = "/";
    else if(!strncmp(p, "/../", 4) || !strcmp(p, "/..")) {
      char *slash;
      p = p[3] ? p + 3 : "/";
      slash = out.data ? strrchr(out.data, '/') : NULL;
      if(slash) {
        out.len = (size_t)(slash - out.data);
        out.data[out.len] = '\0';
      }
    }
    else if(!strcmp(p, ".") || !strcmp(p, ".."))
      break;
    else {
      const char *seg = p;
      if(*p == '/')
        p++;
      while(*p && *p != '/')
        p++;
      if(pk_buf_append(&out, seg, (size_t)(p - seg)) != PK_OK) {
        pk_buf_free(&out);
        return NULL;
      }
    }
  }
  return pk_buf_detach(&out);
}

static unsigned int default_port(const char *scheme)
{
  if(pk_strcaseeq(scheme, "http") || pk_strcaseeq(scheme, "ws"))
    return 80;
  if(pk_strcaseeq(scheme, "https") || pk_strcaseeq(scheme, "wss"))
    return 443;
  if(pk_strcaseeq(scheme, "ftp"))
    return 21;
  return 0;
}

pk_code pk_url_normalize(struct pk_url *u)
{
  pk_str_lower(u->scheme);
  pk_str_lower(u->host);
  if((u->flags & PK_URL_HAS_PORT) && u->port == default_port(u->scheme)) {
    u->flags &= ~(unsigned int)PK_URL_HAS_PORT;
    u->port = 0;
  }
  if(u->path && strstr(u->path, "/.")) {
    char *clean = remove_dot_segments(u->path);
    const char *base;
    if(!clean)
      return PK_ERR_NOMEM;
    base = strrchr(u->path, '/');
    free(u->path);
    u->path = clean;
    if(base && base[1] == '\0')
      u->flags |= PK_URL_TRAILING_SLASH;
  }
  else if(u->path && *u->path) {
    size_t n = strlen(u->path);
    if(u->path[n - 1] == '/')
      u->flags |= PK_URL_TRAILING_SLASH;
  }
  if(u->path && !*u->path && u->host) {
    free(u->path);
    u->path = pk_strndup("/", 1);
    if(!u->path)
      return PK_ERR_NOMEM;
  }
  return PK_OK;
}

char *pk_url_to_string(const struct pk_url *u)
{
  struct pk_buf b;
  char port[8];

  pk_buf_init(&b);
  if(pk_buf_append_str(&b, u->scheme) || pk_buf_append_char(&b, ':'))
    goto fail;
  if(u->host) {
    if(pk_buf_append_str(&b, "//"))
      goto fail;
    if(u->user) {
      if(pk_buf_append_str(&b, u->user))
        goto fail;
      if(u->password && (pk_buf_append_char(&b, ':') || pk_buf_append_str(&b, u->password)))
        goto fail;
      if(pk_buf_append_char(&b, '@'))
        goto fail;
    }
    if(pk_buf_append_str(&b, u->host))
      goto fail;
    if(u->flags & PK_URL_HAS_PORT) {
      snprintf(port, sizeof(port), ":%u", u->port);
      if(pk_buf_append_str(&b, port))
        goto fail;
    }
  }
  if(u->path && pk_buf_append_str(&b, u->path))
    goto fail;
  if(u->query && (pk_buf_append_char(&b, '?') || pk_buf_append_str(&b, u->query)))
    goto fail;
  if(u->fragment && (pk_buf_append_char(&b, '#') || pk_buf_append_str(&b, u->fragment)))
    goto fail;
  return pk_buf_detach(&b);
fail:
  pk_buf_free(&b);
  return NULL;
}
