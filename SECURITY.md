# Security policy

Lab Notebook stores people's experiments and has accounts, so security problems matter. Thank you for reporting them
responsibly.

## Reporting a problem

Please **don't open a public issue** for a security problem. Report it privately instead:

- **GitHub:** [Report a vulnerability](https://github.com/mcaragon/lab-notebook/security/advisories/new) (Security tab →
  *Report a vulnerability*). Only the maintainer sees it.

Useful to include: what an attacker can do (for example read another account's experiments), the steps or requests
that show it, and the version (shown in the app's user menu).

You'll get an answer within a few days. Fixes are released as a new version and credited in the advisory, unless you'd
rather stay anonymous.

## Scope

In scope: the Lab Notebook app in this repository (sign-in, sessions, invites, access between accounts, the admin
dashboard, report generation, file downloads).

Out of scope: PubChem Local itself, your reverse proxy or tunnel configuration, and denial of service through sheer
volume of requests.

## Supported versions

Only the latest release (the `latest` Docker image) gets security fixes.
