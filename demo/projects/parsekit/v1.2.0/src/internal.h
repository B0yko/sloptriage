/*
 * parsekit internal helpers.
 *
 * Copyright 2026 Andrii Boiko
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef PARSEKIT_INTERNAL_H
#define PARSEKIT_INTERNAL_H

#include "parsekit.h"

#define PK_ISSPACE(c) ((c) == ' ' || (c) == '\t' || (c) == '\r' || (c) == '\n')
#define PK_ISBLANK(c) ((c) == ' ' || (c) == '\t')
#define PK_ISDIGIT(c) ((c) >= '0' && (c) <= '9')
#define PK_ISALPHA(c) (((c) >= 'a' && (c) <= 'z') || ((c) >= 'A' && (c) <= 'Z'))
#define PK_TOLOWER(c) (((c) >= 'A' && (c) <= 'Z') ? ((c) + ('a' - 'A')) : (c))

#define PK_BUF_MIN 32

int pk_strcaseeq(const char *a, const char *b);
int pk_token_char(int c);

#endif /* PARSEKIT_INTERNAL_H */
