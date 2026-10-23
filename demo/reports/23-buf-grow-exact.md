# Integer overflow in buffer growth

The function `pk_buf_grow_exact()` multiplies the capacity by 2 without an overflow check, and
`pk_buf_shrink_to_fit()` then frees the old pointer twice. This leads to memory corruption.
