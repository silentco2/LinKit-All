# Security

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting: open the [Security tab](https://github.com/silentco2/LinKit-All/security) of the repository and choose "Report a vulnerability".

Include what you found, the steps to reproduce it, and the version or commit. Do not include real CVs, passwords or tokens.

## What counts

Examples: the local web server reachable from another computer or website, a way to read the vault without the passphrase, secrets or CV text written to logs, data sent anywhere other than your chosen AI provider, a dry run that clicks Submit.

## How the project handles security

See [docs/privacy.md](docs/privacy.md) for where data is stored, what the AI provider sees, how the vault works and what is logged.

LinKit All is early software and the package is not on PyPI yet, so only the latest commit on the main branch is supported.
