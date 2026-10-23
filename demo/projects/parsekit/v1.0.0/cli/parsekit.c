/*
 * parsekit command line tool.
 *
 * Copyright 2026 Andrii Boiko
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "parsekit.h"

#define MAX_INPUT (1024 * 1024)

static void usage(void)
{
  fputs("usage: parsekit url <url>\n"
        "       parsekit normalize <url>\n"
        "       parsekit header <text>\n"
        "       parsekit header --file <path>\n"
        "       parsekit decode <percent-encoded>\n"
        "       parsekit --version\n",
        stderr);
}

static char *read_file(const char *path, size_t *len)
{
  FILE *f = fopen(path, "rb");
  char *data;
  size_t n;

  if(!f)
    return NULL;
  data = malloc(MAX_INPUT + 1);
  if(!data) {
    fclose(f);
    return NULL;
  }
  n = fread(data, 1, MAX_INPUT, f);
  fclose(f);
  data[n] = '\0';
  *len = n;
  return data;
}

static void print_url(const struct pk_url *u)
{
  printf("scheme:   %s\n", u->scheme);
  if(u->user)
    printf("user:     %s\n", u->user);
  if(u->host)
    printf("host:     %s\n", u->host);
  if(u->flags & PK_URL_HAS_PORT)
    printf("port:     %u\n", u->port);
  printf("path:     %s\n", u->path ? u->path : "");
  if(u->query)
    printf("query:    %s\n", u->query);
  if(u->fragment)
    printf("fragment: %s\n", u->fragment);
}

static int cmd_url(const char *text, int normalize)
{
  struct pk_url u;
  pk_code rc = pk_url_parse(text, &u);
  if(rc != PK_OK) {
    fprintf(stderr, "parsekit: %s\n", pk_strerror(rc));
    return 1;
  }
  if(normalize) {
    char *s;
    rc = pk_url_normalize(&u);
    if(rc != PK_OK) {
      fprintf(stderr, "parsekit: %s\n", pk_strerror(rc));
      pk_url_free(&u);
      return 1;
    }
    s = pk_url_to_string(&u);
    if(s)
      printf("%s\n", s);
    free(s);
  }
  else
    print_url(&u);
  pk_url_free(&u);
  return 0;
}

static int cmd_header(const char *block, size_t len)
{
  struct pk_headers hs;
  size_t i, j;
  pk_code rc = pk_header_parse(block, len, &hs);

  if(rc != PK_OK) {
    fprintf(stderr, "parsekit: %s\n", pk_strerror(rc));
    return 1;
  }
  for(i = 0; i < hs.count; i++) {
    const char *name = hs.list[i].name;
    int seen = 0;
    char *value;
    for(j = 0; j < i; j++)
      if(!strcmp(hs.list[j].name, name))
        seen = 1;
    if(seen)
      continue;
    value = pk_header_concat(&hs, name);
    printf("%s: %s\n", name, value ? value : "");
    free(value);
  }
  pk_headers_free(&hs);
  return 0;
}

static int cmd_decode(const char *text)
{
  size_t n;
  char *out = pk_percent_decode(text, strlen(text), &n);
  if(!out)
    return 1;
  fwrite(out, 1, n, stdout);
  putchar('\n');
  free(out);
  return 0;
}

int main(int argc, char **argv)
{
  if(argc == 2 && !strcmp(argv[1], "--version")) {
    printf("parsekit %s\n", PK_VERSION);
    return 0;
  }
  if(argc == 3 && !strcmp(argv[1], "url"))
    return cmd_url(argv[2], 0);
  if(argc == 3 && !strcmp(argv[1], "normalize"))
    return cmd_url(argv[2], 1);
  if(argc == 3 && !strcmp(argv[1], "decode"))
    return cmd_decode(argv[2]);
  if(argc == 3 && !strcmp(argv[1], "header"))
    return cmd_header(argv[2], strlen(argv[2]));
  if(argc == 4 && !strcmp(argv[1], "header") && !strcmp(argv[2], "--file")) {
    size_t len = 0;
    int rc;
    char *data = read_file(argv[3], &len);
    if(!data) {
      perror(argv[3]);
      return 1;
    }
    rc = cmd_header(data, len);
    free(data);
    return rc;
  }
  usage();
  return 2;
}
