# Security policy

Please report vulnerabilities in sloptriage through GitHub's private vulnerability reporting:
**Security → Report a vulnerability** on <https://github.com/B0yko/sloptriage>. Do not open a public issue.

In scope: anything that lets report text run code, reach a token, inject markup or mentions into the
comment, or make the tool fetch or clone something the user did not ask for; flaws in the Action's
permission split; and anything that lets a PoC run by `--repro` reach the host, the network or a secret
beyond the documented hardening (a missing flag, a mount, an inherited variable, an unbounded resource).
Vulnerabilities in Docker, Podman or the kernel themselves belong to those projects. Please include the input, the command or workflow, and the observed behaviour.

Supported versions: the latest release.
