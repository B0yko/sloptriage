# Security vulnerability in parsekit

I found a serious memory safety issue in parsekit's parsing code that can lead to remote code
execution. The library does not properly validate input lengths. Please assign a CVE and a bounty.
