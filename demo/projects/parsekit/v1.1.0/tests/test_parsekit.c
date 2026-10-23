/*
 * parsekit unit tests (normal inputs only).
 *
 * Copyright 2026 Andrii Boiko
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "parsekit.h"

static int failures;

#define CHECK(cond)                                                  \
  do {                                                               \
    if(!(cond)) {                                                    \
      fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #cond); \
      failures++;                                                    \
    }                                                                \
  } while(0)

static void test_url_parse(void)
{
  struct pk_url u;
  CHECK(pk_url_parse("https://user:pw@example.com:8443/a/b?x=1#frag", &u) == PK_OK);
  CHECK(!strcmp(u.scheme, "https"));
  CHECK(!strcmp(u.user, "user"));
  CHECK(!strcmp(u.password, "pw"));
  CHECK(!strcmp(u.host, "example.com"));
  CHECK(u.port == 8443);
  CHECK(!strcmp(u.path, "/a/b"));
  CHECK(!strcmp(u.query, "x=1"));
  CHECK(!strcmp(u.fragment, "frag"));
  pk_url_free(&u);

  CHECK(pk_url_parse("http://[::1]:80/", &u) == PK_OK);
  CHECK(!strcmp(u.host, "[::1]"));
  pk_url_free(&u);

  CHECK(pk_url_parse("http://example.com:99999/", &u) == PK_ERR_PORT);
  CHECK(pk_url_parse("1http://example.com/", &u) == PK_ERR_SYNTAX);
}

static void test_url_normalize(void)
{
  struct pk_url u;
  char *s;
  CHECK(pk_url_parse("HTTP://Example.COM:80", &u) == PK_OK);
  CHECK(pk_url_normalize(&u) == PK_OK);
  s = pk_url_to_string(&u);
  CHECK(s && !strcmp(s, "http://example.com/"));
  free(s);
  pk_url_free(&u);
}

static void test_headers(void)
{
  struct pk_headers hs;
  const char *block = "Host: example.com\r\nX-Long: a\r\n  b\r\nAccept: */*\r\n\r\n";
  const struct pk_header *h;
  CHECK(pk_header_parse(block, strlen(block), &hs) == PK_OK);
  CHECK(hs.count == 3);
  h = pk_header_get(&hs, "x-long");
  CHECK(h && !strcmp(h->value, "a b"));
  CHECK(pk_header_count(&hs, "HOST") == 1);
  CHECK(pk_header_remove(&hs, "accept") == PK_OK);
  CHECK(hs.count == 2);
  pk_headers_free(&hs);
  CHECK(pk_header_parse("bad header\r\n", 12, &hs) == PK_ERR_SYNTAX);
}

static void test_query_and_decode(void)
{
  struct pk_query q;
  size_t n;
  char *d = pk_percent_decode("a%2Fb%zz", 8, &n);
  CHECK(d && !strcmp(d, "a/b%zz") && n == 6);
  free(d);
  CHECK(pk_query_parse("a=1&b=two+words&flag", &q) == PK_OK);
  CHECK(q.count == 3);
  CHECK(!strcmp(pk_query_get(&q, "b"), "two words"));
  CHECK(!strcmp(pk_query_get(&q, "flag"), ""));
  CHECK(pk_query_get(&q, "missing") == NULL);
  pk_query_free(&q);
}

int main(void)
{
  test_url_parse();
  test_url_normalize();
  test_headers();
  test_query_and_decode();
  if(failures) {
    fprintf(stderr, "%d check(s) failed\n", failures);
    return 1;
  }
  puts("all parsekit tests passed");
  return 0;
}
