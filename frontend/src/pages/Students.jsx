import { formatDate } from '../lib/format'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, Card, Empty, Field, Loading, Modal, PageTitle } from '../components/common'

const blank = { academic_id: '', full_name: '' }

export default function Students({ user, notify }) {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [form, setForm] = useState(blank)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const result = await api(`/academic/students?limit=100&search=${encodeURIComponent(query)}`)
      setItems(result.items || []); setTotal(result.total || 0)
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }, [query])

  useEffect(() => { load() }, [load])

  const openCreate = () => { setEditing(null); setForm(blank); setModalOpen(true) }
  const openEdit = (student) => {
    setEditing(student)
    setForm({ academic_id: student.AcademicId, full_name: student.FullName })
    setModalOpen(true)
  }
  const save = async (event) => {
    event.preventDefault()
    setSaving(true); setError('')
    try {
      if (editing) await api(`/academic/students/${editing.StudentId}`, { method: 'PATCH', body: form })
      else await api('/academic/students', { method: 'POST', body: form })
      setEditing(null); setForm(blank); setModalOpen(false)
      notify(editing ? 'تم تحديث بيانات الطالب.' : 'تمت إضافة الطالب إلى قاعدة البيانات.', 'success')
      await load()
    } catch (err) { setError(err.message) }
    finally { setSaving(false) }
  }
  const remove = async (student) => {
    if (!window.confirm(`هل تريد حذف الطالب "${student.FullName}"؟ لا يمكن حذف طالب مسجل في اختبار.`)) return
    try {
      await api(`/academic/students/${student.StudentId}`, { method: 'DELETE' })
      notify('تم حذف الطالب.', 'success'); await load()
    } catch (err) { setError(err.message) }
  }

  return (
    <div className="page-stack">
      <PageTitle eyebrow="الإدارة الأكاديمية" title="الطلاب" subtitle="إدارة السجل الأكاديمي للطلاب وربطه بالاختبارات."
        actions={user.role_name !== 'Reviewer' ? <Button onClick={openCreate}>＋ إضافة طالب</Button> : null} />
      {error && <Alert tone="danger" onClose={() => setError('')}>{error}</Alert>}
      <Card>
        <div className="toolbar">
          <div className="search-field"><span>⌕</span><input value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && setQuery(search)} placeholder="ابحث بالاسم أو الرقم الأكاديمي..." /></div>
          <Button variant="secondary" onClick={() => setQuery(search)}>بحث</Button>
          <span className="toolbar-count">{total} طالب</span>
        </div>
        {loading ? <Loading /> : items.length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>الرقم الأكاديمي</th><th>اسم الطالب</th><th>تاريخ الإضافة</th><th>رقم السجل</th><th>الإجراءات</th></tr></thead>
              <tbody>{items.map((student) => (
                <tr key={student.StudentId}>
                  <td><span className="id-chip">{student.AcademicId}</span></td>
                  <td><strong>{student.FullName}</strong></td>
                  <td>{formatDate(student.CreatedAt)}</td>
                  <td>#{student.StudentId}</td>
                  <td className="actions-cell">
                    {user.role_name !== 'Reviewer' && <Button size="sm" variant="ghost" onClick={() => openEdit(student)}>تعديل</Button>}
                    {user.role_name === 'Admin' && <Button size="sm" variant="danger-ghost" onClick={() => remove(student)}>حذف</Button>}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <Empty title="لم يتم العثور على طلاب" detail="أضف طالباً جديداً أو غيّر كلمات البحث." />}
      </Card>

      {modalOpen && (
        <Modal title={editing ? 'تعديل بيانات الطالب' : 'إضافة طالب جديد'} subtitle="سيتم حفظ البيانات مباشرة في قاعدة بيانات Madar." onClose={() => { setEditing(null); setForm(blank); setModalOpen(false) }}>
          <form className="form-stack" onSubmit={save}>
            <Field label="الرقم الأكاديمي"><input required maxLength="80" value={form.academic_id} onChange={(e) => setForm({ ...form, academic_id: e.target.value })} placeholder="مثال: 2026-001" /></Field>
            <Field label="اسم الطالب"><input required minLength="2" maxLength="200" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} placeholder="الاسم الرباعي" /></Field>
            <div className="form-actions"><Button type="button" variant="secondary" onClick={() => { setEditing(null); setForm(blank); setModalOpen(false) }}>إلغاء</Button><Button type="submit" disabled={saving}>{saving ? 'جارٍ الحفظ...' : 'حفظ البيانات'}</Button></div>
          </form>
        </Modal>
      )}
    </div>
  )
}
