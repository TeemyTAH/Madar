# Changelog

## 1.2.0 — Phase 5 Academic Management

- Added PBKDF2 password hashing, HMAC Bearer tokens, first-admin bootstrap, login, and admin-only user creation.
- Added authentication middleware for all versioned API routes and documented Bearer security in OpenAPI.
- Added student, exam, question, enrollment, answer-sheet, and gradebook APIs.
- Added objective/accepted-answer/rubric question configuration validation.
- Added teacher response editing and score adjustment, plus admin final-score approval.
- Added audit logging for academic mutations and grade decisions.
- Answer-sheet creation and uploads now initialize per-question answer rows; newly added questions backfill existing sheets.
- Added Phase 5 integration and authorization tests.
- Verification: 53 pytest tests passed.

## 1.1.0 — Phases 2–4

- Added Arabic HTR inference, page segmentation, and processing-run persistence.
- Added deterministic objective grading and a review-only rubric evidence baseline.
- Added upload, HTR, answer-region, and grading API routes.


## 1.3.0 — Phase 6: Reports and Analytics

- Added authenticated reporting endpoints for institution overview, exam analytics, question difficulty, student transcripts, teacher activity reports, and gradebooks.
- Added Excel exports with Gradebook, Question Analysis, Summary, and Score Distribution worksheets.
- Added UTF-8 BOM CSV exports for Arabic compatibility.
- Enforced final-approval-only totals and per-question export values; provisional scores are excluded.
- Added audit events for successful gradebook exports.
- Added reporting regression tests for analytics, pending/final separation, teacher self-access, exports, formula-injection protection, API authentication, and empty exams.
- Kept the teacher-facing interface (Phase 7) and final end-to-end integration/release validation (Phase 8) pending by design.


## 1.4.0 — Phases 7–8: Arabic RTL UI and API integration

- Replaced the default React/Vite starter screen with the Madar Arabic RTL workspace.
- Added session-based login and first-admin bootstrap UI, with role-aware Admin/Teacher/Reviewer navigation.
- Connected dashboard, student and exam management, question setup, student enrollment, answer-page uploads, answer-sheet review, grading, final approval, reporting, and Excel/CSV downloads to the existing API.
- Added a crop/region selector that saves normalized answer regions and calls answer-level HTR.
- Added authenticated answer-sheet page listing without exposing filesystem paths.
- Added authenticated original/processed answer-image delivery constrained to the expected Madar image directories.
- Added frontend development proxy, setup documentation, and a PowerShell lint/build verification script.
- Added API integration tests for page listing, protected image delivery, and storage path traversal protection.
- Verification: 63 backend pytest tests passed. Frontend npm/lint/build verification is pending on the target Windows machine.
