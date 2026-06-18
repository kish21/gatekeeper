# Security Policy

We take the security of GateKeeper seriously. As an authorization proxy that sits in
front of MCP servers, GateKeeper is itself a security control — so vulnerabilities in
it can have outsized impact. This document explains how to report a vulnerability and
what to expect when you do.

## Supported Versions

The project is pre-1.0 and ships from `main`. Security fixes are applied to the latest
`main` only. Tagged releases will be listed here once they exist.

| Version | Supported |
| ------- | --------- |
| `main`  | ✅        |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report privately via either channel:

- **GitHub** — use the **"Report a vulnerability"** button under the repository's
  **Security** tab (GitHub Private Vulnerability Reporting).
- **Email** — `kishorekv2@gmail.com` with the subject line `SECURITY:` followed by a
  short description.

Please include, where possible:

- The component affected (MCP proxy, authorization/policy engine, RBAC, audit ledger,
  OIDC/auth, HTTP/stdio transport, etc.).
- Steps to reproduce, or a proof-of-concept.
- The impact you believe it has (authorization bypass, privilege escalation, tool/
  surface enumeration, audit tampering, data exposure, RCE, etc.).
- Any suggested remediation.

## What to Expect

| Stage                  | Target                    |
| ---------------------- | ------------------------- |
| Acknowledgement        | within 3 business days    |
| Initial assessment     | within 7 business days    |
| Fix or mitigation plan | communicated after triage |

We will keep you informed of progress and let you know when the issue is resolved.
We support coordinated disclosure: please give us a reasonable window to ship a fix
before any public write-up.

## Scope

In scope: the application code in this repository — the MCP authorization proxy,
policy/RBAC enforcement, audit ledger, authentication (OIDC) and transport layers,
and any path where a denied action could be made to succeed (authorization bypass) or
a permitted surface could be leaked (enumeration).

Out of scope: third-party services and dependencies (report those upstream), the
backing MCP servers GateKeeper proxies, and findings that require physical access or
a compromised host.

## Recognition

We are grateful to researchers who report responsibly. With your permission we are
happy to credit you once a fix has shipped.
