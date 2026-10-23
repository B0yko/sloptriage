/*
 * parsekit HTTP header parsing.
 *
 * Copyright 2026 Andrii Boiko
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdlib.h>
#include <string.h>

#include "internal.h"

static void header_free(struct pk_header *h)
{
  free(h->name);
  free(h->value);
  h->name = NULL;
  h->value = NULL;
  h->value_len = 0;
}

void pk_headers_free(struct pk_headers *hs)
{
  size_t i;
  for(i = 0; i < hs->count; i++)
    header_free(&hs->list[i]);
  hs->count = 0;
}

/* obs-fold: a CRLF followed by spaces or tabs continues the previous line */
char *pk_header_unfold(const char *value, size_t len)
{
  struct pk_buf out;
  size_t i;

  pk_buf_init(&out);
  for(i = 0; i < len; i++) {
    char c = value[i];
    if((c == '\r' || c == '\n')) {
      size_t j = i;
      if(c == '\r' && j + 1 < len && value[j + 1] == '\n')
        j++;
      if(j + 1 < len && PK_ISBLANK(value[j + 1])) {
        i = j + 1;
        while(i + 1 < len && PK_ISBLANK(value[i + 1]))
          i++;
        c = ' ';
      }
    }
    if(pk_buf_append_char(&out, c) != PK_OK) {
      pk_buf_free(&out);
      return NULL;
    }
  }
  return pk_buf_detach(&out);
}

static pk_code parse_line(const char *line, size_t len, struct pk_headers *hs)
{
  const char *colon = memchr(line, ':', len);
  const char *value;
  size_t namelen, valuelen, i;
  struct pk_header *h;

  if(!colon || colon == line)
    return PK_ERR_SYNTAX;
  namelen = (size_t)(colon - line);
  for(i = 0; i < namelen; i++)
    if(!pk_token_char((unsigned char)line[i]))
      return PK_ERR_SYNTAX;
  if(hs->count >= PK_MAX_HEADERS)
    return PK_ERR_TOO_MANY;
  value = colon + 1;
  valuelen = pk_trim(&value, len - namelen - 1);
  h = &hs->list[hs->count];
  h->name = pk_strndup(line, namelen);
  h->value = pk_header_unfold(value, valuelen);
  if(!h->name || !h->value) {
    header_free(h);
    return PK_ERR_NOMEM;
  }
  h->value_len = strlen(h->value);
  hs->count++;
  return PK_OK;
}

/* parse a header block: lines separated by CRLF or LF, ended by an empty line */
pk_code pk_header_parse(const char *block, size_t len, struct pk_headers *hs)
{
  size_t pos = 0;

  hs->count = 0;
  while(pos < len) {
    size_t start = pos, end;
    pk_code rc;

    /* find the end of this field, including obs-fold continuation lines */
    for(;;) {
      while(pos < len && block[pos] != '\n')
        pos++;
      if(pos + 1 < len && PK_ISBLANK(block[pos + 1])) {
        pos++;
        continue;
      }
      break;
    }
    end = pos;
    if(end > start && block[end - 1] == '\r')
      end--;
    if(pos < len)
      pos++;
    if(end == start)
      break;
    if(end - start > PK_MAX_HEADER_LINE) {
      pk_headers_free(hs);
      return PK_ERR_TOO_LONG;
    }
    rc = parse_line(block + start, end - start, hs);
    if(rc != PK_OK) {
      pk_headers_free(hs);
      return rc;
    }
  }
  return PK_OK;
}

const struct pk_header *pk_header_get(const struct pk_headers *hs, const char *name)
{
  size_t i;
  for(i = 0; i < hs->count; i++)
    if(pk_strcaseeq(hs->list[i].name, name))
      return &hs->list[i];
  return NULL;
}

size_t pk_header_count(const struct pk_headers *hs, const char *name)
{
  size_t i, n = 0;
  for(i = 0; i < hs->count; i++)
    if(pk_strcaseeq(hs->list[i].name, name))
      n++;
  return n;
}

/* combine all values of a repeated header into one comma-separated value */
char *pk_header_concat(const struct pk_headers *hs, const char *name)
{
  size_t i, n = 0, total = 0, pos = 0;
  char *out;

  for(i = 0; i < hs->count; i++) {
    if(pk_strcaseeq(hs->list[i].name, name)) {
      total += hs->list[i].value_len;
      n++;
    }
  }
  if(!n)
    return NULL;
  if(n == 1)
    return pk_strndup(pk_header_get(hs, name)->value, total);
  total += (n - 1) * 2;
  out = malloc(total + 1);
  if(!out)
    return NULL;
  for(i = 0; i < hs->count; i++) {
    const struct pk_header *h = &hs->list[i];
    if(!pk_strcaseeq(h->name, name))
      continue;
    if(pos) {
      out[pos++] = ',';
      out[pos++] = ' ';
    }
    memcpy(out + pos, h->value, h->value_len);
    pos += h->value_len;
  }
  out[pos] = '\0';
  return out;
}

pk_code pk_header_remove(struct pk_headers *hs, const char *name)
{
  size_t i = 0, removed = 0;
  while(i < hs->count) {
    if(pk_strcaseeq(hs->list[i].name, name)) {
      header_free(&hs->list[i]);
      memmove(&hs->list[i], &hs->list[i + 1], (hs->count - i - 1) * sizeof(hs->list[0]));
      hs->count--;
      removed++;
    }
    else
      i++;
  }
  return removed ? PK_OK : PK_ERR_NOT_FOUND;
}
