# Madar Database Baseline v1.0

## Status
Candidate unified baseline for team review. It is not a migration script for an existing populated database.

## Files
- `backend/app/database/schema.sql`: initial SQLite schema.
- `backend/tests/test_schema_integrity.py`: standard-library integrity tests.

## Main design decisions
1. The SQL schema is the implementation source of truth; the Logical Design and ERD must be updated to match it.
2. Existing naming style is retained where possible: `AnswerSheetId`, `ProcessingStatus`, `IsBlankOrUnreadable`, `AuditLogId`, and `CreatedAt`.
3. Machine-readable status values are stored in English. The Arabic UI should translate them for teachers.
4. `QuestionAnswerPages` supports one answer spanning multiple pages and multiple regions. Coordinates are normalized from 0 to 1 relative to the source page.
5. `AnswerCriterionEvaluations` stores criterion-level marks, evidence, explanation, confidence, and current/history state.
6. `AIProcessingRuns` records processing stage, model and prompt versions, status, timing, outputs, and errors.
7. Question types are represented by `QuestionType`; objective choices and accepted text variants have dedicated tables.
8. Cross-exam answer links and cross-sheet page links are rejected by triggers.
9. Score bounds, rubric totals, exam totals, and the specified Teacher-adjustment/Admin-approval roles are protected by database constraints/triggers. Backend authorization must enforce the same rules at the API boundary.
10. `PRAGMA foreign_keys = ON` must be executed for every SQLite connection. The pragma in the schema file only protects the initialization connection.

## Validation
The schema was executed against an in-memory SQLite database. The included test suite checks schema creation, sample grading flow, cross-exam links, cross-sheet page links, score bounds, rubric bounds, role restrictions, and foreign-key integrity.

Run from the project root after placing the files in the official structure:

```powershell
py backend/tests/test_schema_integrity.py
```

## Important deployment warning
Do not overwrite an existing database containing real student or exam data with this initial schema. The current project schema has different columns and relationships. If a database file already contains data, prepare and test a versioned migration with a backup first.

## Backend responsibilities not replaced by SQL
- Authenticate users and authorize every API request.
- Validate that MCQ/True-False questions have the required choices and exactly one correct option before publishing.
- Validate that Fill-in-the-Blank questions have accepted answers.
- Validate that essay/assignment questions have suitable grading criteria before processing.
- Write audit records for teacher edits, score adjustments, approvals, and reprocessing.
- Update `AnswerSheets.ProcessingStatus` and timestamps consistently.
- Keep file paths relative to the configured Madar storage root and prevent path traversal.

## Status-value mapping from the previous SQL draft

If migrating rows from the earlier Arabic-valued draft, map values as follows:

| Previous Arabic value | v1.0 machine value |
|---|---|
| لم تتم المعالجة | NOT_PROCESSED |
| تمت المعالجة | PROCESSED |
| بانتظار المراجعة | PENDING_REVIEW |
| تمت المراجعة | REVIEWED |
| تم الاعتماد النهائي | FINALLY_APPROVED |
| صالحة | VALID |
| منخفضة الجودة | LOW_QUALITY |
| غير صالحة | INVALID |
| ناجح | SUCCESS |
| فشل | FAILED |

Do not apply these mappings by hand to a live database. Implement them in a tested migration transaction after taking a verified backup.

## DatabaseManager
- `backend/app/database/database_manager.py` owns initialization, connections, backup, and restore.
- The default database path is `storage/SmartArabicGraderDB.sqlite3`.
- The manager creates `storage/original_images`, `storage/processed_images`, `storage/exports`, and `storage/backups`.
- Existing databases are validated and never overwritten by `initialize_database()`.
- Backups and restore sources are checked with `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, and `SchemaMigrations` before use.
- Run manager tests from the package root:

```powershell
py -m unittest backend.tests.test_database_manager -v
```
