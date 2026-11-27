import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, setToken, getToken } from './lib/api'
import { Alert, Button, Field, Loading } from './components/common'
import Dashboard from './pages/Dashboard'
import Students from './pages/Students'
import Exams from './pages/Exams'
import ExamWorkspace from './pages/ExamWorkspace'
import Users from './pages/Users'
import Reports from './pages/Reports'
import './App.css'

const navigation = [
  { id: 'dashboard', label: 'لوحة المعلومات', icon: '◫', roles: ['Admin', 'Teacher', 'Reviewer'] },
  { id: 'students', label: 'الطلاب', icon: '♙', roles: ['Admin', 'Teacher', 'Reviewer'] },
  { id: 'exams', label: 'الاختبارات', icon: '▤', roles: ['Admin', 'Teacher', 'Reviewer'] },
  { id: 'reports', label: 'التقارير', icon: '▥', roles: ['Admin', 'Teacher', 'Reviewer'] },
  { id: 'users', label: 'المستخدمون', icon: '♧', roles: ['Admin'] },
]

const roleLabels = { Admin: 'مسؤول النظام', Teacher: 'معلم', Reviewer: 'مراجع' }

function AuthScreen({ onAuthenticated }) {
  const [mode, setMode] = useState('login')
  const [login, setLogin] = useState({ username: '', password: '' })
  const [admin, setAdmin] = useState({ username: '', full_name: '', password: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event) => {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const result = mode === 'login'
        ? await api('/auth/login', { method: 'POST', body: login })
        : await api('/auth/bootstrap-admin', { method: 'POST', body: admin })
      setToken(result.access_token)
      onAuthenticated(result.user)
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="auth-screen" dir="rtl">
      <div className="auth-backdrop" />
      <div className="auth-layout">
        <section className="auth-brand-panel">
          <div className="brand-lockup"><span className="brand-mark">م</span><div><strong>مَدار</strong><small>SMART ARABIC GRADER</small></div></div>
          <div className="auth-brand-copy">
            <span className="eyebrow">منظومة التصحيح الذكي</span>
            <h1>من ورقة الإجابة<br />إلى نتيجة موثوقة.</h1>
            <p>منصة موحدة لإدارة الاختبارات، قراءة الإجابات العربية، مراجعة التصحيح، واعتماد النتائج.</p>
          </div>
          <div className="auth-feature-list">
            <div><span>01</span><strong>إدارة أكاديمية مركزية</strong></div>
            <div><span>02</span><strong>معالجة صور وقراءة HTR</strong></div>
            <div><span>03</span><strong>مراجعة بشرية واعتماد آمن</strong></div>
          </div>
          <div className="auth-brand-footer">MADAR · LOCAL-FIRST ACADEMIC PLATFORM</div>
        </section>

        <section className="auth-form-panel">
          <div className="auth-mobile-brand"><span className="brand-mark">م</span><strong>مَدار</strong></div>
          <div className="auth-form-heading"><span className="eyebrow">{mode === 'login' ? 'مرحباً بعودتك' : 'التهيئة الأولية'}</span><h2>{mode === 'login' ? 'تسجيل الدخول' : 'إنشاء المسؤول الأول'}</h2><p>{mode === 'login' ? 'أدخل بيانات حسابك للمتابعة إلى مساحة العمل.' : 'تُستخدم هذه الخطوة مرة واحدة فقط عند إعداد قاعدة بيانات جديدة.'}</p></div>
          <div className="auth-mode-switch">
            <button className={mode === 'login' ? 'active' : ''} onClick={() => { setMode('login'); setError('') }}>تسجيل الدخول</button>
            <button className={mode === 'bootstrap' ? 'active' : ''} onClick={() => { setMode('bootstrap'); setError('') }}>إعداد أول مسؤول</button>
          </div>
          {error && <Alert tone="danger">{error}</Alert>}
          <form className="form-stack auth-form" onSubmit={submit}>
            {mode === 'bootstrap' && <Field label="الاسم الكامل"><input required minLength="2" maxLength="200" value={admin.full_name} onChange={(e) => setAdmin({ ...admin, full_name: e.target.value })} autoComplete="name" /></Field>}
            <Field label="اسم المستخدم"><input required minLength={mode === 'bootstrap' ? 3 : 1} maxLength="80" value={mode === 'login' ? login.username : admin.username} onChange={(e) => mode === 'login' ? setLogin({ ...login, username: e.target.value }) : setAdmin({ ...admin, username: e.target.value })} autoComplete="username" /></Field>
            <Field label="كلمة المرور" hint={mode === 'bootstrap' ? '12 حرفاً على الأقل.' : undefined}><input required type="password" minLength={mode === 'bootstrap' ? 12 : 1} maxLength="256" value={mode === 'login' ? login.password : admin.password} onChange={(e) => mode === 'login' ? setLogin({ ...login, password: e.target.value }) : setAdmin({ ...admin, password: e.target.value })} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} /></Field>
            <Button type="submit" block disabled={busy}>{busy ? 'جارٍ التحقق...' : mode === 'login' ? 'دخول إلى مدار ←' : 'إنشاء حساب المسؤول ←'}</Button>
          </form>
          <div className="auth-security"><span>◈</span><p>اتصال محلي آمن · صلاحيات حسب الدور · قاعدة بيانات SQLite</p></div>
        </section>
      </div>
    </div>
  )
}

export default function App() {
  const [user, setUser] = useState(null)
  const [authLoading, setAuthLoading] = useState(Boolean(getToken()))
  const [activePage, setActivePage] = useState('dashboard')
  const [selectedExamId, setSelectedExamId] = useState(null)
  const [notice, setNotice] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const notify = useCallback((message, tone = 'info') => {
    setNotice({ message, tone })
    window.clearTimeout(window.__madarToastTimer)
    window.__madarToastTimer = window.setTimeout(() => setNotice(null), 4500)
  }, [])

  useEffect(() => {
    const unauthorized = () => {
      setUser(null)
      setToken(null)
      setActivePage('dashboard')
      notify('انتهت الجلسة أو لم يعد رمز الدخول صالحاً. سجّل الدخول مرة أخرى.', 'warning')
    }
    window.addEventListener('madar:unauthorized', unauthorized)
    return () => window.removeEventListener('madar:unauthorized', unauthorized)
  }, [notify])

  useEffect(() => {
    const token = getToken()
    if (!token) return
    api('/auth/me')
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setAuthLoading(false))
  }, [])

  const handleAuthenticated = (authenticatedUser) => {
    setUser(authenticatedUser)
    setActivePage('dashboard')
    notify(`مرحباً ${authenticatedUser.full_name || authenticatedUser.username}`, 'success')
  }

  const logout = () => {
    setToken(null); setUser(null); setSelectedExamId(null); setActivePage('dashboard')
    notify('تم تسجيل الخروج.', 'info')
  }

  const openExam = (examId) => {
    setSelectedExamId(examId)
    setActivePage('exam-workspace')
  }

  const navItems = useMemo(() => navigation.filter((item) => item.roles.includes(user?.role_name)), [user])
  const currentTitle = activePage === 'exam-workspace' ? 'مساحة الاختبار' : navigation.find((item) => item.id === activePage)?.label || 'مدار'

  if (authLoading) return <div className="app-loading"><Loading label="جارٍ التحقق من الجلسة..." /></div>
  if (!user) return <AuthScreen onAuthenticated={handleAuthenticated} />

  return (
    <div className="app-shell" dir="rtl">
      {sidebarOpen && <button className="mobile-scrim" aria-label="إغلاق القائمة" onClick={() => setSidebarOpen(false)} />}
      <aside className={`sidebar ${sidebarOpen ? 'sidebar-open' : ''}`}>
        <div className="sidebar-brand">
          <span className="brand-mark">م</span>
          <div><strong>مَدار</strong><small>SMART GRADER</small></div>
          <button className="sidebar-close" onClick={() => setSidebarOpen(false)} aria-label="إغلاق القائمة">×</button>
        </div>
        <div className="sidebar-section-label">القائمة الرئيسية</div>
        <nav className="side-nav">
          {navItems.map((item) => (
            <button key={item.id} className={`nav-item ${(activePage === item.id || (activePage === 'exam-workspace' && item.id === 'exams')) ? 'active' : ''}`} onClick={() => { setActivePage(item.id); setSidebarOpen(false) }}>
              <span className="nav-icon">{item.icon}</span><span>{item.label}</span>
              {(activePage === item.id) && <i />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-status"><span className="connection-dot" /><div><strong>النظام المحلي</strong><small>قاعدة البيانات عبر API</small></div></div>
          <div className="sidebar-user">
            <span className="user-avatar">{(user.full_name || user.username || 'م').charAt(0)}</span>
            <div className="user-meta"><strong>{user.full_name || user.username}</strong><small>{roleLabels[user.role_name] || user.role_name}</small></div>
            <button className="logout-button" onClick={logout} title="تسجيل الخروج">⇥</button>
          </div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="topbar-start">
            <button className="menu-toggle" onClick={() => setSidebarOpen(true)} aria-label="فتح القائمة">☰</button>
            <div><span className="topbar-kicker">منظومة مدار</span><strong>{currentTitle}</strong></div>
          </div>
          <div className="topbar-end">
            <span className="topbar-date">{new Intl.DateTimeFormat('ar', { dateStyle: 'full' }).format(new Date())}</span>
            <div className="topbar-user"><span className="user-avatar">{(user.full_name || 'م').charAt(0)}</span><div><strong>{user.full_name || user.username}</strong><small>{roleLabels[user.role_name]}</small></div></div>
          </div>
        </header>

        <div className="content-area">
          {notice && <div className="toast-wrap"><Alert tone={notice.tone} onClose={() => setNotice(null)}>{notice.message}</Alert></div>}
          {activePage === 'dashboard' && <Dashboard onOpenExam={openExam} />}
          {activePage === 'students' && <Students user={user} notify={notify} />}
          {activePage === 'exams' && <Exams user={user} onOpenExam={openExam} notify={notify} />}
          {activePage === 'exam-workspace' && selectedExamId && <ExamWorkspace examId={selectedExamId} user={user} onBack={() => setActivePage('exams')} notify={notify} />}
          {activePage === 'users' && user.role_name === 'Admin' && <Users notify={notify} />}
          {activePage === 'reports' && <Reports />}
          {activePage === 'exam-workspace' && !selectedExamId && <Exams user={user} onOpenExam={openExam} notify={notify} />}
        </div>
        <footer className="app-footer"><span>مَدار · نظام التصحيح الذكي</span><span>Phase 7–8 · Frontend Integration</span></footer>
      </main>
    </div>
  )
}
