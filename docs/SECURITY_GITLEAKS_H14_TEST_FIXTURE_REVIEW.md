# Security review · H14/3H Gitleaks legacy test fixture

## What was found

GitHub Actions, **CI modular → Seguridad · detectar secretos**, uses pinned Gitleaks 8.30.1 with **full Git history** (`actions/checkout fetch-depth: 0` and `gitleaks git --redact=100 --no-banner --verbose .`). A single match for rule `generic-api-key` is reported for the following historical exploratory branch commit:

- Commit: `6a2973f590ecd3ef3fdda83cef54861489241a97` (2026-10-19 H14/3H)
- File: `.github/scripts/ci_dbi_scientific_raster_reviewed_live_audit.py`
- Line: 14; precise source: `os.environ.setdefault("JWT_SECRET", "test")`.
- Rule: `generic-api-key`.
- Fingerprint: `6a2973f590ecd3ef3fdda83cef54861489241a97:.github/scripts/ci_dbi_scientific_raster_reviewed_live_audit.py:generic-api-key:14`.

The script's literal value **test** is a local CI test placeholder, not an operational JWT signing key; the same script also sets `DATABASE_URL` to `sqlite:///:memory:` and uses in-memory test stores and mocks. It is not on `main` and is not used as a production configuration. Reviewed from GitHub source and Gitleaks logs; no actual application secret value was disclosed.

## Narrow treatment

A **single exact, four-part commit/file/rule/line fingerprint** is placed in root `.gitleaksignore`, with no wildcard, directory-level allowance or general rule exemption. The CI continues to run the same pinned Gitleaks binary against its full fetched Git history. Any different leak, even on the same file/line in a different commit, remains a finding.

This is a **documented reviewed false-positive exception**; it is not a claim that no secrets have ever existed, a modification to historical commits, or a reason to bypass future security review. If the scanner flags anything else, keep the CI red and investigate; don't generalize this exemption.

## Guardrails, acceptance, and caveats

1. Verify Gitleaks `secrets` job turns green with the identical `fetch-depth:0`, `git` and `--redact=100` invocation. Do not edit CI scanning command to narrow to the PR head.
2. Review the exact line, test-only access and scope again before considering this exception approved; have a security reviewer acknowledge the entry.
3. Never copy `JWT_SECRET="test"` into runtime configurations. Control Center loads local secrets from a user-protected encrypted CLIXML location.
4. Don't rewrite force-push the H14 stacked history, change JWT production secrets, or move H14 into `main` just to silence one scan.
5. If the literal unexpectedly corresponds to a deployed credential, treat it as a real exposure: revoke/rotate it, remove this ignore and investigate operational history. The current reviewed evidence does **not** indicate this.

No code or workflow permissions change: only a **precise reviewed fingerprint** and these notes. PR should remain draft until approval; no DB migrations, Render, merges or multipart grants.
