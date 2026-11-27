# Madar Project Status

## Delivery state

- Phase 1 — Database foundation and integrity: completed baseline; original schema and database preserved.
- Phase 2 — Arabic HTR engine: implemented; actual ONNX smoke test remains dependent on the target machine and representative handwriting validation.
- Phase 3 — Backend image/HTR processing integration: implemented and covered by tests.
- Phase 4 — Objective grading and review-only rubric baseline: implemented and covered by tests.
- Phase 5 — Academic management and access control: implemented and covered by tests.
- Phase 6 — Reports, analytics, and exports: implemented and covered by tests.
- Phase 7 — Arabic RTL React interface: implemented with login/bootstrap, role-aware navigation, dashboard, student/exam/question management, enrollments, answer upload, OCR/answer review, grade review/approval, reports, and exports.
- Phase 8 — Frontend/API/database integration: implemented for the local-first workflow. The browser calls authenticated REST endpoints; it never connects to SQLite directly. Added authenticated page listing and image-serving routes so teachers can inspect the source answer pages and map answer regions.

## Current verification

- `python -m compileall -q backend ai_engine` — PASS
- `python -m pytest -q` — 63 passed
- Database schema integrity tests — PASS
- Database manager tests — PASS
- Academic lifecycle and authentication tests — PASS
- Reporting calculations and final-score exclusion tests — PASS
- XLSX workbook generation and worksheet validation — PASS
- UTF-8 BOM CSV export validation — PASS
- Export audit logging — PASS
- OpenAPI route registration for page listing and protected image delivery — PASS
- New API integration tests for page listing, original/processed image delivery, and path traversal protection — PASS
- Frontend `npm ci`, ESLint, and production Vite build — pending verification on the target Windows machine using `scripts/verify_frontend.ps1`; the package registry was not reachable from the build environment used for this handoff.

## Important limitations

- HTR accuracy is not established by the two-line golden sample; the current model is a baseline only.
- Rubric evaluation is a transparent lexical evidence-overlap heuristic, not a trained semantic understanding model.
- Model training/fine-tuning and language-model integration are deferred to the expansion/integration work.
- API authentication/authorization is implemented, but production hardening remains necessary: HTTPS, network controls, rate limiting, password reset, token revocation, and backup policy.
- The initial Admin account must be bootstrapped once if no Admin record exists. The supplied sample `demo_teacher` has a placeholder password hash and is not a usable login.
- Final score statistics and exports intentionally exclude all unapproved scores. A student's total appears only when every configured question has a final approved score.

## Remaining release validation

1. Run `scripts/verify_frontend.ps1` on Windows to install the locked frontend dependencies, run ESLint, and build the production bundle.
2. Start the backend and frontend in two terminals and complete a real browser workflow: bootstrap/login, create student and exam, configure questions, enroll, upload a real answer page, map regions, run HTR, review text, evaluate, adjust/approve scores, and export a gradebook.
3. Run the ONNX HTR smoke test with representative local handwriting samples and expand the golden dataset before making accuracy claims.
4. Complete production hardening before any public deployment: HTTPS, network controls, rate limiting, token lifecycle, and verified backup/recovery.

The frontend/API integration is implemented in this package; these remaining checks are release validation on the target Windows environment, not a claim that HTR accuracy or production deployment has already been validated.
