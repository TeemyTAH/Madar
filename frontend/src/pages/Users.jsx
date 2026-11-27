import { useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, Card, Field, PageTitle } from '../components/common'

const empty = { username: '', full_name: '', password: '', role_name: 'Teacher' }

export default function Users({ notify }) {
  const [form, setForm] = useState(empty)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [created, setCreated] = useState(null)

  const submit = async (event) => {
    event.preventDefault(); setBusy(true); setError(''); setCreated(null)
    try {
      const result = await api('/auth/users', { method: 'POST', body: form })
      setCreated(result); setForm(empty)
      notify('تم إنشاء حساب المستخدم بنجاح.', 'success')
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="page-stack">
      <PageTitle eyebrow="إدارة النظام" title="حسابات المستخدمين" subtitle="إنشاء حسابات المسؤولين والمعلمين والمراجعين وفق صلاحيات النظام." />
      {error && <Alert tone="danger" onClose={() => setError('')}>{error}</Alert>}
      {created && <Alert tone="success" onClose={() => setCreated(null)}>تم إنشاء الحساب: {created.full_name} · {created.role_name} · رقم المستخدم #{created.user_id}</Alert>}
      <div className="dashboard-columns">
        <Card title="إنشاء حساب جديد" subtitle="هذه العملية متاحة للمسؤول Admin فقط.">
          <form className="form-stack" onSubmit={submit}>
            <Field label="اسم المستخدم"><input required minLength="3" maxLength="80" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} autoComplete="off" /></Field>
            <Field label="الاسم الكامل"><input required minLength="2" maxLength="200" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
            <Field label="كلمة المرور" hint="12 حرفاً على الأقل. استخدم كلمة مرور قوية وفريدة."><input required type="password" minLength="12" maxLength="256" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" /></Field>
            <Field label="الدور"><select value={form.role_name} onChange={(e) => setForm({ ...form, role_name: e.target.value })}><option value="Teacher">معلم Teacher</option><option value="Reviewer">مراجع Reviewer</option><option value="Admin">مسؤول Admin</option></select></Field>
            <Button type="submit" disabled={busy}>{busy ? 'جارٍ إنشاء الحساب...' : 'إنشاء الحساب'}</Button>
          </form>
        </Card>
        <Card title="الأدوار والصلاحيات">
          <div className="role-list">
            <div><span className="role-icon role-admin">A</span><section><strong>Admin · مسؤول</strong><p>إدارة المستخدمين والبيانات الأكاديمية واعتماد الدرجات النهائية.</p></section></div>
            <div><span className="role-icon role-teacher">T</span><section><strong>Teacher · معلم</strong><p>إدارة الطلاب والاختبارات والأسئلة، رفع الإجابات، مراجعة النصوص وتعديل الدرجات.</p></section></div>
            <div><span className="role-icon role-reviewer">R</span><section><strong>Reviewer · مراجع</strong><p>عرض السجلات والتقارير وكشوف الدرجات دون إجراء تغييرات.</p></section></div>
          </div>
          <div className="workflow-note"><span>ⓘ</span><p>لا تعرض الواجهة كلمات المرور بعد إنشاء الحساب. تحفظ كلمات المرور في الخادم بصيغة مشتقة PBKDF2، ولا تُرسل إلى قاعدة البيانات من المتصفح مباشرة.</p></div>
        </Card>
      </div>
    </div>
  )
}
