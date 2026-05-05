# SECURITY.md

# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in `life-dashboard`, please **do not open a public GitHub issue**.

Instead, report it privately by emailing:

**[dev@brandonolin.com]**

Please include as much of the following information as you can:

- a clear description of the issue
- steps to reproduce it
- affected files, routes, features, or components
- any proof-of-concept, logs, screenshots, or sample payloads
- the version, commit, or branch where you found it
- any ideas you have about severity or possible fixes

A good-faith private report is appreciated and will be taken seriously.

## What to Expect

After a report is received:

- an acknowledgment should be sent within a reasonable time
- the issue will be reviewed and triaged
- follow-up questions may be asked if more detail is needed
- a fix timeline will be determined based on severity, scope, and project capacity

Because this is an early-stage project maintained by a small team, response times may vary.

## Disclosure Policy

Please allow time for the issue to be investigated and, if necessary, patched before making details public.

The general preference is for coordinated disclosure:

1. receive the report privately
2. confirm and assess the issue
3. prepare and release a fix if needed
4. disclose the issue publicly once users have had a reasonable opportunity to update

## Scope

This policy applies to security issues in the code and configuration contained in this repository.

Examples may include:

- authentication or authorization flaws
- privilege escalation paths
- sensitive data exposure
- insecure default configuration
- vulnerable dependency usage, when materially affecting the project
- injection, request forgery, or other application-level vulnerabilities

If you are unsure whether something is a security issue, it is still better to report it privately first.

## Out of Scope

The following are generally out of scope unless they clearly create a real security impact in this project:

- purely theoretical issues without a plausible exploit path
- best-practice suggestions without an identifiable vulnerability
- reports about third-party services not controlled by this project
- social engineering or phishing attempts unrelated to the repository itself
- denial-of-service findings that require unrealistic resources or non-default deployments

## Supported Versions

This project is still early and does not yet have a formal long-term support policy.

At this stage:

- the latest state of the default branch should be treated as the primary supported version
- older commits, forks, and experimental branches may not receive security fixes

Once stable releases exist, this section should be updated with a clearer support matrix.

## Security Practices

Repository users and contributors are encouraged to:

- avoid committing secrets, tokens, passwords, or private keys
- review dependency updates carefully
- use least-privilege credentials in development and deployment
- keep self-hosted deployments behind appropriate authentication and network protections
- update promptly when security-related fixes are published

## Thanks

Responsible disclosure helps protect users, contributors, and self-hosters. Thank you for reporting security issues privately and constructively.