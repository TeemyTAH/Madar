import { formatDate, formatNumber } from '../lib/format'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, downloadFile } from '../lib/api'
import { Alert, Button, Card, Empty, Field, Loading, Modal, Status } from '../components/common'
import SheetReview from './SheetReview'

const typeLabels = {
  MULTIPLE_CHOICE: 'اختيار من متعدد',
  TRUE_FALSE: 'صح أو خطأ',
  FILL_BLANK: 'أكمل الفراغ',
  SHORT_ANSWER: 'إجابة قصيرة',
  ESSAY: 'مقالي',
  ASSIGNMENT: 'واجب',
}

const initialQuestion = {
  question_number: 1,
  question_type: 'MULTIPLE_CHOICE',
  question_text: '',
  model_answer: '',
  max_marks: '1',
}

function QuestionsTab({ examId, user, notify }) {
  const [questions, setQuestions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState(initialQuestion)
  const [options, setOptions] = useState([
    { choice_label: 'A', choice_text: '', is_correct: true },
    { choice_label: 'B', choice_text: '', is_correct: false },
    { choice_label: 'C', choice_text: '', is_correct: false },
    { choice_label: 'D', choice_text: '', is_correct: false },
  ])
  const [accepted, setAccepted] = useState('')
  const [criteria, setCriteria] = useState([{ criterion_title: '', criterion_description: '', allocated_marks: '' }])

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setQuestions(await api(`/academic/exams/${examId}/questions`)) }
    catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }, [examId])
  useEffect(() => { load() }, [load])

  const openForm = () => {
    setForm({ ...initialQuestion, question_number: questions.length + 1 })
    setAccepted('')
    setOptions([
      { choice_label: 'A', choice_text: '', is_correct: true },
      { choice_label: 'B', choice_text: '', is_correct: false },
      { choice_label: 'C', choice_text: '', is_correct: false },
      { choice_label: 'D', choice_text: '', is_correct: false },
    ])
    setCriteria([{ criterion_title: '', criterion_description: '', allocated_marks: '' }])
    setError(''); setOpen(true)
  }

  const create = async (event) => {
    event.preventDefault(); setSaving(true); setError('')
    try {
      const type = form.question_type
      const payload = {
        question_number: Number(form.question_number),
        question_type: type,
        question_text: form.question_text.trim(),
        model_answer: form.model_answer.trim() || null,
        max_marks: Number(form.max_marks),
        choices: [],
        accepted_answers: [],
        rubric_criteria: [],
      }
      if (['MULTIPLE_CHOICE', 'TRUE_FALSE'].includes(type)) {
        payload.choices = options
          .filter((item) => item.choice_text.trim())
          .map((item, index) => ({ ...item, choice_label: item.choice_label || String.fromCharCode(65 + index), sort_order: index + 1 }))
        if (payload.choices.length < 2) throw new Error('أدخل خيارين على الأقل.')
        if (payload.choices.filter((item) => item.is_correct).length !== 1) throw new Error('حدد إجابة صحيحة واحدة فقط.')
        if (type === 'TRUE_FALSE' && payload.choices.length !== 2) throw new Error('سؤال صح أو خطأ يحتاج خيارين فقط.')
      }
      if (['FILL_BLANK', 'SHORT_ANSWER'].includes(type)) {
        payload.accepted_answers = accepted.split('\n').map((item) => item.trim()).filter(Boolean)
          .map((answer_text, index) => ({ answer_text, case_sensitive: false, normalize_arabic: true, sort_order: index + 1 }))
        if (!payload.accepted_answers.length) throw new Error('أدخل إجابة مقبولة واحدة على الأقل، كل إجابة في سطر.')
        if (type === 'SHORT_ANSWER' && !payload.model_answer) throw new Error('الإجابة النموذجية مطلوبة للسؤال القصير.')
      }
      if (['ESSAY', 'ASSIGNMENT'].includes(type)) {
        payload.rubric_criteria = criteria
          .filter((item) => item.criterion_title.trim() && item.criterion_description.trim() && item.allocated_marks !== '')
          .map((item, index) => ({
            criterion_title: item.criterion_title.trim(),
            criterion_description: item.criterion_description.trim(),
            allocated_marks: Number(item.allocated_marks),
            sort_order: index + 1,
          }))
        if (!payload.rubric_criteria.length) throw new Error('أضف معيار Rubric واحداً على الأقل.')
        const sum = payload.rubric_criteria.reduce((total, item) => total + item.allocated_marks, 0)
        if (Math.abs(sum - payload.max_marks) > 0.0001) throw new Error(`مجموع درجات المعايير (${sum}) يجب أن يساوي الدرجة القصوى (${payload.max_marks}).`)
        if (type === 'ESSAY' && !payload.model_answer) throw new Error('الإجابة النموذجية مطلوبة للسؤال المقالي.')
      }
      await api(`/academic/exams/${examId}/questions`, { method: 'POST', body: payload })
      setOpen(false); notify('تمت إضافة السؤال وتحديث سجلات الإجابات المرتبطة.', 'success'); await load()
    } catch (err) { setError(err.message) }
    finally { setSaving(false) }
  }

  const updateOption = (index, patch) => setOptions((current) => current.map((item, i) => i === index ? { ...item, ...patch } : item))
  const type = form.question_type
  const objective = ['MULTIPLE_CHOICE', 'TRUE_FALSE'].includes(type)

  return (
    <div className="page-stack compact-stack">
      <div className="section-heading"><div><h2>أسئلة الاختبار</h2><p>عرّف الأسئلة ومفتاح الإجابة ومعايير التصحيح.</p></div>
        {user.role_name !== 'Reviewer' && <Button onClick={openForm}>＋ إضافة سؤال</Button>}
      </div>
      {error && <Alert tone="danger" onClose={() => setError('')}>{error}</Alert>}
      {loading ? <Loading /> : questions.length ? (
        <div className="question-list">
          {questions.map((question) => (
            <div className="question-row" key={question.QuestionId}>
              <div className="question-number">{question.QuestionNumber}</div>
              <div className="question-main"><strong>{question.QuestionText}</strong><div className="question-meta"><span>{typeLabels[question.QuestionType] || question.QuestionType}</span><span>{formatNumber(question.MaxMarks)} درجة</span>
                {question.choices?.length > 0 && <span>{question.choices.length} خيارات</span>}
                {question.accepted_answers?.length > 0 && <span>{question.accepted_answers.length} إجابات مقبولة</span>}
                {question.rubric_criteria?.length > 0 && <span>{question.rubric_criteria.length} معايير</span>}
              </div></div>
              <span className="id-chip">#{question.QuestionId}</span>
            </div>
          ))}
        </div>
      ) : <Empty title="لم تتم إضافة أسئلة" detail="أضف أسئلة الاختبار أولاً حتى تستطيع إنشاء أوراق الإجابة وتصحيحها." />}

      {open && (
        <Modal title="إضافة سؤال للاختبار" subtitle="تحقق من نوع السؤال ومتطلبات إعداده قبل الحفظ." onClose={() => setOpen(false)} wide>
          <form className="form-stack" onSubmit={create}>
            {error && <Alert tone="danger">{error}</Alert>}
            <div className="form-row form-row-three">
              <Field label="رقم السؤال"><input type="number" min="1" required value={form.question_number} onChange={(e) => setForm({ ...form, question_number: e.target.value })} /></Field>
              <Field label="نوع السؤال"><select value={type} onChange={(e) => setForm({ ...form, question_type: e.target.value })}>
                {Object.entries(typeLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select></Field>
              <Field label="الدرجة القصوى"><input type="number" min="0.01" step="0.25" required value={form.max_marks} onChange={(e) => setForm({ ...form, max_marks: e.target.value })} /></Field>
            </div>
            <Field label="نص السؤال"><textarea rows="3" required value={form.question_text} onChange={(e) => setForm({ ...form, question_text: e.target.value })} placeholder="اكتب نص السؤال..." /></Field>
            {['SHORT_ANSWER', 'ESSAY'].includes(type) && <Field label="الإجابة النموذجية"><textarea rows="3" value={form.model_answer} onChange={(e) => setForm({ ...form, model_answer: e.target.value })} placeholder="الإجابة النموذجية..." /></Field>}
            {objective && (
              <div className="builder-panel">
                <div className="builder-title"><strong>خيارات الإجابة</strong><small>اختر إجابة صحيحة واحدة فقط.</small></div>
                {options.slice(0, type === 'TRUE_FALSE' ? 2 : 4).map((option, index) => (
                  <div className="option-builder" key={index}>
                    <span className="option-letter">{option.choice_label}</span>
                    <input aria-label={`الخيار ${option.choice_label}`} value={option.choice_text} onChange={(e) => updateOption(index, { choice_text: e.target.value })} placeholder={`نص الخيار ${option.choice_label}`} required />
                    <label className="correct-choice"><input type="radio" name="correct-choice" checked={option.is_correct} onChange={() => setOptions((current) => current.map((item, i) => ({ ...item, is_correct: i === index })))} /> صحيح</label>
                  </div>
                ))}
                {type === 'TRUE_FALSE' && <small className="field-hint">استخدم الخيارين لتمثيل صحيح وخطأ.</small>}
              </div>
            )}
            {['FILL_BLANK', 'SHORT_ANSWER'].includes(type) && <Field label="الإجابات المقبولة" hint="اكتب كل صيغة مقبولة في سطر مستقل.">
              <textarea rows="4" value={accepted} onChange={(e) => setAccepted(e.target.value)} placeholder={'مثال:\nالإجابة الأولى\nصيغة بديلة'} />
            </Field>}
            {['ESSAY', 'ASSIGNMENT'].includes(type) && (
              <div className="builder-panel">
                <div className="builder-title"><strong>معايير التصحيح (Rubric)</strong><small>يجب أن يساوي مجموع الدرجات الدرجة القصوى للسؤال.</small></div>
                {criteria.map((item, index) => (
                  <div className="criterion-builder" key={index}>
                    <div className="criterion-top"><strong>المعيار {index + 1}</strong>{criteria.length > 1 && <Button size="sm" variant="danger-ghost" type="button" onClick={() => setCriteria((current) => current.filter((_, i) => i !== index))}>حذف</Button>}</div>
                    <div className="form-row"><Field label="عنوان المعيار"><input value={item.criterion_title} onChange={(e) => setCriteria((current) => current.map((x, i) => i === index ? { ...x, criterion_title: e.target.value } : x))} required /></Field>
                      <Field label="الدرجة"><input type="number" min="0" step="0.25" value={item.allocated_marks} onChange={(e) => setCriteria((current) => current.map((x, i) => i === index ? { ...x, allocated_marks: e.target.value } : x))} required /></Field></div>
                    <Field label="وصف المعيار"><textarea rows="2" value={item.criterion_description} onChange={(e) => setCriteria((current) => current.map((x, i) => i === index ? { ...x, criterion_description: e.target.value } : x))} required /></Field>
                  </div>
                ))}
                <Button type="button" variant="secondary" size="sm" onClick={() => setCriteria((current) => [...current, { criterion_title: '', criterion_description: '', allocated_marks: '' }])}>＋ إضافة معيار</Button>
              </div>
            )}
            <div className="workflow-note"><span>ⓘ</span><p>التقييم المقالي الحالي قائم على Rubric heuristic ويظل اقتراحاً يتطلب مراجعة بشرية؛ لا يوجد نموذج دلالي مدرّب في هذه النسخة.</p></div>
            <div className="form-actions"><Button type="button" variant="secondary" onClick={() => setOpen(false)}>إلغاء</Button><Button type="submit" disabled={saving}>{saving ? 'جارٍ الحفظ...' : 'حفظ السؤال'}</Button></div>
          </form>
        </Modal>
      )}
    </div>
  )
}

function EnrollmentTab({ examId, user, notify }) {
  const [students, setStudents] = useState([])
  const [enrollments, setEnrollments] = useState([])
  const [selected, setSelected] = useState([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [studentData, enrollmentData] = await Promise.all([
        api('/academic/students?limit=200'),
        api(`/academic/exams/${examId}/enrollments`),
      ])
      setStudents(studentData.items || [])
      setEnrollments(enrollmentData || [])
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }, [examId])
  useEffect(() => { load() }, [load])

  const enrolledIds = useMemo(() => new Set(enrollments.map((item) => Number(item.StudentId))), [enrollments])
  const visibleStudents = students.filter((item) => !enrolledIds.has(Number(item.StudentId)) &&
    `${item.FullName} ${item.AcademicId}`.toLowerCase().includes(search.toLowerCase()))

  const submit = async () => {
    if (!selected.length) return
    setBusy(true); setError('')
    try {
      const result = await api(`/academic/exams/${examId}/enrollments`, { method: 'POST', body: { student_ids: selected } })
      notify(`تم تسجيل ${result.added_count} طالب في الاختبار.`, 'success')
      setSelected([]); await load()
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  const remove = async (student) => {
    if (!window.confirm(`إزالة ${student.FullName} من هذا الاختبار؟`)) return
    try {
      await api(`/academic/exams/${examId}/enrollments/${student.StudentId}`, { method: 'DELETE' })
      notify('تمت إزالة التسجيل.', 'success'); await load()
    } catch (err) { setError(err.message) }
  }

  if (loading) return <Loading />
  return (
    <div className="page-stack compact-stack">
      {error && <Alert tone="danger" onClose={() => setError('')}>{error}</Alert>}
      <div className="enrollment-columns">
        {user.role_name !== 'Reviewer' && <Card title="تسجيل طلاب جدد" subtitle="اختر الطلاب لإضافتهم إلى هذا الاختبار.">
          <div className="search-field search-field-full"><span>⌕</span><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="ابحث عن طالب..." /></div>
          <div className="select-list">
            {visibleStudents.length ? visibleStudents.map((student) => (
              <label className="select-list-item" key={student.StudentId}>
                <input type="checkbox" checked={selected.includes(student.StudentId)} onChange={(e) => setSelected((current) => e.target.checked ? [...current, student.StudentId] : current.filter((id) => id !== student.StudentId))} />
                <span><strong>{student.FullName}</strong><small>{student.AcademicId}</small></span>
              </label>
            )) : <Empty title="لا يوجد طلاب متاحون" detail="أضف الطلاب من قسم الطلاب أولاً." />}
          </div>
          <div className="form-actions"><span className="toolbar-count">{selected.length} محدد</span><Button onClick={submit} disabled={busy || !selected.length}>{busy ? 'جارٍ التسجيل...' : 'تسجيل المحددين'}</Button></div>
        </Card>}
        <Card title={`الطلاب المسجلون (${enrollments.length})`} subtitle="يمكن إزالة التسجيل قبل إنشاء ورقة إجابة.">
          {enrollments.length ? <div className="enrolled-list">{enrollments.map((item) => (
            <div className="enrolled-item" key={item.ExamStudentId}>
              <span className="avatar-small">{item.FullName?.trim()?.charAt(0) || 'ط'}</span>
              <span className="enrolled-name"><strong>{item.FullName}</strong><small>{item.AcademicId} · تسجيل #{item.ExamStudentId}</small></span>
              {user.role_name !== 'Reviewer' && <Button size="sm" variant="danger-ghost" onClick={() => remove(item)}>إزالة</Button>}
            </div>
          ))}</div> : <Empty title="لا يوجد طلاب مسجلون" />}
        </Card>
      </div>
    </div>
  )
}

function SheetsTab({ examId, user, notify, onOpenSheet }) {
  const [sheets, setSheets] = useState([])
  const [enrollments, setEnrollments] = useState([])
  const [selectedEnrollment, setSelectedEnrollment] = useState('')
  const [pageNumber, setPageNumber] = useState('1')
  const [file, setFile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [sheetData, enrollmentData] = await Promise.all([
        api(`/academic/exams/${examId}/answer-sheets`),
        api(`/academic/exams/${examId}/enrollments`),
      ])
      setSheets(sheetData || []); setEnrollments(enrollmentData || [])
      setSelectedEnrollment((current) => current || (enrollmentData?.length ? String(enrollmentData[0].ExamStudentId) : ''))
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }, [examId])
  useEffect(() => { load() }, [load])

  const upload = async (event) => {
    event.preventDefault()
    if (!file || !selectedEnrollment) return
    setUploading(true); setError('')
    try {
      const form = new FormData()
      form.append('exam_student_id', selectedEnrollment)
      form.append('page_number', pageNumber)
      form.append('file', file)
      const result = await api('/uploads/answer-page', { method: 'POST', body: form })
      notify(`تم رفع الصفحة ${result.page_number} ومعالجتها مبدئياً.`, 'success')
      setFile(null)
      const input = document.getElementById('answer-page-file')
      if (input) input.value = ''
      await load()
    } catch (err) { setError(err.message) }
    finally { setUploading(false) }
  }

  if (loading) return <Loading />
  const sheetByEnrollment = new Map(sheets.map((sheet) => [Number(sheet.ExamStudentId), sheet]))
  const pendingEnrollments = enrollments.filter((item) => !sheetByEnrollment.has(Number(item.ExamStudentId)))

  return (
    <div className="page-stack compact-stack">
      {error && <Alert tone="danger" onClose={() => setError('')}>{error}</Alert>}
      {user.role_name !== 'Reviewer' && (
        <Card title="رفع ورقة إجابة" subtitle="ارفع صورة واضحة لكل صفحة. يقبل النظام الصور المدعومة حتى 20 MB للملف.">
          <form className="upload-form" onSubmit={upload}>
            <Field label="الطالب المسجل">
              <select required value={selectedEnrollment} onChange={(e) => setSelectedEnrollment(e.target.value)}>
                {enrollments.map((item) => <option key={item.ExamStudentId} value={item.ExamStudentId}>{item.FullName} — {item.AcademicId}</option>)}
              </select>
            </Field>
            <Field label="رقم الصفحة"><input type="number" min="1" required value={pageNumber} onChange={(e) => setPageNumber(e.target.value)} /></Field>
            <Field label="صورة الإجابة" hint="PNG أو JPG أو JPEG أو WEBP حسب دعم معالج الصور.">
              <input id="answer-page-file" type="file" accept="image/*" required onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </Field>
            <Button type="submit" disabled={uploading || !file || !selectedEnrollment}>{uploading ? 'جارٍ الرفع والمعالجة...' : 'رفع الصفحة'}</Button>
          </form>
          {!enrollments.length && <Alert tone="warning">سجّل الطلاب في الاختبار قبل رفع أوراق الإجابة.</Alert>}
        </Card>
      )}
      <Card title="أوراق الإجابة" subtitle="اختر ورقة لعرض الصفحات ومراجعة إجاباتها.">
        {sheets.length ? (
          <div className="table-wrap">
            <table><thead><tr><th>الطالب</th><th>الرقم الأكاديمي</th><th>الصفحات</th><th>الإجابات</th><th>الحالة</th><th /></tr></thead>
              <tbody>{sheets.map((sheet) => (
                <tr key={sheet.AnswerSheetId}>
                  <td><strong>{sheet.FullName}</strong><small className="cell-sub">ورقة #{sheet.AnswerSheetId}</small></td>
                  <td>{sheet.AcademicId}</td><td>{formatNumber(sheet.PageCount)}</td><td>{formatNumber(sheet.AnswerCount)}</td><td><Status value={sheet.ProcessingStatus} /></td>
                  <td><Button size="sm" onClick={() => onOpenSheet(sheet.AnswerSheetId)}>مراجعة الورقة ←</Button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <Empty title="لا توجد أوراق إجابة" detail="ارفع أول صفحة إجابة من النموذج أعلاه." />}
      </Card>
      {pendingEnrollments.length > 0 && <div className="muted-note">يوجد {pendingEnrollments.length} طالباً مسجلاً لم تُرفع لهم أوراق إجابة بعد.</div>}
    </div>
  )
}

function ResultsTab({ examId }) {
  const [data, setData] = useState(null)
  const [analytics, setAnalytics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [results, report] = await Promise.all([
        api(`/academic/exams/${examId}/results`),
        api(`/reports/exams/${examId}/analytics`).catch(() => null),
      ])
      setData(results); setAnalytics(report)
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }, [examId])
  useEffect(() => { load() }, [load])

  if (loading) return <Loading />
  return (
    <div className="page-stack compact-stack">
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="stats-grid stats-grid-compact">
        <div className="mini-stat"><span>الطلاب المسجلون</span><strong>{formatNumber(data?.enrolled_count)}</strong></div>
        <div className="mini-stat"><span>الأسئلة</span><strong>{formatNumber(data?.question_count)}</strong></div>
        <div className="mini-stat"><span>نتائج نهائية</span><strong>{formatNumber(data?.items?.filter((item) => item.final_score !== null).length)}</strong></div>
        <div className="mini-stat"><span>بانتظار الاعتماد</span><strong>{formatNumber(data?.items?.filter((item) => item.final_score === null).length)}</strong></div>
      </div>
      <Card title="كشف الدرجات" subtitle="تظهر الدرجة النهائية فقط بعد اعتماد جميع أسئلة الطالب."
        action={<div className="inline-actions"><Button size="sm" variant="secondary" onClick={() => downloadFile(`/reports/exams/${examId}/export?format=xlsx`, `madar-exam-${examId}.xlsx`)}>تنزيل Excel</Button><Button size="sm" variant="secondary" onClick={() => downloadFile(`/reports/exams/${examId}/export?format=csv`, `madar-exam-${examId}.csv`)}>تنزيل CSV</Button></div>}>
        {data?.items?.length ? <div className="table-wrap">
          <table><thead><tr><th>الطالب</th><th>الرقم الأكاديمي</th><th>الحالة</th><th>الإنجاز</th><th>الدرجة النهائية</th></tr></thead>
            <tbody>{data.items.map((item) => (
              <tr key={item.StudentId}>
                <td><strong>{item.FullName}</strong></td><td>{item.AcademicId}</td><td><Status value={item.result_status} /></td>
                <td><div className="progress-cell"><span>{item.approved_count}/{item.question_count}</span><div className="progress-track"><i style={{ width: `${item.completion_percent}%` }} /></div></div></td>
                <td><strong>{item.final_score === null ? 'غير متاحة بعد' : `${formatNumber(item.final_score)} / ${formatNumber(data.exam.TotalMarks)}`}</strong></td>
              </tr>
            ))}</tbody>
          </table>
        </div> : <Empty title="لا توجد نتائج" detail="سجّل الطلاب وأضف أسئلة وأوراق إجابة حتى تظهر النتائج." />}
      </Card>
      {analytics && (
        <Card title="ملخص التحليل" subtitle="المؤشرات المحسوبة من النتائج المعتمدة فقط.">
          <div className="analytics-grid">
            <div><span>متوسط الدرجات</span><strong>{analytics.summary?.average_final_percent == null ? '—' : `${formatNumber(analytics.summary.average_percent)}%`}</strong></div>
            <div><span>نسبة النجاح</span><strong>{analytics.summary?.pass_rate_percent == null ? '—' : `${formatNumber(analytics.summary.pass_rate_percent)}%`}</strong></div>
            <div><span>عدد الناجحين</span><strong>{formatNumber(analytics.summary?.passed_count)}</strong></div>
            <div><span>عدد الراسبين</span><strong>{formatNumber(analytics.summary?.failed_count)}</strong></div>
          </div>
        </Card>
      )}
    </div>
  )
}

export default function ExamWorkspace({ examId, user, onBack, notify, initialSheetId }) {
  const [exam, setExam] = useState(null)
  const [tab, setTab] = useState(initialSheetId ? 'sheets' : 'overview')
  const [sheetId, setSheetId] = useState(initialSheetId || null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setExam(await api(`/academic/exams/${examId}`)) }
    catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }, [examId])
  useEffect(() => { load() }, [load])

  const openSheet = (id) => { setSheetId(id); setTab('review') }
  const tabs = [
    ['overview', 'نظرة عامة'],
    ['questions', 'الأسئلة'],
    ['enrollments', 'تسجيل الطلاب'],
    ['sheets', 'أوراق الإجابة'],
    ['results', 'النتائج'],
  ]

  if (loading && !exam) return <Loading label="جارٍ فتح الاختبار..." />
  if (!exam) return <Alert tone="danger">{error || 'تعذر تحميل الاختبار.'}</Alert>

  if (tab === 'review' && sheetId) {
    return <SheetReview sheetId={sheetId} user={user} onBack={() => { setSheetId(null); setTab('sheets') }} notify={notify} />
  }

  return (
    <div className="page-stack">
      <div className="back-row"><Button variant="ghost" onClick={onBack}>→ قائمة الاختبارات</Button><span>مساحة إدارة الاختبار</span></div>
      <div className="exam-workspace-hero">
        <div className="exam-icon-large">▤</div>
        <div className="exam-workspace-info"><div className="eyebrow">{exam.SubjectName} · اختبار #{exam.ExamId}</div><h1>{exam.Title}</h1><p>{formatDate(exam.ExamDate)} <span>•</span> الدرجة الكلية {formatNumber(exam.TotalMarks)}</p></div>
        <div className="exam-workspace-counts"><div><strong>{formatNumber(exam.QuestionCount)}</strong><span>سؤال</span></div><div><strong>{formatNumber(exam.EnrolledCount)}</strong><span>طالب</span></div></div>
      </div>
      {error && <Alert tone="danger">{error}</Alert>}
      <nav className="tabs-nav" aria-label="أقسام الاختبار">
        {tabs.map(([key, label]) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}
      </nav>
      {tab === 'overview' && (
        <div className="dashboard-columns">
          <Card title="ملخص الاختبار" subtitle="بيانات محفوظة في قاعدة البيانات.">
            <div className="detail-list"><div><span>اسم المادة</span><strong>{exam.SubjectName}</strong></div><div><span>تاريخ الاختبار</span><strong>{formatDate(exam.ExamDate)}</strong></div><div><span>الدرجة الكلية</span><strong>{formatNumber(exam.TotalMarks)}</strong></div><div><span>الدرجات الموزعة على الأسئلة</span><strong>{formatNumber(exam.AllocatedQuestionMarks)}</strong></div></div>
          </Card>
          <Card title="خطوات العمل" subtitle="ترتيب سير العمل المقترح.">
            <ol className="workflow-steps"><li>إضافة أسئلة الاختبار ومفتاح الإجابة.</li><li>تسجيل الطلاب المشاركين.</li><li>رفع صور أوراق الإجابة.</li><li>ربط مناطق الإجابة وتشغيل HTR.</li><li>مراجعة الإجابات واقتراح الدرجات.</li><li>اعتماد النتائج النهائية وتصدير كشف الدرجات.</li></ol>
          </Card>
        </div>
      )}
      {tab === 'questions' && <QuestionsTab examId={examId} user={user} notify={notify} />}
      {tab === 'enrollments' && <EnrollmentTab examId={examId} user={user} notify={notify} />}
      {tab === 'sheets' && <SheetsTab examId={examId} user={user} notify={notify} onOpenSheet={openSheet} />}
      {tab === 'results' && <ResultsTab examId={examId} />}
    </div>
  )
}
