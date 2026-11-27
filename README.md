# Madar — Smart Arabic Grader

Local-first Arabic examination processing and grading backend.

## What is implemented in this package

- SQLite database lifecycle and integrity checks.
- Image upload and preprocessing.
- Arabic HTR inference with ONNX Runtime, CTC prefix beam search, and page/line segmentation.
- HTR run tracking in `AIProcessingRuns` and extracted-answer persistence.
- Deterministic grading for multiple-choice, true/false, and accepted-answer questions.
- A conservative rubric evidence-overlap baseline for free-response questions. It is a **preliminary heuristic**, not a trained semantic model, and always requires teacher review.
- API endpoints for upload, HTR, and grading suggestions.
- Academic reporting: exam analytics, question difficulty summaries, student transcripts, and final-grade exports to Excel/CSV.

## Setup (Windows PowerShell)

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Start the local API

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the local OpenAPI page.

## Phase 2 — Arabic HTR smoke test

```powershell
python -m ai_engine.htr.smoke_test
```

Pass another page or line image as an argument:

```powershell
python -m ai_engine.htr.smoke_test .\path\to\answer_page.png
```

The HTR result contains candidate text, line boxes, alternative hypotheses, timing, and a review flag. The confidence is a beam-search posterior over candidate strings; it is not calibrated accuracy.

## Phase 3 — HTR API

- `POST /api/v1/uploads/answer-page`: upload and preprocess an answer page, recording the `IMAGE_PROCESSING` run.
- `POST /api/v1/ai/pages/{page_id}/recognize`: recognize page lines and store the run output.
- `POST /api/v1/ai/answers/{answer_id}/recognize`: recognize only the regions linked through `QuestionAnswerPages`, then store `ExtractedText`, OCR confidence, and review state.

Answer-level OCR requires at least one valid `QuestionAnswerPages` mapping. Coordinates are normalized to the page dimensions; all-null coordinates mean the full page.

## Phase 4 — Grading API

- `POST /api/v1/grading/answers/{answer_id}/evaluate`: create a score suggestion.

Objective questions and configured accepted-answer variants are graded deterministically. Essay/short-answer rubric suggestions use explicit criterion-description token overlap only. Those suggestions are always marked `REQUIRES_REVIEW`; the API never changes `AdjustedScore`, `ApprovedScore`, or `IsApproved`.

## Phase 6 — Reports, analytics, and exports

All report routes require an authenticated Bearer token. Institution/exam/student/gradebook reports allow Admin, Teacher, and Reviewer; teacher activity reports allow Admin or the matching Teacher only.

- `GET /api/v1/reports/overview`: institution-wide counts and recent exams.
- `GET /api/v1/reports/exams/{exam_id}/analytics?pass_threshold_percent=50`: exam statistics, pass/fail rates, score distribution, question analysis, hardest questions, image/OCR/review indicators, and failed AI runs.
- `GET /api/v1/reports/exams/{exam_id}/gradebook`: per-student gradebook data.
- `GET /api/v1/reports/students/{student_id}`: student transcript across enrolled exams.
- `GET /api/v1/reports/teachers/{teacher_id}`: teacher activity/workload report. Admins can view any teacher; teachers can view only their own report.
- `GET /api/v1/reports/exams/{exam_id}/export?format=xlsx` or `format=csv`: downloadable gradebook. Excel includes gradebook, question analysis, summary, and score distribution worksheets; CSV is UTF-8 with BOM for Arabic compatibility.

**Final-grade safety rule:** analytics, transcripts, and exports include a student's final total only after every configured question has an approved score. Individual question scores are exported only when that question is approved. Suggested and teacher-adjusted but unapproved scores are never exported. Each export is recorded in `AuditLogs`.

`openpyxl` is installed through `requirements.txt` for Excel generation.

## Backend release verification

On Windows PowerShell, run the packaged verification script after installing `requirements.txt`:

```powershell
.\scripts\verify_backend.ps1
```

The script checks Python compilation, the complete pytest suite, and SQLite integrity/foreign keys. The HTR model smoke test is separate because it validates actual ONNX inference on the target machine:

```powershell
python -m ai_engine.htr.smoke_test .\docs\demo_answer_page.png
```

## Tests

Run the complete test suite from the project root:

```powershell
python -m pytest -q
```

## Important deployment notes

- The existing database is not migrated or overwritten by this work.
- The package does not contain a trained semantic grading model or language model. Genuine semantic grading, synonym/paraphrase understanding, and model fine-tuning remain expansion work.
- The current HTR model has only a two-line user-confirmed golden sample in the included baseline report. That sample is too small to claim production accuracy.
- API authentication and role-based authorization are implemented in Phase 5. Production deployment hardening is still required; keep this API bound to localhost until HTTPS, network controls, rate limiting, token lifecycle, and backup/recovery policy are reviewed.
- Never use AI suggestions as final grades without teacher review and the existing approval workflow.

The answer-region API used by answer-level HTR is:

- `POST /api/v1/answers/{answer_id}/regions`: create a full-page or normalized rectangular region mapping.
- `GET /api/v1/answers/{answer_id}/regions`: list the mappings for an answer.

## Phase 5 — Academic management and access control

The academic management API is available under `/api/v1/academic`:

- Students: create, search/list, retrieve, update, and guarded deletion.
- Exams: create, list/search, retrieve, update, and guarded deletion.
- Questions: configure MCQ/True-False choices, accepted text variants, and rubric criteria with mark validation.
- Enrollments: bulk register students in an exam.
- Answer sheets: create one sheet per enrollment and initialize answer records for every exam question.
- Grade review: teacher response correction and score adjustment; administrator final approval.
- Gradebook: per-exam provisional and final results. A final total is returned only after every question has an approved score.

### First-time authentication

All `/api/v1/*` endpoints require a Bearer access token, except `POST /api/v1/auth/bootstrap-admin` and `POST /api/v1/auth/login`.

On a new installation, or on a database that does not yet contain an Admin account, create the first administrator once:

```powershell
$body = @{
  username = "madar_admin"
  full_name = "Madar Administrator"
  password = "ChangeThisToAUniquePassword#2026"
} | ConvertTo-Json

$login = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/auth/bootstrap-admin" `
  -ContentType "application/json" -Body $body

$token = $login.access_token
```

Use the returned token in Swagger UI at `http://127.0.0.1:8000/docs` by selecting **Authorize** and entering the Bearer token. An Admin can create Teacher and Reviewer accounts using `POST /api/v1/auth/users`.

The signing key is generated per installation at `storage/.madar_auth_secret`. Keep it private; deleting it invalidates issued tokens. The sample database's legacy `demo_teacher` account has a placeholder password hash and cannot log in; bootstrap an Admin and create a new Teacher account instead.

### Role boundaries

- Admin: academic administration, account creation, and final score approval.
- Teacher: student/exam/question setup, uploads, AI processing, response correction, and score adjustment.
- Reviewer: read-only academic records and gradebook access.

Keep Uvicorn bound to `127.0.0.1` until deployment hardening is complete.


## Phase 7/8 — Frontend integration

The Arabic RTL React interface is in `frontend/`. It communicates with the FastAPI backend through `/api/v1`; the browser never opens the SQLite file directly.

Start the backend from the project root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite development proxy forwards `/api/v1` and `/health` to `http://127.0.0.1:8000`. See `frontend/README.md` for first-admin setup, workflows, and deployment notes.

The integration adds:
- `GET /api/v1/academic/answer-sheets/{answer_sheet_id}/pages` to list sheet pages without disclosing stored filesystem paths.
- `GET /api/v1/uploads/pages/{page_id}/image?variant=original|processed` to serve registered answer images to authenticated academic users. Stored paths are constrained to Madar's storage directories.

The complete backend test suite includes integration tests for the new page listing and protected image endpoints. Run the frontend lint/build check from PowerShell with `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; .\scripts\verify_frontend.ps1`.
