import { formatDate, formatNumber } from '../lib/format'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, Card, Empty, Field, Loading, Modal, PageTitle } from '../components/common'

const emptyExam = { title: '', subject_name: '', exam_date: '', total_marks: '100' }

export default function Exams({ user, onOpenExam, notify }) {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [form, setForm] = useState(emptyExam)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const result = await api(`/academic/exams?limit=100&search=${encodeURIComponent(query)}`)
      setItems(result.items || []); setTotal(result.total || 0)
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }, [query])

  useEffect(() => { load() }, [load])

  const create = async (event) => {
    event.preventDefault(); setSaving(true); setError('')
    try {
      const created = await api('/academic/exams', {
        method: 'POST',
        body: { ...form, total_marks: Number(form.total_marks), exam_date: form.exam_date || null },
      })
      setModalOpen(false); setForm(emptyExam)
      notify('تم إنشاء الاختبار وحفظه في قاعدة البيانات.', 'success')
      await load()
      onOpenExam(created.ExamId)
    } catch (err) { setError(err.message) }
    finally { setSaving(false) }
  }

  return (
    <div className="page-stack">
      <PageTitle eyebrow="الإدارة الأكاديمية" title="الاختبارات" subtitle="إنشاء الاختبارات، إعداد الأسئلة، تسجيل الطلاب، ومتابعة النتائج."
        actions={user?.role_name !== 'Reviewer' ? <Button onClick={() => { setForm(emptyExam); setModalOpen(true) }}>＋ إنشاء اختبار</Button> : null} />
      {error && <Alert tone="danger" onClose={() => setError('')}>{error}</Alert>}
      <Card>
        <div className="toolbar">
          <div className="search-field"><span>⌕</span><input value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && setQuery(search)} placeholder="ابحث باسم الاختبار أو المادة..." /></div>
          <Button variant="secondary" onClick={() => setQuery(search)}>بحث</Button>
          <span className="toolbar-count">{total} اختبار</span>
        </div>
        {loading ? <Loading /> : items.length ? (
          <div className="exam-grid">
            {items.map((exam) => (
              <button className="exam-card" key={exam.ExamId} onClick={() => onOpenExam(exam.ExamId)}>
                <div className="exam-card-top"><span className="exam-symbol">▤</span><span className="id-chip">#{exam.ExamId}</span></div>
                <h3>{exam.Title}</h3>
                <p>{exam.SubjectName}</p>
                <div className="exam-card-meta">
                  <span>◷ {formatDate(exam.ExamDate)}</span>
                  <span>الدرجة: {formatNumber(exam.TotalMarks)}</span>
                </div>
                <div className="exam-card-footer">
                  <span>{formatNumber(exam.QuestionCount)} أسئلة</span>
                  <span>{formatNumber(exam.EnrolledCount)} طلاب</span>
                  <b>فتح التفاصيل ←</b>
                </div>
              </button>
            ))}
          </div>
        ) : <Empty title="لا توجد اختبارات" detail="أنشئ اختبارك الأول ثم أضف أسئلته وسجّل الطلاب فيه." />}
      </Card>

      {modalOpen && (
        <Modal title="إنشاء اختبار جديد" subtitle="أدخل بيانات الاختبار الأساسية." onClose={() => setModalOpen(false)}>
          <form className="form-stack" onSubmit={create}>
            <Field label="اسم الاختبار"><input required minLength="2" maxLength="200" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="مثال: اختبار نهاية الفصل" /></Field>
            <Field label="المادة"><input required minLength="2" maxLength="120" value={form.subject_name} onChange={(e) => setForm({ ...form, subject_name: e.target.value })} placeholder="مثال: اللغة العربية" /></Field>
            <div className="form-row">
              <Field label="تاريخ الاختبار"><input type="date" value={form.exam_date} onChange={(e) => setForm({ ...form, exam_date: e.target.value })} /></Field>
              <Field label="الدرجة الكلية"><input required type="number" min="0.01" step="0.25" value={form.total_marks} onChange={(e) => setForm({ ...form, total_marks: e.target.value })} /></Field>
            </div>
            <div className="form-actions"><Button type="button" variant="secondary" onClick={() => setModalOpen(false)}>إلغاء</Button><Button type="submit" disabled={saving}>{saving ? 'جارٍ الإنشاء...' : 'إنشاء الاختبار'}</Button></div>
          </form>
        </Modal>
      )}
    </div>
  )
}
