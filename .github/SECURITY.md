# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in IngeTrazo, please report it
**privately** — do not open a public issue.

**Email:** info@ingepresupuestos.com

Please include:

- A description of the vulnerability.
- Steps to reproduce.
- The version of IngeTrazo you are using.
- Any relevant logs or screenshots.

We will acknowledge your report within **7 days** and work with you to
understand and address the issue before any public disclosure.

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.4.x   | ✅ Yes    |
| < 0.4   | ❌ No     |

## Scope

IngeTrazo is a desktop application. Security concerns most relevant to this
project include:

- Malicious `.igz`, `.skp`, or other model files that could cause code execution.
- Plugin system abuse (arbitrary code execution is by design — plugins are
  Python scripts — but isolation and permission boundaries matter).
- The AI Bridge MCP server (localhost TCP socket).
