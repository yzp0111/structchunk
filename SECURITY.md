# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.0   | :white_check_mark: |

## Reporting a Vulnerability

**Do not file security bugs as public GitHub issues.** Instead, send a detailed report via email to **564087945@qq.com**.

You will receive an acknowledgment within 48 hours, followed by regular status updates as the issue is triaged and resolved.

Include the following in your report:

- structchunk version
- Python version and platform (OS, architecture)
- A minimal, self-contained reproduction
- Impact assessment (what an attacker could achieve)

## Disclosure Policy

This project follows a **coordinated disclosure** model:

1. The reporter sends the details to the maintainer via email.
2. The maintainer has up to **90 days** to release a fix or, at minimum, a mitigation advisory.
3. After the fix is published, a public CVE may be filed.
4. The reporter is credited in the advisory unless they request anonymity.

## Security Considerations

### Snowflake Clock-Resilience

The Snowflake ID generator inside `structchunk` is designed to never emit a duplicate ID, even when the system clock jumps backward. If the clock regresses (for example, after an NTP correction or a suspend/resume cycle), the generator spin-waits for up to 10ms for the clock to catch up. If the clock does not advance past the last-issued timestamp within that window, a `RuntimeError` is raised. This fail-closed behavior means a stuck or misconfigured clock is surfaced immediately rather than silently producing colliding IDs that could corrupt a database primary key.

### Zero Runtime Dependencies

structchunk has zero runtime dependencies. Only `pytest` is needed for development and testing. This dramatically reduces the supply-chain attack surface: there are no transitive dependencies to audit, no sub-dependency vulnerabilities to track, and no risk of a compromised upstream package injecting malicious code into the chunking pipeline.

### Limited I/O Surface

No file I/O is performed during the core chunking operation. The caller provides the content string directly. The only I/O paths are `chunk_file()` and the CLI entry point, both of which read from a caller-specified file path. As a general precaution, do not pass untrusted files to the chunker without sanitization, and validate that any file read by the CLI is expected input rather than an arbitrary system file.
