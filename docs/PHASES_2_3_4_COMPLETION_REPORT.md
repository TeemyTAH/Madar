# Madar — تقرير تنفيذ المراحل 2 و3 و4

**الإصدار:** 1.1.0  
**نطاق العمل:** Arabic HTR، تكامل Backend، التصحيح والتقييم  
**قاعدة البيانات:** Schema v1.0 كما هي؛ لم تُنفذ أي Migration ولم تُستبدل قاعدة البيانات الموجودة.

## ملخص التنفيذ

| المرحلة | ما نُفذ | الحالة |
|---|---|---|
| 2 — Arabic HTR | Beam Search، قراءة الصفحات، اكتشاف الأسطر، بدائل القراءة، مؤشرات الثقة، مسارات احتياطية للتقسيم | مكتملة برمجياً؛ اختبار ONNX الفعلي مطلوب على جهاز Windows |
| 3 — Backend Integration | خدمات HTR، تتبع AIProcessingRuns، ربط مناطق الإجابة، حفظ النص المستخرج، سجلات التدقيق، واجهات API | مكتملة واختباراتها ناجحة |
| 4 — Grading & Rubric | تصحيح MCQ/True-False، مطابقة الإجابات المقبولة، اقتراح درجات Rubric على أساس الأدلة اللفظية | الأساس التشغيلي مكتمل؛ النموذج الدلالي الحقيقي غير متوفر ويظل ضمن التوسع |

## المرحلة 2 — محرك التعرف على الكتابة العربية

### الملفات

- `ai_engine/htr/engine.py`
- `ai_engine/htr/reference/page.py`
- `ai_engine/htr/smoke_test.py`
- `ai_engine/htr/models/ar.onnx`
- `ai_engine/htr/models/ar.json`
- `ai_engine/htr/models/ppocr_det_v4.onnx`

### ما تم

1. الإبقاء على نموذج ONNX الحالي وملف إعداداته دون تدريب أو تعديل للأوزان.
2. إضافة CTC Prefix Beam Search بدلاً من الاعتماد على Greedy وحده.
3. إعادة ترتيب النص العربي باستخدام دوال RTL المرجعية الموجودة في المشروع.
4. إضافة اكتشاف الصفحة والأسطر عبر PP-OCRv4 DBNet.
5. إضافة مسارين احتياطيين عند عدم اكتشاف الأسطر: Blobs ثم Projection.
6. إرجاع إحداثيات الأسطر، النص، البدائل، زمن المعالجة، وزمن الاستدلال.
7. تصنيف القراءة منخفضة الثقة على أنها تحتاج مراجعة.
8. تصحيح المسار الافتراضي لملف كاشف النصوص؛ كان يبحث في `ai_engine/models` بينما الملف موجود في `ai_engine/htr/models`.
9. جعل استيراد ONNX Runtime كسولاً حتى يمكن تشغيل اختبارات الخدمات وقاعدة البيانات دون تحميل Runtime عند استيراد التطبيق.

### حدود الدقة

الـ Golden Dataset المرفق يحتوي عينتين مؤكدتين فقط. القياس السابق المسجل:

- CER الإجمالي: **33.33%**.
- WER الإجمالي: **75.00%**.
- في مقارنة Decoder السابقة، تحسن CER للعينة الثانية من 41.67% إلى 33.33% مع Beam Search، بينما بقي WER عند 100%.
- قيم Beam posterior المسجلة للعينة كانت تقريباً 0.13–0.17؛ لذلك يستخدم المحرك حد مراجعة افتراضياً 0.60.

هذه البيانات لا تكفي لإثبات دقة إنتاجية. قيمة Beam posterior ليست احتمال دقة معايراً. لا يجوز اعتماد النص المستخرج دون مراجعته مقابل صورة الطالب.

### اختبار ONNX الفعلي

أُجريت اختبارات وحدات باستخدام Session وهمي للتحقق من preprocessing وCTC وRTL وتدفق الصفحات. لم يكن ONNX Runtime مثبتاً في بيئة التنفيذ الحالية، وتعذر تنزيله بسبب عدم توفر الشبكة؛ لذلك لم يُشغّل اختبار النموذج والكاشف الحقيقيين هنا بعد تعديل المحرك.

على جهاز Windows الذي يحتوي `onnxruntime==1.32.0` نفّذ:

```powershell
python -m ai_engine.htr.smoke_test
```

يمكن تمرير صورة أخرى:

```powershell
python -m ai_engine.htr.smoke_test .\path\to\answer_page.png
```

هذا اختبار تشغيل فعلي للنموذج والكاشف، وليس اختبار دقة إحصائياً.

## المرحلة 3 — تكامل HTR مع Backend

### الملفات

- `backend/app/services/processing_runs.py`
- `backend/app/services/htr_service.py`
- `backend/app/api/endpoints/ai.py`
- `backend/app/api/endpoints/answers.py`
- `backend/app/main.py`
- `backend/app/schemas/answers.py`
- `ai_engine/image_processing/processor.py`

### واجهات API

| Method | Endpoint | الوظيفة |
|---|---|---|
| POST | `/api/v1/ai/pages/{page_id}/recognize` | قراءة الصفحة وتخزين نتيجة تشغيل HTR |
| POST | `/api/v1/answers/{answer_id}/regions` | ربط إجابة بصفحة كاملة أو منطقة محددة |
| GET | `/api/v1/answers/{answer_id}/regions` | عرض مناطق الإجابة المرتبطة |
| POST | `/api/v1/ai/answers/{answer_id}/recognize` | قراءة المناطق المرتبطة بإجابة محددة وحفظ النص |

### منطق الربط

- إحداثيات المناطق نسبية من 0 إلى 1.
- ترك الإحداثيات الأربعة فارغة يعني ربط الصفحة كاملة.
- يجب أن تنتمي الصفحة والإجابة إلى ورقة الإجابة نفسها.
- يمكن للإجابة الواحدة أن تمتد عبر صفحات ومناطق متعددة.
- لا يبدأ OCR على مستوى الإجابة قبل إنشاء `QuestionAnswerPages` mappings.
- يحفظ النص في `QuestionAnswers.ExtractedText`، وتحفظ ثقة OCR في `OcrConfidence`، وتُحدّث `NeedsOcrReview` و`IsEmptyAnswer`.
- لا يستبدل OCR النص الذي أدخله المعلم في `EditedText`.

### سجل التشغيل

يستخدم `ProcessingRunTracker` دورة الحياة:

`PENDING → RUNNING → SUCCEEDED / FAILED / REQUIRES_REVIEW`

ويحفظ المرحلة، الصفحة، الإجابة، إصدار النموذج، المدخلات، المخرجات، الخطأ، وقت البدء والانتهاء، والمدة في `AIProcessingRuns`.

أضيف سجل تدقيق لاستخراج النص دون نسخ نص الطالب كاملاً إلى سجل التدقيق.

### إصلاح سلامة الملفات

أصبحت `ImageProcessor` تنفذ التحويلات أولاً في الذاكرة، ثم تحفظ الصورة المعالجة والأصلية في نهاية العملية. وإذا فشل أحد الحفظين، تحذف المخرجات الجزئية حتى لا تبقى ملفات يتيمة.

## المرحلة 4 — التصحيح والتقييم

### الملفات

- `backend/app/services/grading_service.py`
- `backend/app/services/rubric_evaluator.py`
- `backend/app/api/endpoints/grading.py`

### واجهة API

`POST /api/v1/grading/answers/{answer_id}/evaluate`

### الأنواع المدعومة

1. **MULTIPLE_CHOICE:** يشترط وجود خيارين على الأقل وخيار صحيح واحد فقط.
2. **TRUE_FALSE:** يشترط خيارين وخيار صحيح واحد فقط.
3. **FILL_BLANK:** مطابقة الإجابة مع `AcceptedAnswers` مع احترام خيارات تطبيع العربية وحساسية حالة الأحرف.
4. **SHORT_ANSWER:** مطابقة الإجابات المقبولة إن وجدت؛ وإلا ينتقل إلى Rubric.
5. **ESSAY / ASSIGNMENT:** تقييم أولي على مستوى معايير Rubric.

### Rubric baseline

- يجب أن يساوي مجموع درجات المعايير الدرجة القصوى للسؤال.
- يجب أن يحتوي كل معيار وصفاً قابلاً لاستخراج مفردات الدليل منه.
- يحسب المقيم اللفظي تغطية مفردات الوصف في الإجابة، ويقترح درجة موزونة حسب الدرجة المخصصة للمعيار.
- تُحفظ التفاصيل في `AnswerCriterionEvaluations`، مع الاحتفاظ بالسجل السابق وجعل تقييم واحد فقط حالياً لكل معيار.
- التقييم اللفظي لا يفهم المرادفات أو إعادة الصياغة أو التكافؤ الدلالي؛ لذلك يظل دائماً `REQUIRES_REVIEW` ولا يكتب درجة ثقة زائفة.

### ما لم يُدّعَ تنفيذه

لا يوجد في الحزمة نموذج Semantic AI أو Language Model مدرّب/مهيأ لتقييم الإجابات المقالية. لذلك:

- لا يُدّعى أن Rubric baseline يفهم المعنى.
- لا تُعتمد درجات المقالات آلياً.
- لا تُكتب `AdjustedScore` أو `ApprovedScore` أو `IsApproved` بواسطة خدمة الذكاء الاصطناعي.
- يظل الاعتماد النهائي ضمن مسار المعلم/المدير الموجود في قاعدة البيانات.

إضافة نموذج دلالي حقيقي، وضبطه على بيانات إجابات يمنية/عربية، ومعايرة الدرجات والثقة، تظل ضمن مرحلة التوسع والتدريب.

## الاختبارات

تم تشغيل الاختبارات من جذر المشروع:

```powershell
python -m pytest -q
python backend/tests/test_schema_integrity.py
python -m unittest backend.tests.test_database_manager -v
```

النتائج في بيئة التنفيذ:

- Pytest: **49 passed**.
- Schema integrity: **14/14 passed**.
- Database manager: **6/6 passed**.
- Compile check: `python -m compileall -q ai_engine backend` ناجح.

تغطي الاختبارات preprocessing، CTC، RTL، استدعاء page pipeline مع detector وهمي، سلامة مسار النموذج، تتبع دورة حياة المعالجة، تعدد صفحات الإجابة، حماية المسارات، تصحيح MCQ وFill Blank، Rubric review، منع إعادة تقييم الإجابة المعتمدة، وتكامل API مع قاعدة اختبار مؤقتة.

## التشغيل

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

ثم افتح:

`http://127.0.0.1:8000/docs`

## ملاحظات الأمان والنشر

- لم تُنفذ طبقة Authentication/Authorization في هذه المراحل.
- يجب إبقاء الخادم على `127.0.0.1` وعدم تعريضه للشبكة العامة قبل إضافة تسجيل الدخول والصلاحيات وحماية الطلبات.
- لم يتم تعديل قاعدة البيانات الموجودة أو استبدالها.
- لم يتم تدريب النموذج أو تعديل أوزانه.
