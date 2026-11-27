# Madar — Phase 6 Completion Report

## Phase

**Phase 6: Reports, Analytics, and Approved-Grade Exports**  
Status: **Implemented and locally tested**

## Scope delivered

### Institution overview

- Counts for students, exams, active teachers, enrollments, answer sheets, pages, answer records, approved answers, OCR review queue, grading review queue, fully approved sheets, and failed AI runs.
- Five most recent exams with enrollment and answer-sheet counts.

### Exam analytics

- Enrollment and answer-sheet completion metrics.
- Finalized versus pending results.
- Pass/fail counts and pass rate against a configurable threshold (default 50%).
- Mean, median, minimum, maximum, and average percentage for fully approved final results.
- Score distribution in six percentage bands.
- Per-question response count, approved count, pending count, average approved score, average percentage, full-mark count, zero-mark count, empty answers, and pending grading-review count.
- Three hardest questions ranked by lowest average percentage, with approved sample counts available for interpretation.
- Page-quality, OCR-review, grading-review, empty-answer, and failed-AI-run indicators.

### Student transcript

- Enrollment history across exams.
- Per-exam completion status and final approved score/percentage.
- Average, highest, and lowest percentage across finalized exams.

### Teacher activity report

- Created-exam and enrollment counts, answer-sheet totals, pending review workload, teacher-reviewed and adjusted-answer counts, finalized student-result counts, and average percentage across finalized results.
- Recent exam list and activity-event counts sourced from `AuditLogs`.
- Admins can view any teacher report; a Teacher can view only their own report.

### Exports

- Excel workbook with four worksheets: Arabic gradebook, question analysis, exam summary, and score distribution.
- CSV export encoded as UTF-8 with BOM to preserve Arabic text in common spreadsheet applications.
- Right-to-left worksheet direction, filters, frozen panes, readable widths, number formats, and percentage data bars in Excel.
- Every successful export is recorded in `AuditLogs` with actor, exam, format, filename, and approved-only policy metadata.
- Spreadsheet formula-injection protection prefixes potentially executable text cells before writing CSV/XLSX.

## Final-score safety and calculation rules

- A student's final total is emitted only when at least one question is configured and every configured question has an approved score.
- Per-question export values are populated only when that individual answer is approved.
- Suggested scores and teacher-adjusted but unapproved scores are never included in final statistics, transcripts, or exports.
- Pass rate uses finalized students as its denominator; pending students are not treated as failures.
- Question difficulty is based on approved answers only and is returned with the approved sample count.
- Exams with no enrolled students or no approved results return null averages/pass rates and empty ranked-question lists rather than fabricated zero averages.

## API routes

All routes are under `/api/v1` and require a Bearer token. Overview/exam/student/gradebook routes allow Admin, Teacher, and Reviewer; teacher activity reports allow Admin or the matching Teacher only.

- `GET /reports/overview`
- `GET /reports/exams/{exam_id}/analytics?pass_threshold_percent=50`
- `GET /reports/exams/{exam_id}/gradebook`
- `GET /reports/students/{student_id}`
- `GET /reports/teachers/{teacher_id}` (Admin; Teacher self-access only)
- `GET /reports/exams/{exam_id}/export?format=xlsx`
- `GET /reports/exams/{exam_id}/export?format=csv`

## Database compatibility

- No schema migration was required.
- No existing tables or student/exam/answer records were rewritten.
- Export activity reuses the existing `AuditLogs` table.
- The sample SQLite database remains unchanged by Phase 6 implementation and tests; tests use isolated temporary databases.

## Verification

- Python compilation — PASS.
- Complete pytest suite — **61 passed**.
- Fully approved versus pending score separation — PASS.
- Pass threshold and pass-rate denominator — PASS.
- Question difficulty ordering and approved-only statistics — PASS.
- Student transcript pending/final behavior — PASS
- Teacher activity report and self-only authorization — PASS.
- Excel generation and four-sheet workbook validation — PASS.
- CSV Arabic UTF-8 BOM and pending-score omission — PASS.
- Export audit logging — PASS
- Spreadsheet formula-injection neutralization — PASS.
- Authenticated API route behavior — PASS.
- Empty-exam analytics — PASS.

## Explicitly deferred

- Phase 7: Arabic RTL teacher-facing interface.
- Phase 8: final UI/API/AI integration and end-to-end release validation.
- Training/fine-tuning of HTR or semantic grading models remains expansion work; this phase does not claim model accuracy improvements.
