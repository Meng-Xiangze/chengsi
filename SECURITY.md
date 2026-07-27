# Security Policy

## Supported Versions

Security fixes are applied to the latest published version. Older releases may not receive backports.

## Reporting a Vulnerability

Do not disclose exploitable security issues in a public issue. Report them privately through GitHub Security Advisories for this repository, or through the private contact method listed by the repository owner.

Include the affected version, operating system, reproduction steps, impact, and any relevant logs. Remove API keys, personal file paths, conversations, generated media, and private knowledge-base content before submitting a report.

## Security Model

Chengsi runs locally with the permissions of the current operating-system user. Tools such as `python_executor` can execute code, and `system_cleaner` can delete selected files. Path checks and protected project directories reduce common accidents, but Chengsi is not an OS-level sandbox.

Use trusted model providers and tools, keep backups, protect `config.json`, and do not expose the desktop interface or credentials to untrusted networks.
