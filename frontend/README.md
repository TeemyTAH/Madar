# Madar Frontend — Phase 7/8 Integration

واجهة عربية RTL مبنية باستخدام React + Vite، وتتصل بخدمات Madar عبر REST API. لا تتصل المتصفحات بملف SQLite مباشرة؛ جميع عمليات القراءة والكتابة تمر عبر الـBackend مع Bearer authentication وصلاحيات الأدوار.

## المتطلبات

- Python 3.11–3.13 مع متطلبات المشروع الموجودة في `../requirements.txt`.
- Node.js 20.19+ أو 22.12+ وnpm.
- تشغيل الواجهة والـAPI على الجهاز نفسه أثناء التطوير المحلي.

## التشغيل المحلي على Windows

### Terminal 1 — Backend + SQLite

من جذر المشروع `Madar_Final_Project`:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

إذا لم تكن البيئة الافتراضية أو الحزم مجهزة بعد:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Terminal 2 — Frontend

من مجلد `frontend`:

```powershell
npm ci
npm run dev
```

افتح:

- واجهة Madar: `http://127.0.0.1:5173`
- توثيق API: `http://127.0.0.1:8000/docs`
- فحص صحة API وقاعدة البيانات: `http://127.0.0.1:8000/health`

Vite يمرر `/api/v1` و`/health` إلى `http://127.0.0.1:8000` افتراضياً. لتغيير عنوان الـBackend أنشئ `frontend/.env` من `.env.example` وعدّل `MADAR_API_ORIGIN`.

## أول تشغيل وتسجيل الدخول

1. شغّل الـBackend أولاً؛ سيهيئ SQLite في `storage/SmartArabicGraderDB.sqlite3` دون استبدال قاعدة بيانات موجودة وصالحة.
2. إذا لم يوجد Admin، اختر «إعداد أول مسؤول» وأنشئ الحساب الأول. كلمة المرور 12 حرفاً على الأقل.
3. إذا كان Admin موجوداً، استخدم «تسجيل الدخول»؛ لا تحاول إعادة Bootstrap.
4. ينتهي رمز الدخول بعد 8 ساعات، ويحفظ في `sessionStorage` حتى إغلاق جلسة المتصفح.

## الوظائف المتصلة بالـAPI

- لوحة المعلومات ومؤشرات قاعدة البيانات.
- إدارة الطلاب والاختبارات والأسئلة.
- تسجيل الطلاب في الاختبارات.
- رفع صفحات الإجابة، مع حد 20 MB للصورة.
- عرض الصور الأصلية والمعالجة من مسارات محمية.
- تحديد مناطق الإجابة بإحداثيات نسبية وربط أكثر من منطقة بالسؤال.
- تشغيل HTR لكل إجابة، ومراجعة النص المستخرج.
- تشغيل التقييم، ومراجعة المعلم، والاعتماد النهائي بواسطة Admin.
- التقارير وكشف الدرجات وتنزيل Excel/CSV.
- إنشاء حسابات Admin وTeacher وReviewer.

## الصلاحيات

- **Admin:** الإدارة الأكاديمية، إدارة المستخدمين، واعتماد الدرجات النهائية.
- **Teacher:** إدارة الاختبارات والأسئلة والطلاب، رفع الإجابات، HTR، ومراجعة الدرجات.
- **Reviewer:** الاطلاع على البيانات والتقارير دون التعديل.

## ملاحظات مهمة

- HTR هو مسودة نصية يجب مراجعتها بصرياً أمام صورة الإجابة.
- تقييم الإجابات المقالية في هذه النسخة يعتمد على Rubric heuristic، وليس نموذجاً دلالياً مدرباً.
- الدرجة النهائية لا تظهر إلا بعد اعتماد جميع أسئلة الطالب.
- أبقِ الخادم مربوطاً بـ`127.0.0.1` في التطوير المحلي. قبل النشر العام يلزم HTTPS وقيود شبكة وRate limiting وسياسة نسخ احتياطي واستعادة.
- في الإنتاج، يفضّل نشر الواجهة والـAPI على نفس النطاق عبر reverse proxy يمرر `/api/v1` و`/health` إلى FastAPI؛ لا تضع مفاتيح أو أسرار الخادم داخل متغيرات `VITE_*`.


## فحص الواجهة قبل التسليم

من جذر المشروع في PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\verify_frontend.ps1
```

ينفذ السكربت `npm ci` ثم ESLint ثم `vite build` باستخدام الإصدارات المثبتة في `package-lock.json`.
