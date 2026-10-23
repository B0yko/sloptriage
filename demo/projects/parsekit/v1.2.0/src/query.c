/*
 * parsekit query-string parsing (application/x-www-form-urlencoded).
 *
 * Copyright 2026 Andrii Boiko
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdlib.h>
#include <string.h>

#include "internal.h"

static void param_free(struct pk_param *p)
{
  free(p->key);
  free(p->value);
  p->key = NULL;
  p->value = NULL;
}

void pk_query_free(struct pk_query *q)
{
  size_t i;
  for(i = 0; i < q->count; i++)
    param_free(&q->params[i]);
  free(q->params);
  q->params = NULL;
  q->count = 0;
  q->cap = 0;
}

/* '+' means space in form encoding; everything else goes through %XX decoding */
static char *form_decode(const char *s, size_t len)
{
  char *plus = pk_strndup(s, len);
  char *out;
  size_t i;

  if(!plus)
    return NULL;
  for(i = 0; i < len; i++)
    if(plus[i] == '+')
      plus[i] = ' ';
  out = pk_percent_decode(plus, len, NULL);
  free(plus);
  return out;
}

static pk_code add_param(struct pk_query *q, const char *pair, size_t len)
{
  const char *eq = memchr(pair, '=', len);
  struct pk_param *p;

  if(q->count == q->cap) {
    size_t cap = q->cap ? q->cap * 2 : 8;
    struct pk_param *grown;
    if(cap > PK_MAX_PARAMS)
      return PK_ERR_TOO_MANY;
    grown = realloc(q->params, cap * sizeof(*grown));
    if(!grown)
      return PK_ERR_NOMEM;
    q->params = grown;
    q->cap = cap;
  }
  p = &q->params[q->count];
  if(eq) {
    p->key = form_decode(pair, (size_t)(eq - pair));
    p->value = form_decode(eq + 1, len - (size_t)(eq - pair) - 1);
  }
  else {
    p->key = form_decode(pair, len);
    p->value = NULL;
  }
  if(!p->key || (eq && !p->value)) {
    param_free(p);
    return PK_ERR_NOMEM;
  }
  q->count++;
  return PK_OK;
}

pk_code pk_query_parse(const char *text, struct pk_query *q)
{
  const char *p = text;

  memset(q, 0, sizeof(*q));
  if(!text)
    return PK_OK;
  while(*p) {
    const char *amp = strchr(p, '&');
    size_t len = amp ? (size_t)(amp - p) : strlen(p);
    if(len) {
      pk_code rc = add_param(q, p, len);
      if(rc != PK_OK) {
        pk_query_free(q);
        return rc;
      }
    }
    if(!amp)
      break;
    p = amp + 1;
  }
  return PK_OK;
}

const char *pk_query_get(const struct pk_query *q, const char *key)
{
  size_t i;
  for(i = 0; i < q->count; i++)
    if(!strcmp(q->params[i].key, key))
      return q->params[i].value ? q->params[i].value : "";
  return NULL;
}
