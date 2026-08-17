# Security policy

Do not use Open3D Artist as a sandbox for untrusted Blender files, skills, providers, or prompts. The current core does not execute Blender or community code; future workers must run behind an OS/container boundary with network denied by default.

## Reporting

Please do not open a public issue for a vulnerability. Use [GitHub's private security advisory form](https://github.com/nguyenanhducdeveloper86/open3d/security/advisories/new) when available. Include a minimal reproduction, affected version/commit, and impact. Do not include API keys, private assets, or personal data.

We will acknowledge reports within 7 days and publish a fix or mitigation when it is safe to do so.

## Non-negotiable controls

- validate contracts and MCP inputs before use;
- never expose shell, arbitrary filesystem, or `blender.exec_python` as a public operation;
- checkpoint before mutation and keep artifacts immutable;
- deny worker network access unless an explicit provider consent path exists;
- canonicalize paths and re-check after symlink resolution;
- redact credentials from logs and never store them in project artifacts.
