/*
 * parsekit growable buffers.
 *
 * Copyright 2026 Andrii Boiko
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdlib.h>
#include <string.h>

#include "internal.h"

void pk_buf_init(struct pk_buf *b)
{
  b->data = NULL;
  b->len = 0;
  b->cap = 0;
}

void pk_buf_free(struct pk_buf *b)
{
  free(b->data);
  pk_buf_init(b);
}

/* make room for at least `extra` more bytes plus a terminating zero */
static pk_code buf_reserve(struct pk_buf *b, size_t extra)
{
  size_t need = b->len + extra + 1;
  size_t cap = b->cap ? b->cap : PK_BUF_MIN;
  char *grown;

  if(need < b->len)
    return PK_ERR_TOO_LONG;
  if(need <= b->cap)
    return PK_OK;
  while(cap < need) {
    if(cap > ((size_t)-1) / 2)
      return PK_ERR_TOO_LONG;
    cap *= 2;
  }
  grown = realloc(b->data, cap);
  if(!grown)
    return PK_ERR_NOMEM;
  b->data = grown;
  b->cap = cap;
  return PK_OK;
}

pk_code pk_buf_append(struct pk_buf *b, const char *data, size_t len)
{
  pk_code rc = buf_reserve(b, len);
  if(rc != PK_OK)
    return rc;
  if(len)
    memcpy(b->data + b->len, data, len);
  b->len += len;
  b->data[b->len] = '\0';
  return PK_OK;
}

pk_code pk_buf_append_char(struct pk_buf *b, char c)
{
  return pk_buf_append(b, &c, 1);
}

pk_code pk_buf_append_str(struct pk_buf *b, const char *str)
{
  return pk_buf_append(b, str, strlen(str));
}

/* hand over the buffer contents; the caller frees them */
char *pk_buf_detach(struct pk_buf *b)
{
  char *out = b->data;
  if(!out) {
    out = malloc(1);
    if(out)
      out[0] = '\0';
  }
  pk_buf_init(b);
  return out;
}
