/*
 * parsekit - a small URL and HTTP header parsing library.
 *
 * Copyright 2026 Andrii Boiko
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef PARSEKIT_H
#define PARSEKIT_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PK_VERSION "1.1.0"
#define PK_VERSION_NUM 0x010100

#define PK_MAX_HEADERS 64
#define PK_MAX_HEADER_LINE 8192

typedef enum {
  PK_OK = 0,
  PK_ERR_NOMEM,
  PK_ERR_SYNTAX,
  PK_ERR_TOO_LONG,
  PK_ERR_TOO_MANY,
  PK_ERR_PORT,
  PK_ERR_NOT_FOUND
} pk_code;

/* growable byte buffer */
struct pk_buf {
  char *data;
  size_t len;
  size_t cap;
};

#define PK_URL_TRAILING_SLASH (1 << 0)
#define PK_URL_HAS_PORT (1 << 1)

struct pk_url {
  char *scheme;
  char *user;
  char *password;
  char *host;
  unsigned int port;
  char *path;
  char *query;
  char *fragment;
  unsigned int flags;
};

struct pk_header {
  char *name;
  char *value;
  size_t value_len;
};

struct pk_headers {
  struct pk_header list[PK_MAX_HEADERS];
  size_t count;
};

#define PK_MAX_PARAMS 1024

struct pk_param {
  char *key;
  char *value; /* NULL for a key without '=' */
};

struct pk_query {
  struct pk_param *params;
  size_t count;
  size_t cap;
};

/* buffers */
void pk_buf_init(struct pk_buf *b);
void pk_buf_free(struct pk_buf *b);
pk_code pk_buf_append(struct pk_buf *b, const char *data, size_t len);
pk_code pk_buf_append_char(struct pk_buf *b, char c);
pk_code pk_buf_append_str(struct pk_buf *b, const char *str);
char *pk_buf_detach(struct pk_buf *b);

/* strings */
char *pk_strndup(const char *s, size_t n);
void pk_str_lower(char *s);
size_t pk_trim(const char **start, size_t len);
int pk_hexval(int c);
char *pk_percent_decode(const char *in, size_t len, size_t *outlen);

/* URLs */
pk_code pk_url_parse(const char *text, struct pk_url *url);
pk_code pk_url_normalize(struct pk_url *url);
char *pk_url_to_string(const struct pk_url *url);
void pk_url_free(struct pk_url *url);

/* query strings */
pk_code pk_query_parse(const char *text, struct pk_query *q);
const char *pk_query_get(const struct pk_query *q, const char *key);
void pk_query_free(struct pk_query *q);

/* HTTP headers */
pk_code pk_header_parse(const char *block, size_t len, struct pk_headers *hs);
const struct pk_header *pk_header_get(const struct pk_headers *hs, const char *name);
size_t pk_header_count(const struct pk_headers *hs, const char *name);
char *pk_header_join(const struct pk_headers *hs, const char *name);
char *pk_header_unfold(const char *value, size_t len);
pk_code pk_header_remove(struct pk_headers *hs, const char *name);
void pk_headers_free(struct pk_headers *hs);

const char *pk_strerror(pk_code code);

#ifdef __cplusplus
}
#endif

#endif /* PARSEKIT_H */
