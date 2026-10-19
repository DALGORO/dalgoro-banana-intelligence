# H14 scientific stack — composite CI-only review

## Purpose
Standalone branch derived from **PR #279 top H14/3H** at `4df477698fbebbfbb3d4dbe1c92d839e8b62a0e1`, containing only the verified MinIO CI security hardening from updated PR #269: job-scoped `permissions: contents: read` and checkout `persist-credentials: false`. The H14 stack already contains a **single exact historical Gitleaks fingerprint** in `.gitleaksignore`, unchanged here. Thus the Gitleaks exception was not broadened or duplicated.

## CI targets
- Real ephemeral MinIO multipart begin/list/abort in GitHub runner, loopback only, no DALGORO credentials or production objects.
- Independent H14 3H API/observation read-only mock tests on the stacked branch, plus all ordinary frontend/backend and geospatial checks.
- Verify the top stack and #269 security hardening can coexist; **not** a new permission to merge intermediate branches.
- PR #287 independently triggers the exact #269 SHA to test its own MinIO workflow. It may remain security-red because that older stack does not itself include #279's precise `.gitleaksignore`.

## Deferred gates (NOT satisfied by green CI)
1. Live combined PostgreSQL/PostGIS and MinIO S3 failure/concurrency trials with real locally-scoped resources: uncertain commits, expired grants, revocations, parallel requests, interrupted multipart, crash recovery and cleanup rules.
2. Review duplicate/alternative #271 relative to #270; preserve the stacked sequence #259→#262→#263→#264→#265→#266→#267→#268→#269→#270→#272→#274→#275→#277→#279.
3. Independent institutional signoff, exact asset ownership, authorized retention and permission matrix. Never infer permission from a SQL/S3 read-only observation.
4. No real TIFF reception, S3 production grants or aborts/cleanup, no `main` integration, migration or Render without express permission.

This is a **CI-only draft PR**. Do not merge it.
