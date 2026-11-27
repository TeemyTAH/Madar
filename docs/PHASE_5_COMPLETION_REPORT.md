# Madar — Phase 5 Completion Report

## Phase

**Phase 5: Academic Management — Students, Exams, Enrollments, Answer Sheets, and Grades**

Status: **Implemented and locally tested**

## 1. Scope delivered

### Authentication and role enforcement

- Added first-administrator bootstrap. Bootstrap is available only while no administrator account exists; legacy non-admin accounts are preserved.
- Added password hashing with PBKDF2-HMAC-SHA256 and per-password random salts.
- Added signed Bearer access tokens using HMAC-SHA256, with an eight-hour lifetime.
- Added a per-install signing secret in `storage/.madar_auth_secret`; this file is generated at first startup and excluded from version control/package delivery.
- Added login, current-user, and administrator-only user creation endpoints.
- Protected all `/api/v1/*` endpoints except the first-admin bootstrap and login endpoints.
- Added an OpenAPI HTTP Bearer security scheme so Swagger UI exposes its Authorize control.
- Active-user status is checked against the database on every authenticated API request.

### Student management

- Create, list/search, retrieve, update, and delete students.
- Pagination with bounded `limit` and `offset`.
- Duplicate academic IDs are rejected.
- Students linked to exams cannot be deleted.
- Mutations are written to `AuditLogs`.

### Exam management

- Create, list/search, retrieve, update, and delete exams.
- ISO date/date-time validation for `ExamDate`.
- Question mark allocations remain bounded by exam total marks through existing SQLite triggers.
- Exams with enrollments cannot be deleted.
- Mutations are audited.

### Question configuration

- Create, list, retrieve, update limited descriptive/mark fields, and delete unattempted questions.
- Objective question creation validates choice count and exactly one correct option.
- Fill-in-the-blank questions require accepted-answer variants.
- Short-answer questions require either accepted answers or rubric criteria.
- Essay and assignment questions require rubric criteria; essay questions also require a model answer.
- Rubric criterion allocations must sum to the question maximum and include descriptions.
- New questions are backfilled into existing answer sheets for that exam.
- Questions with student answers cannot be deleted.

### Enrollments and answer sheets

- Bulk student enrollment is idempotent and reports newly added versus existing enrollments.
- Enrollment removal is blocked once an answer sheet exists.
- One answer sheet per exam enrollment is enforced transactionally by the service.
- Creating an answer sheet initializes one `QuestionAnswers` record per exam question.
- Upload-created answer sheets now initialize the same answer records.
- Adding questions after answer-sheet creation backfills missing answer rows.

### Grade review and gradebook

- Teachers can update a student's response before final approval.
- Response changes invalidate previous suggested and adjusted grades and return the sheet to pending review.
- Teachers can submit adjusted scores only within question mark limits; the database also enforces the active-Teacher rule.
- Administrators can approve final scores; the database also enforces the active-Admin rule.
- Answers requiring review cannot be approved from a suggestion alone; an administrator may explicitly override with a score and a required approval note.
- A sheet becomes `FINALLY_APPROVED` only when all its answer rows are approved.
- Exam results distinguish final approved score from provisional score. Final score is null until every configured question is approved.
- Grade changes and approvals are audited.

## 2. Main API routes

All routes are under `/api/v1`.

### Authentication

- `POST /auth/bootstrap-admin`
- `POST /auth/login`
- `GET /auth/me`
- `POST /auth/users` (Admin only)

### Academic management

- `GET|POST /academic/students`
- `GET|PATCH|DELETE /academic/students/{student_id}`
- `GET|POST /academic/exams`
- `GET|PATCH|DELETE /academic/exams/{exam_id}`
- `POST /academic/exams/{exam_id}/enrollments`
- `GET /academic/exams/{exam_id}/enrollments`
- `DELETE /academic/exams/{exam_id}/enrollments/{student_id}`
- `POST /academic/exams/{exam_id}/questions`
- `GET /academic/exams/{exam_id}/questions`
- `GET|PATCH|DELETE /academic/questions/{question_id}`
- `POST /academic/exams/{exam_id}/answer-sheets`
- `GET /academic/exams/{exam_id}/answer-sheets`
- `GET /academic/answer-sheets/{answer_sheet_id}`
- `GET /academic/answer-sheets/{answer_sheet_id}/answers`
- `PATCH /academic/answers/{answer_id}/response`
- `PATCH /academic/answers/{answer_id}/grade` (Teacher only)
- `POST /academic/answers/{answer_id}/approve` (Admin only)
- `GET /academic/exams/{exam_id}/results`

## 3. Role matrix

| Operation | Admin | Teacher | Reviewer |
|---|---:|---:|---:|
| Read academic records and gradebook | Yes | Yes | Yes |
| Create/update students and exams | Yes | Yes | No |
| Enroll students and configure questions | Yes | Yes | No |
| Update answer response | Yes | Yes | No |
| Adjust score | No | Yes | No |
| Approve final score | Yes | No | No |
| Create user accounts | Yes | No | No |
| Delete students/exams | Yes | No | No |

The database's existing triggers remain the final guard for Teacher score adjustment and Admin final approval. Reviewer accounts cannot upload pages or trigger AI/HTR/grading operations.

## 4. Database and compatibility

- No schema migration was required for Phase 5.
- The existing schema and database file were not rewritten by Phase 5 tests.
- Existing non-admin user records are preserved. If the packaged database has no Admin account, the first-admin bootstrap creates one without deleting legacy Teacher or Reviewer rows.
- The legacy `demo_teacher` row in the supplied sample database has a placeholder password hash and is not a usable login account. Bootstrap an Admin, then create a real Teacher account through `/auth/users`.
- A new per-install signing secret is generated at runtime under `storage/`; it is not included in the ZIP.

## 5. Verification

- `python -m compileall -q backend ai_engine` — PASS
- `python -m pytest -q` — **53 passed**
- Academic lifecycle tests — PASS
- Authentication and role enforcement tests — PASS
- Question validation and mark-boundary tests — PASS
- Answer-sheet initialization and late-question backfill tests — PASS
- Teacher adjustment and Admin approval workflow — PASS
- Upload-created answer initialization — PASS
- OpenAPI Bearer security scheme — PASS

The HTR ONNX smoke test remains a separate machine-dependent check requiring ONNX Runtime and the model files. Phase 5 does not train or alter any AI model.

## 6. Security and deployment boundary

- Keep the API bound to `127.0.0.1` unless HTTPS, network-level controls, backup policy, and production hardening have been reviewed.
- Protect `storage/.madar_auth_secret`; deleting it invalidates all currently issued Bearer tokens.
- Tokens expire after eight hours. There is no refresh-token or logout/revocation endpoint in this phase.
- Rate limiting, password reset, multi-factor authentication, and account lockout remain future security-hardening work.
- The first-admin bootstrap is intended for first local setup only and is disabled after an Admin record exists.

## 7. Start-up and first login (Windows PowerShell)

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

If no Admin account exists, create one once:

```powershell
$body = @{
  username = "madar_admin"
  full_name = "Madar Administrator"
  password = "ChangeThisToAUniquePassword#2026"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/auth/bootstrap-admin" -ContentType "application/json" -Body $body
```

Use the returned `access_token` as a Bearer token in Swagger UI (`/docs`) or API clients. Create a real Teacher account through `POST /api/v1/auth/users` while authenticated as Admin.

Change the example password before use; never reuse the example value.
