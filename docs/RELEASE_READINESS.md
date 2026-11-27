# Madar Backend Release Readiness

## Current package boundary

This package completes the backend-oriented project phases 1–6. It is the consolidated working baseline for the remaining work.

- Completed: database foundation, Arabic HTR baseline, image/HTR backend processing, objective/rubric grading baseline, academic management/access control, reporting/analytics/exports.
- Intentionally left: Phase 7 Arabic RTL user interfaces and Phase 8 end-to-end integration/release validation.
- Deferred expansion: HTR training/fine-tuning, representative accuracy validation, and a trained semantic grading model/language-model connection.

This is not represented as a finished end-user desktop/web product because the teacher-facing interface and final integrated workflow are not included yet.

## Windows setup

From PowerShell in the extracted project root:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Verify the delivered backend

```powershell
.\scripts\verify_backend.ps1
```

The verification script runs compilation, the full pytest suite, SQLite integrity, and foreign-key checks. The expected current automated result is **61 passed**.

## Test the local HTR model separately

```powershell
python -m ai_engine.htr.smoke_test .\docs\demo_answer_page.png
```

A successful inference confirms the ONNX model can be loaded and executed on that machine. It does not establish production handwriting accuracy; the included user-confirmed golden set is only two samples.

## Start the local API

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

- API documentation: `http://127.0.0.1:8000/docs`
- Health endpoint: `http://127.0.0.1:8000/health`

Keep the service bound to `127.0.0.1`. Do not expose it to a LAN or the public internet before Phase 8 security and deployment review.

## First administrator

If the database has no Admin account, use the one-time endpoint `POST /api/v1/auth/bootstrap-admin` as documented in `README.md`. Then create a Teacher account through `POST /api/v1/auth/users`. The legacy sample `demo_teacher` account has a placeholder password hash and is not a valid login.

## Data-preservation note

Phase 6 implementation and tests do not modify the packaged sample database or its schema. Tests create isolated temporary databases. Back up the local `storage/` directory before using real student records.
