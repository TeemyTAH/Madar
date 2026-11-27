-- Madar / SmartArabicGraderDB
-- Candidate unified schema v1.0
-- SQLite. Enable foreign keys on EVERY connection, not only during initialization.
PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE SchemaMigrations (
    Version INTEGER PRIMARY KEY,
    Description TEXT NOT NULL,
    AppliedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE Users (
    UserId INTEGER PRIMARY KEY AUTOINCREMENT,
    Username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    FullName TEXT NOT NULL,
    PasswordHash TEXT NOT NULL,
    RoleName TEXT NOT NULL DEFAULT 'Teacher'
        CHECK (RoleName IN ('Admin', 'Teacher', 'Reviewer')),
    IsActive INTEGER NOT NULL DEFAULT 1 CHECK (IsActive IN (0, 1)),
    CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    LastLoginAt TEXT
);

CREATE TABLE Students (
    StudentId INTEGER PRIMARY KEY AUTOINCREMENT,
    AcademicId TEXT NOT NULL UNIQUE,
    FullName TEXT NOT NULL,
    CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE Exams (
    ExamId INTEGER PRIMARY KEY AUTOINCREMENT,
    CreatedByUserId INTEGER,
    Title TEXT NOT NULL,
    SubjectName TEXT NOT NULL,
    ExamDate TEXT,
    TotalMarks NUMERIC NOT NULL CHECK (TotalMarks > 0),
    CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (CreatedByUserId) REFERENCES Users(UserId) ON DELETE SET NULL
);

CREATE TABLE ExamStudents (
    ExamStudentId INTEGER PRIMARY KEY AUTOINCREMENT,
    ExamId INTEGER NOT NULL,
    StudentId INTEGER NOT NULL,
    FOREIGN KEY (ExamId) REFERENCES Exams(ExamId) ON DELETE CASCADE,
    FOREIGN KEY (StudentId) REFERENCES Students(StudentId) ON DELETE NO ACTION,
    UNIQUE (ExamId, StudentId)
);

CREATE TABLE Questions (
    QuestionId INTEGER PRIMARY KEY AUTOINCREMENT,
    ExamId INTEGER NOT NULL,
    QuestionNumber INTEGER NOT NULL CHECK (QuestionNumber > 0),
    QuestionType TEXT NOT NULL DEFAULT 'ESSAY'
        CHECK (QuestionType IN (
            'MULTIPLE_CHOICE', 'TRUE_FALSE', 'FILL_BLANK',
            'SHORT_ANSWER', 'ESSAY', 'ASSIGNMENT'
        )),
    QuestionText TEXT NOT NULL,
    ModelAnswer TEXT,
    MaxMarks NUMERIC NOT NULL CHECK (MaxMarks > 0),
    CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ExamId) REFERENCES Exams(ExamId) ON DELETE CASCADE,
    UNIQUE (ExamId, QuestionNumber),
    CHECK (
        QuestionType IN ('MULTIPLE_CHOICE', 'TRUE_FALSE', 'FILL_BLANK', 'ASSIGNMENT')
        OR (ModelAnswer IS NOT NULL AND length(trim(ModelAnswer)) > 0)
    )
);

CREATE TABLE QuestionChoices (
    ChoiceId INTEGER PRIMARY KEY AUTOINCREMENT,
    QuestionId INTEGER NOT NULL,
    ChoiceLabel TEXT NOT NULL,
    ChoiceText TEXT NOT NULL,
    IsCorrect INTEGER NOT NULL DEFAULT 0 CHECK (IsCorrect IN (0, 1)),
    SortOrder INTEGER NOT NULL DEFAULT 1 CHECK (SortOrder > 0),
    FOREIGN KEY (QuestionId) REFERENCES Questions(QuestionId) ON DELETE CASCADE,
    UNIQUE (QuestionId, ChoiceLabel),
    UNIQUE (QuestionId, SortOrder)
);

-- At most one correct choice. Backend must also ensure at least one before publishing.
CREATE UNIQUE INDEX UX_QuestionChoices_OneCorrect
    ON QuestionChoices(QuestionId) WHERE IsCorrect = 1;

CREATE TABLE AcceptedAnswers (
    AcceptedAnswerId INTEGER PRIMARY KEY AUTOINCREMENT,
    QuestionId INTEGER NOT NULL,
    AnswerText TEXT NOT NULL,
    CaseSensitive INTEGER NOT NULL DEFAULT 0 CHECK (CaseSensitive IN (0, 1)),
    NormalizeArabic INTEGER NOT NULL DEFAULT 1 CHECK (NormalizeArabic IN (0, 1)),
    SortOrder INTEGER NOT NULL DEFAULT 1 CHECK (SortOrder > 0),
    FOREIGN KEY (QuestionId) REFERENCES Questions(QuestionId) ON DELETE CASCADE,
    UNIQUE (QuestionId, SortOrder),
    UNIQUE (QuestionId, AnswerText)
);

CREATE TABLE RubricCriteria (
    CriterionId INTEGER PRIMARY KEY AUTOINCREMENT,
    QuestionId INTEGER NOT NULL,
    CriterionTitle TEXT NOT NULL,
    CriterionDescription TEXT,
    AllocatedMarks NUMERIC NOT NULL CHECK (AllocatedMarks >= 0),
    SortOrder INTEGER NOT NULL DEFAULT 1 CHECK (SortOrder > 0),
    FOREIGN KEY (QuestionId) REFERENCES Questions(QuestionId) ON DELETE CASCADE,
    UNIQUE (QuestionId, SortOrder)
);

CREATE TABLE AnswerSheets (
    AnswerSheetId INTEGER PRIMARY KEY AUTOINCREMENT,
    ExamStudentId INTEGER NOT NULL,
    ProcessingStatus TEXT NOT NULL DEFAULT 'NOT_PROCESSED'
        CHECK (ProcessingStatus IN (
            'NOT_PROCESSED', 'PROCESSED', 'PENDING_REVIEW',
            'REVIEWED', 'FINALLY_APPROVED'
        )),
    IsBlankOrUnreadable INTEGER NOT NULL DEFAULT 0
        CHECK (IsBlankOrUnreadable IN (0, 1)),
    Notes TEXT,
    CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ExamStudentId) REFERENCES ExamStudents(ExamStudentId) ON DELETE CASCADE
);

CREATE TABLE AnswerPages (
    PageId INTEGER PRIMARY KEY AUTOINCREMENT,
    AnswerSheetId INTEGER NOT NULL,
    PageNumber INTEGER NOT NULL CHECK (PageNumber > 0),
    OriginalImagePath TEXT NOT NULL,
    PreprocessedImagePath TEXT,
    ImageQualityStatus TEXT NOT NULL DEFAULT 'VALID'
        CHECK (ImageQualityStatus IN ('VALID', 'LOW_QUALITY', 'INVALID')),
    ImageWidth INTEGER CHECK (ImageWidth IS NULL OR ImageWidth > 0),
    ImageHeight INTEGER CHECK (ImageHeight IS NULL OR ImageHeight > 0),
    CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (AnswerSheetId) REFERENCES AnswerSheets(AnswerSheetId) ON DELETE CASCADE,
    UNIQUE (AnswerSheetId, PageNumber)
);

CREATE TABLE QuestionAnswers (
    AnswerId INTEGER PRIMARY KEY AUTOINCREMENT,
    AnswerSheetId INTEGER NOT NULL,
    QuestionId INTEGER NOT NULL,
    SelectedChoiceId INTEGER,
    ExtractedText TEXT,
    EditedText TEXT,
    OcrConfidence NUMERIC
        CHECK (OcrConfidence IS NULL OR (OcrConfidence >= 0 AND OcrConfidence <= 100)),
    NeedsOcrReview INTEGER NOT NULL DEFAULT 0 CHECK (NeedsOcrReview IN (0, 1)),
    IsEmptyAnswer INTEGER NOT NULL DEFAULT 0 CHECK (IsEmptyAnswer IN (0, 1)),
    SuggestedScore NUMERIC CHECK (SuggestedScore IS NULL OR SuggestedScore >= 0),
    SuggestedJustification TEXT,
    EvaluationConfidence NUMERIC
        CHECK (EvaluationConfidence IS NULL OR (EvaluationConfidence >= 0 AND EvaluationConfidence <= 100)),
    NeedsGradingReview INTEGER NOT NULL DEFAULT 0 CHECK (NeedsGradingReview IN (0, 1)),
    ReviewedByUserId INTEGER,
    AdjustedScore NUMERIC CHECK (AdjustedScore IS NULL OR AdjustedScore >= 0),
    TeacherJustification TEXT,
    TeacherNotes TEXT,
    ApprovedByUserId INTEGER,
    ApprovedScore NUMERIC CHECK (ApprovedScore IS NULL OR ApprovedScore >= 0),
    IsApproved INTEGER NOT NULL DEFAULT 0 CHECK (IsApproved IN (0, 1)),
    ApprovedAt TEXT,
    UpdatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (AnswerSheetId) REFERENCES AnswerSheets(AnswerSheetId) ON DELETE CASCADE,
    FOREIGN KEY (QuestionId) REFERENCES Questions(QuestionId) ON DELETE NO ACTION,
    FOREIGN KEY (SelectedChoiceId) REFERENCES QuestionChoices(ChoiceId) ON DELETE NO ACTION,
    FOREIGN KEY (ReviewedByUserId) REFERENCES Users(UserId) ON DELETE NO ACTION,
    FOREIGN KEY (ApprovedByUserId) REFERENCES Users(UserId) ON DELETE NO ACTION,
    UNIQUE (AnswerSheetId, QuestionId),
    CHECK (AdjustedScore IS NULL OR ReviewedByUserId IS NOT NULL),
    CHECK (
        (IsApproved = 0 AND ApprovedScore IS NULL AND ApprovedByUserId IS NULL AND ApprovedAt IS NULL)
        OR
        (IsApproved = 1 AND ApprovedScore IS NOT NULL AND ApprovedByUserId IS NOT NULL AND ApprovedAt IS NOT NULL)
    )
);

-- An answer may occupy multiple regions on one or more pages.
-- Region coordinates are normalized (0..1) relative to the original page dimensions.
CREATE TABLE QuestionAnswerPages (
    AnswerPageSegmentId INTEGER PRIMARY KEY AUTOINCREMENT,
    AnswerId INTEGER NOT NULL,
    PageId INTEGER NOT NULL,
    SegmentOrder INTEGER NOT NULL DEFAULT 1 CHECK (SegmentOrder > 0),
    RegionX REAL,
    RegionY REAL,
    RegionWidth REAL,
    RegionHeight REAL,
    FOREIGN KEY (AnswerId) REFERENCES QuestionAnswers(AnswerId) ON DELETE CASCADE,
    FOREIGN KEY (PageId) REFERENCES AnswerPages(PageId) ON DELETE CASCADE,
    UNIQUE (AnswerId, SegmentOrder),
    CHECK (
        (RegionX IS NULL AND RegionY IS NULL AND RegionWidth IS NULL AND RegionHeight IS NULL)
        OR
        (
            RegionX BETWEEN 0 AND 1 AND RegionY BETWEEN 0 AND 1
            AND RegionWidth > 0 AND RegionHeight > 0
            AND RegionX + RegionWidth <= 1
            AND RegionY + RegionHeight <= 1
        )
    )
);

CREATE TABLE AIProcessingRuns (
    ProcessingRunId INTEGER PRIMARY KEY AUTOINCREMENT,
    AnswerSheetId INTEGER NOT NULL,
    PageId INTEGER,
    AnswerId INTEGER,
    Stage TEXT NOT NULL CHECK (Stage IN (
        'IMAGE_PROCESSING', 'HTR', 'SEMANTIC_EVALUATION', 'RUBRIC'
    )),
    ModelName TEXT,
    ModelVersion TEXT,
    PromptVersion TEXT,
    Status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (Status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'REQUIRES_REVIEW')),
    InputReference TEXT,
    OutputReference TEXT,
    OutputJson TEXT,
    ErrorMessage TEXT,
    StartedAt TEXT,
    CompletedAt TEXT,
    DurationMs INTEGER CHECK (DurationMs IS NULL OR DurationMs >= 0),
    CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (AnswerSheetId) REFERENCES AnswerSheets(AnswerSheetId) ON DELETE CASCADE,
    FOREIGN KEY (PageId) REFERENCES AnswerPages(PageId) ON DELETE CASCADE,
    FOREIGN KEY (AnswerId) REFERENCES QuestionAnswers(AnswerId) ON DELETE CASCADE,
    CHECK (CompletedAt IS NULL OR StartedAt IS NULL OR CompletedAt >= StartedAt),
    CHECK (
        (Stage IN ('IMAGE_PROCESSING', 'HTR') AND PageId IS NOT NULL)
        OR
        (Stage IN ('SEMANTIC_EVALUATION', 'RUBRIC') AND AnswerId IS NOT NULL)
    )
);

CREATE TABLE AnswerCriterionEvaluations (
    EvaluationId INTEGER PRIMARY KEY AUTOINCREMENT,
    AnswerId INTEGER NOT NULL,
    CriterionId INTEGER NOT NULL,
    ProcessingRunId INTEGER,
    EvaluationMethod TEXT NOT NULL DEFAULT 'AUTOMATIC'
        CHECK (EvaluationMethod IN ('AUTOMATIC', 'MANUAL')),
    AwardedMarks NUMERIC NOT NULL CHECK (AwardedMarks >= 0),
    EvidenceText TEXT,
    Explanation TEXT,
    Confidence NUMERIC CHECK (Confidence IS NULL OR (Confidence >= 0 AND Confidence <= 100)),
    IsCurrent INTEGER NOT NULL DEFAULT 1 CHECK (IsCurrent IN (0, 1)),
    CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (AnswerId) REFERENCES QuestionAnswers(AnswerId) ON DELETE CASCADE,
    FOREIGN KEY (CriterionId) REFERENCES RubricCriteria(CriterionId) ON DELETE NO ACTION,
    FOREIGN KEY (ProcessingRunId) REFERENCES AIProcessingRuns(ProcessingRunId) ON DELETE CASCADE,
    UNIQUE (AnswerId, CriterionId, ProcessingRunId),
    CHECK (
        (EvaluationMethod = 'AUTOMATIC' AND ProcessingRunId IS NOT NULL)
        OR (EvaluationMethod = 'MANUAL' AND ProcessingRunId IS NULL)
    )
);

CREATE UNIQUE INDEX UX_AnswerCriterionEvaluations_Current
    ON AnswerCriterionEvaluations(AnswerId, CriterionId) WHERE IsCurrent = 1;

CREATE TABLE AuditLogs (
    AuditLogId INTEGER PRIMARY KEY AUTOINCREMENT,
    PerformedByUserId INTEGER,
    EntityName TEXT NOT NULL,
    EntityId TEXT NOT NULL,
    ActionType TEXT NOT NULL,
    OldValue TEXT,
    NewValue TEXT,
    Details TEXT,
    CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (PerformedByUserId) REFERENCES Users(UserId) ON DELETE SET NULL
);

CREATE TABLE BackupHistory (
    BackupId INTEGER PRIMARY KEY AUTOINCREMENT,
    PerformedByUserId INTEGER,
    BackupFilePath TEXT NOT NULL,
    OperationType TEXT NOT NULL DEFAULT 'BACKUP'
        CHECK (OperationType IN ('BACKUP', 'RESTORE')),
    Status TEXT NOT NULL DEFAULT 'SUCCESS'
        CHECK (Status IN ('SUCCESS', 'FAILED')),
    Notes TEXT,
    CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (PerformedByUserId) REFERENCES Users(UserId) ON DELETE SET NULL
);

-- =========================
-- Business-rule triggers
-- =========================

CREATE TRIGGER TRG_Questions_CheckExamTotal_INSERT
AFTER INSERT ON Questions
BEGIN
    SELECT RAISE(ABORT, 'Question marks exceed the exam total marks.')
    WHERE (
        SELECT COALESCE(SUM(MaxMarks), 0) FROM Questions WHERE ExamId = NEW.ExamId
    ) > (SELECT TotalMarks FROM Exams WHERE ExamId = NEW.ExamId);
END;

CREATE TRIGGER TRG_Questions_CheckExamTotal_UPDATE
AFTER UPDATE OF MaxMarks, ExamId ON Questions
BEGIN
    SELECT RAISE(ABORT, 'Question marks exceed the exam total marks.')
    WHERE (
        SELECT COALESCE(SUM(MaxMarks), 0) FROM Questions WHERE ExamId = NEW.ExamId
    ) > (SELECT TotalMarks FROM Exams WHERE ExamId = NEW.ExamId);
END;

CREATE TRIGGER TRG_Exams_CheckTotalMarks_UPDATE
AFTER UPDATE OF TotalMarks ON Exams
BEGIN
    SELECT RAISE(ABORT, 'Exam total marks cannot be lower than the sum of question marks.')
    WHERE (
        SELECT COALESCE(SUM(MaxMarks), 0) FROM Questions WHERE ExamId = NEW.ExamId
    ) > NEW.TotalMarks;
END;

CREATE TRIGGER TRG_RubricCriteria_CheckQuestionMarks_INSERT
AFTER INSERT ON RubricCriteria
BEGIN
    SELECT RAISE(ABORT, 'Rubric marks exceed the question maximum marks.')
    WHERE (
        SELECT COALESCE(SUM(AllocatedMarks), 0)
        FROM RubricCriteria WHERE QuestionId = NEW.QuestionId
    ) > (SELECT MaxMarks FROM Questions WHERE QuestionId = NEW.QuestionId);
END;

CREATE TRIGGER TRG_RubricCriteria_CheckQuestionMarks_UPDATE
AFTER UPDATE OF AllocatedMarks, QuestionId ON RubricCriteria
BEGIN
    SELECT RAISE(ABORT, 'Rubric marks exceed the question maximum marks.')
    WHERE (
        SELECT COALESCE(SUM(AllocatedMarks), 0)
        FROM RubricCriteria WHERE QuestionId = NEW.QuestionId
    ) > (SELECT MaxMarks FROM Questions WHERE QuestionId = NEW.QuestionId);
END;

CREATE TRIGGER TRG_Questions_CheckRubricOnMaxMarks_UPDATE
AFTER UPDATE OF MaxMarks ON Questions
BEGIN
    SELECT RAISE(ABORT, 'Question maximum marks cannot be lower than its rubric total.')
    WHERE (
        SELECT COALESCE(SUM(AllocatedMarks), 0)
        FROM RubricCriteria WHERE QuestionId = NEW.QuestionId
    ) > NEW.MaxMarks;
END;

CREATE TRIGGER TRG_QuestionAnswers_CheckQuestionExam_INSERT
BEFORE INSERT ON QuestionAnswers
BEGIN
    SELECT RAISE(ABORT, 'The question must belong to the exam of the answer sheet.')
    WHERE NOT EXISTS (
        SELECT 1
        FROM AnswerSheets S
        JOIN ExamStudents ES ON ES.ExamStudentId = S.ExamStudentId
        JOIN Questions Q ON Q.ExamId = ES.ExamId
        WHERE S.AnswerSheetId = NEW.AnswerSheetId
          AND Q.QuestionId = NEW.QuestionId
    );
END;

CREATE TRIGGER TRG_QuestionAnswers_CheckQuestionExam_UPDATE
BEFORE UPDATE OF AnswerSheetId, QuestionId ON QuestionAnswers
BEGIN
    SELECT RAISE(ABORT, 'The question must belong to the exam of the answer sheet.')
    WHERE NOT EXISTS (
        SELECT 1
        FROM AnswerSheets S
        JOIN ExamStudents ES ON ES.ExamStudentId = S.ExamStudentId
        JOIN Questions Q ON Q.ExamId = ES.ExamId
        WHERE S.AnswerSheetId = NEW.AnswerSheetId
          AND Q.QuestionId = NEW.QuestionId
    );
END;

CREATE TRIGGER TRG_QuestionAnswers_CheckChoice_INSERT
BEFORE INSERT ON QuestionAnswers
WHEN NEW.SelectedChoiceId IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Selected choice must belong to the answer question.')
    WHERE NOT EXISTS (
        SELECT 1 FROM QuestionChoices C
        WHERE C.ChoiceId = NEW.SelectedChoiceId AND C.QuestionId = NEW.QuestionId
    );
END;

CREATE TRIGGER TRG_QuestionAnswers_CheckChoice_UPDATE
BEFORE UPDATE OF SelectedChoiceId, QuestionId ON QuestionAnswers
WHEN NEW.SelectedChoiceId IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Selected choice must belong to the answer question.')
    WHERE NOT EXISTS (
        SELECT 1 FROM QuestionChoices C
        WHERE C.ChoiceId = NEW.SelectedChoiceId AND C.QuestionId = NEW.QuestionId
    );
END;

CREATE TRIGGER TRG_QuestionAnswerPages_CheckSameSheet_INSERT
BEFORE INSERT ON QuestionAnswerPages
BEGIN
    SELECT RAISE(ABORT, 'Answer page must belong to the same answer sheet as the answer.')
    WHERE NOT EXISTS (
        SELECT 1
        FROM QuestionAnswers QA
        JOIN AnswerPages AP ON AP.AnswerSheetId = QA.AnswerSheetId
        WHERE QA.AnswerId = NEW.AnswerId AND AP.PageId = NEW.PageId
    );
END;

CREATE TRIGGER TRG_QuestionAnswerPages_CheckSameSheet_UPDATE
BEFORE UPDATE OF AnswerId, PageId ON QuestionAnswerPages
BEGIN
    SELECT RAISE(ABORT, 'Answer page must belong to the same answer sheet as the answer.')
    WHERE NOT EXISTS (
        SELECT 1
        FROM QuestionAnswers QA
        JOIN AnswerPages AP ON AP.AnswerSheetId = QA.AnswerSheetId
        WHERE QA.AnswerId = NEW.AnswerId AND AP.PageId = NEW.PageId
    );
END;

CREATE TRIGGER TRG_AIProcessingRuns_CheckTargets_INSERT
BEFORE INSERT ON AIProcessingRuns
BEGIN
    SELECT RAISE(ABORT, 'Processing page must belong to the specified answer sheet.')
    WHERE NEW.PageId IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM AnswerPages P
        WHERE P.PageId = NEW.PageId AND P.AnswerSheetId = NEW.AnswerSheetId
    );
    SELECT RAISE(ABORT, 'Processing answer must belong to the specified answer sheet.')
    WHERE NEW.AnswerId IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM QuestionAnswers A
        WHERE A.AnswerId = NEW.AnswerId AND A.AnswerSheetId = NEW.AnswerSheetId
    );
END;

CREATE TRIGGER TRG_AIProcessingRuns_CheckTargets_UPDATE
BEFORE UPDATE OF AnswerSheetId, PageId, AnswerId ON AIProcessingRuns
BEGIN
    SELECT RAISE(ABORT, 'Processing page must belong to the specified answer sheet.')
    WHERE NEW.PageId IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM AnswerPages P
        WHERE P.PageId = NEW.PageId AND P.AnswerSheetId = NEW.AnswerSheetId
    );
    SELECT RAISE(ABORT, 'Processing answer must belong to the specified answer sheet.')
    WHERE NEW.AnswerId IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM QuestionAnswers A
        WHERE A.AnswerId = NEW.AnswerId AND A.AnswerSheetId = NEW.AnswerSheetId
    );
END;

CREATE TRIGGER TRG_QuestionAnswers_ValidateReviewer_INSERT
BEFORE INSERT ON QuestionAnswers
WHEN NEW.AdjustedScore IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Only an active Teacher may submit an adjusted score.')
    WHERE NOT EXISTS (
        SELECT 1 FROM Users U
        WHERE U.UserId = NEW.ReviewedByUserId
          AND U.RoleName = 'Teacher' AND U.IsActive = 1
    );
END;

CREATE TRIGGER TRG_QuestionAnswers_ValidateReviewer_UPDATE
BEFORE UPDATE OF AdjustedScore, ReviewedByUserId ON QuestionAnswers
WHEN NEW.AdjustedScore IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Only an active Teacher may submit an adjusted score.')
    WHERE NOT EXISTS (
        SELECT 1 FROM Users U
        WHERE U.UserId = NEW.ReviewedByUserId
          AND U.RoleName = 'Teacher' AND U.IsActive = 1
    );
END;

CREATE TRIGGER TRG_QuestionAnswers_ValidateApprover_INSERT
BEFORE INSERT ON QuestionAnswers
WHEN NEW.IsApproved = 1
BEGIN
    SELECT RAISE(ABORT, 'Only an active Admin may approve a final score.')
    WHERE NOT EXISTS (
        SELECT 1 FROM Users U
        WHERE U.UserId = NEW.ApprovedByUserId
          AND U.RoleName = 'Admin' AND U.IsActive = 1
    );
END;

CREATE TRIGGER TRG_QuestionAnswers_ValidateApprover_UPDATE
BEFORE UPDATE OF IsApproved, ApprovedScore, ApprovedByUserId, ApprovedAt ON QuestionAnswers
WHEN NEW.IsApproved = 1
BEGIN
    SELECT RAISE(ABORT, 'Only an active Admin may approve a final score.')
    WHERE NOT EXISTS (
        SELECT 1 FROM Users U
        WHERE U.UserId = NEW.ApprovedByUserId
          AND U.RoleName = 'Admin' AND U.IsActive = 1
    );
END;

CREATE TRIGGER TRG_Questions_PreventIncompatibleQuestionType_UPDATE
BEFORE UPDATE OF QuestionType ON Questions
BEGIN
    SELECT RAISE(ABORT, 'Cannot change question type while incompatible choices exist.')
    WHERE NEW.QuestionType NOT IN ('MULTIPLE_CHOICE', 'TRUE_FALSE')
      AND EXISTS (SELECT 1 FROM QuestionChoices C WHERE C.QuestionId = OLD.QuestionId);
    SELECT RAISE(ABORT, 'Cannot change question type while accepted answers exist for an incompatible type.')
    WHERE NEW.QuestionType NOT IN ('FILL_BLANK', 'SHORT_ANSWER')
      AND EXISTS (SELECT 1 FROM AcceptedAnswers A WHERE A.QuestionId = OLD.QuestionId);
END;

CREATE TRIGGER TRG_RubricCriteria_PreventInvalidExistingEvaluations_UPDATE
BEFORE UPDATE OF QuestionId, AllocatedMarks ON RubricCriteria
BEGIN
    SELECT RAISE(ABORT, 'Cannot change criterion allocation below an existing awarded mark.')
    WHERE EXISTS (
        SELECT 1 FROM AnswerCriterionEvaluations E
        WHERE E.CriterionId = OLD.CriterionId
          AND E.AwardedMarks > NEW.AllocatedMarks
    );
    SELECT RAISE(ABORT, 'Cannot move a criterion after it has been evaluated.')
    WHERE NEW.QuestionId <> OLD.QuestionId
      AND EXISTS (SELECT 1 FROM AnswerCriterionEvaluations E WHERE E.CriterionId = OLD.CriterionId);
END;

CREATE TRIGGER TRG_QuestionChoices_CheckType_INSERT
BEFORE INSERT ON QuestionChoices
BEGIN
    SELECT RAISE(ABORT, 'Choices are allowed only for MULTIPLE_CHOICE or TRUE_FALSE questions.')
    WHERE NOT EXISTS (
        SELECT 1 FROM Questions Q
        WHERE Q.QuestionId = NEW.QuestionId
          AND Q.QuestionType IN ('MULTIPLE_CHOICE', 'TRUE_FALSE')
    );
END;

CREATE TRIGGER TRG_QuestionChoices_CheckType_UPDATE
BEFORE UPDATE OF QuestionId ON QuestionChoices
BEGIN
    SELECT RAISE(ABORT, 'Choices are allowed only for MULTIPLE_CHOICE or TRUE_FALSE questions.')
    WHERE NOT EXISTS (
        SELECT 1 FROM Questions Q
        WHERE Q.QuestionId = NEW.QuestionId
          AND Q.QuestionType IN ('MULTIPLE_CHOICE', 'TRUE_FALSE')
    );
END;

CREATE TRIGGER TRG_AcceptedAnswers_CheckType_INSERT
BEFORE INSERT ON AcceptedAnswers
BEGIN
    SELECT RAISE(ABORT, 'Accepted answer variants are allowed only for FILL_BLANK or SHORT_ANSWER questions.')
    WHERE NOT EXISTS (
        SELECT 1 FROM Questions Q
        WHERE Q.QuestionId = NEW.QuestionId
          AND Q.QuestionType IN ('FILL_BLANK', 'SHORT_ANSWER')
    );
END;

CREATE TRIGGER TRG_AcceptedAnswers_CheckType_UPDATE
BEFORE UPDATE OF QuestionId ON AcceptedAnswers
BEGIN
    SELECT RAISE(ABORT, 'Accepted answer variants are allowed only for FILL_BLANK or SHORT_ANSWER questions.')
    WHERE NOT EXISTS (
        SELECT 1 FROM Questions Q
        WHERE Q.QuestionId = NEW.QuestionId
          AND Q.QuestionType IN ('FILL_BLANK', 'SHORT_ANSWER')
    );
END;

CREATE TRIGGER TRG_QuestionAnswers_CheckScoreBounds_INSERT
AFTER INSERT ON QuestionAnswers
BEGIN
    SELECT RAISE(ABORT, 'Answer score exceeds the question maximum marks.')
    WHERE EXISTS (
        SELECT 1 FROM Questions Q
        WHERE Q.QuestionId = NEW.QuestionId
          AND (
              (NEW.SuggestedScore IS NOT NULL AND NEW.SuggestedScore > Q.MaxMarks)
              OR (NEW.AdjustedScore IS NOT NULL AND NEW.AdjustedScore > Q.MaxMarks)
              OR (NEW.ApprovedScore IS NOT NULL AND NEW.ApprovedScore > Q.MaxMarks)
          )
    );
END;

CREATE TRIGGER TRG_QuestionAnswers_CheckScoreBounds_UPDATE
AFTER UPDATE OF SuggestedScore, AdjustedScore, ApprovedScore, QuestionId ON QuestionAnswers
BEGIN
    SELECT RAISE(ABORT, 'Answer score exceeds the question maximum marks.')
    WHERE EXISTS (
        SELECT 1 FROM Questions Q
        WHERE Q.QuestionId = NEW.QuestionId
          AND (
              (NEW.SuggestedScore IS NOT NULL AND NEW.SuggestedScore > Q.MaxMarks)
              OR (NEW.AdjustedScore IS NOT NULL AND NEW.AdjustedScore > Q.MaxMarks)
              OR (NEW.ApprovedScore IS NOT NULL AND NEW.ApprovedScore > Q.MaxMarks)
          )
    );
END;

CREATE TRIGGER TRG_AnswerCriterionEvaluations_CheckCriterion_INSERT
BEFORE INSERT ON AnswerCriterionEvaluations
BEGIN
    SELECT RAISE(ABORT, 'Rubric criterion must belong to the question being answered.')
    WHERE NOT EXISTS (
        SELECT 1
        FROM QuestionAnswers A
        JOIN RubricCriteria R ON R.QuestionId = A.QuestionId
        WHERE A.AnswerId = NEW.AnswerId AND R.CriterionId = NEW.CriterionId
    );
    SELECT RAISE(ABORT, 'Awarded marks exceed the allocated criterion marks.')
    WHERE NEW.AwardedMarks > (
        SELECT AllocatedMarks FROM RubricCriteria WHERE CriterionId = NEW.CriterionId
    );
    SELECT RAISE(ABORT, 'Processing run must be a RUBRIC run for the same answer.')
    WHERE NEW.ProcessingRunId IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM AIProcessingRuns R
        WHERE R.ProcessingRunId = NEW.ProcessingRunId
          AND R.AnswerId = NEW.AnswerId AND R.Stage = 'RUBRIC'
    );
END;

CREATE TRIGGER TRG_AnswerCriterionEvaluations_CheckCriterion_UPDATE
BEFORE UPDATE OF AnswerId, CriterionId, AwardedMarks, ProcessingRunId ON AnswerCriterionEvaluations
BEGIN
    SELECT RAISE(ABORT, 'Rubric criterion must belong to the question being answered.')
    WHERE NOT EXISTS (
        SELECT 1
        FROM QuestionAnswers A
        JOIN RubricCriteria R ON R.QuestionId = A.QuestionId
        WHERE A.AnswerId = NEW.AnswerId AND R.CriterionId = NEW.CriterionId
    );
    SELECT RAISE(ABORT, 'Awarded marks exceed the allocated criterion marks.')
    WHERE NEW.AwardedMarks > (
        SELECT AllocatedMarks FROM RubricCriteria WHERE CriterionId = NEW.CriterionId
    );
    SELECT RAISE(ABORT, 'Processing run must be a RUBRIC run for the same answer.')
    WHERE NEW.ProcessingRunId IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM AIProcessingRuns R
        WHERE R.ProcessingRunId = NEW.ProcessingRunId
          AND R.AnswerId = NEW.AnswerId AND R.Stage = 'RUBRIC'
    );
END;

-- Score and rubric bounds must also remain valid if maxima are later reduced.
CREATE TRIGGER TRG_Questions_PreventInvalidScoreReduction
BEFORE UPDATE OF MaxMarks ON Questions
BEGIN
    SELECT RAISE(ABORT, 'New question maximum is below an existing answer score.')
    WHERE EXISTS (
        SELECT 1 FROM QuestionAnswers A
        WHERE A.QuestionId = OLD.QuestionId
          AND (
              (A.SuggestedScore IS NOT NULL AND A.SuggestedScore > NEW.MaxMarks)
              OR (A.AdjustedScore IS NOT NULL AND A.AdjustedScore > NEW.MaxMarks)
              OR (A.ApprovedScore IS NOT NULL AND A.ApprovedScore > NEW.MaxMarks)
          )
    );
END;

-- =========================
-- Indexes
-- =========================
CREATE INDEX IX_Exams_CreatedByUserId ON Exams(CreatedByUserId);
CREATE INDEX IX_ExamStudents_ExamId ON ExamStudents(ExamId);
CREATE INDEX IX_ExamStudents_StudentId ON ExamStudents(StudentId);
CREATE INDEX IX_Questions_ExamId ON Questions(ExamId);
CREATE INDEX IX_QuestionChoices_QuestionId ON QuestionChoices(QuestionId);
CREATE INDEX IX_AcceptedAnswers_QuestionId ON AcceptedAnswers(QuestionId);
CREATE INDEX IX_RubricCriteria_QuestionId ON RubricCriteria(QuestionId);
CREATE INDEX IX_AnswerSheets_ExamStudentId ON AnswerSheets(ExamStudentId);
CREATE INDEX IX_AnswerSheets_ProcessingStatus ON AnswerSheets(ProcessingStatus);
CREATE INDEX IX_AnswerPages_AnswerSheetId ON AnswerPages(AnswerSheetId);
CREATE INDEX IX_QuestionAnswers_AnswerSheetId ON QuestionAnswers(AnswerSheetId);
CREATE INDEX IX_QuestionAnswers_QuestionId ON QuestionAnswers(QuestionId);
CREATE INDEX IX_QuestionAnswers_ReviewedByUserId ON QuestionAnswers(ReviewedByUserId);
CREATE INDEX IX_QuestionAnswers_ApprovedByUserId ON QuestionAnswers(ApprovedByUserId);
CREATE INDEX IX_QuestionAnswerPages_PageId ON QuestionAnswerPages(PageId);
CREATE INDEX IX_AIProcessingRuns_AnswerSheetId ON AIProcessingRuns(AnswerSheetId);
CREATE INDEX IX_AIProcessingRuns_AnswerId ON AIProcessingRuns(AnswerId);
CREATE INDEX IX_AIProcessingRuns_Stage_Status ON AIProcessingRuns(Stage, Status);
CREATE INDEX IX_AnswerCriterionEvaluations_AnswerId ON AnswerCriterionEvaluations(AnswerId);
CREATE INDEX IX_AnswerCriterionEvaluations_CriterionId ON AnswerCriterionEvaluations(CriterionId);
CREATE INDEX IX_AuditLogs_PerformedByUserId ON AuditLogs(PerformedByUserId);
CREATE INDEX IX_AuditLogs_Entity ON AuditLogs(EntityName, EntityId);
CREATE INDEX IX_BackupHistory_PerformedByUserId ON BackupHistory(PerformedByUserId);

INSERT INTO SchemaMigrations (Version, Description)
VALUES (1, 'Unified initial Madar schema: questions, multi-page answers, rubric evaluations, and AI run tracking.');

COMMIT;
