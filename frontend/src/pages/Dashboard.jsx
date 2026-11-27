import { formatDate, formatNumber } from '../lib/format'
import { useCallback, useEffect, useState } from 'react'
import { api, healthCheck } from '../lib/api'
import { Alert, Button, Card, Empty, Loading, PageTitle, Stat } from '../components/common'

export default function Dashboard({ onOpenExam }) {
  const [data, setData] = useState(null)
  const [health, setHealth] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      const [overview, status] = await Promise.all([
        api('/reports/overview'),
        healthCheck().catch(() => null),
      ])
      setData(overview)
      setHealth(status)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (busy && !data) return <Loading label="جارٍ تحميل لوحة المعلومات..." />

  const summary = data?.summary || {}
  const metrics = [
    ['الطلاب', summary.Students, '♙', 'blue'],
    ['الاختبارات', summary.Exams, '▤', 'violet'],
    ['المعلمون النشطون', summary.ActiveTeachers, '♧', 'teal'],
    ['التسجيلات', summary.Enrollments, '◎', 'amber'],
    ['أوراق الإجابة', summary.AnswerSheets, '▧', 'blue'],
    ['الصفحات المرفوعة', summary.AnswerPages, '▤', 'violet'],
    ['إجابات معتمدة', summary.ApprovedAnswers, '✓', 'teal'],
    ['بانتظار مراجعة OCR', summary.PendingOcrReview, '⌕', 'amber'],
  ]

  return (
    <div className="page-stack">
      <PageTitle
        eyebrow="نظرة عامة"
        title="لوحة مدار"
        subtitle="متابعة الاختبارات والإجابات والمعالجة والتصحيح من مكان واحد."
        actions={<Button variant="secondary" onClick={load} disabled={busy}>↻ تحديث البيانات</Button>}
      />
      {error && <Alert tone="danger">{error}</Alert>}
      {health && (
        <div className="connection-strip">
          <span className="connection-dot" />
          <strong>قاعدة البيانات متصلة</strong>
          <span>SQLite · API يعمل</span>
          <span className="connection-path" title={health.database_path}>{health.database_path}</span>
        </div>
      )}
      {!health && data && (
        <div className="connection-strip connection-muted">
          <span className="connection-dot" />
          <strong>تم تحميل بيانات التقارير</strong>
          <span>حالة فحص الاتصال غير متاحة حالياً</span>
        </div>
      )}
      <div className="stats-grid">
        {metrics.map(([label, value, icon, tone]) => (
          <Stat key={label} label={label} value={formatNumber(value)} icon={icon} tone={tone} />
        ))}
      </div>
      <div className="dashboard-columns">
        <Card title="أحدث الاختبارات" subtitle="آخر الاختبارات المسجلة في قاعدة البيانات">
          {data?.recent_exams?.length ? (
            <div className="table-wrap">
              <table>
                <thead><tr><th>الاختبار</th><th>المادة</th><th>التاريخ</th><th>الطلاب</th><th /></tr></thead>
                <tbody>
                  {data.recent_exams.map((exam) => (
                    <tr key={exam.ExamId}>
                      <td><strong>{exam.Title}</strong><small className="cell-sub">#{exam.ExamId}</small></td>
                      <td>{exam.SubjectName}</td>
                      <td>{formatDate(exam.ExamDate)}</td>
                      <td>{formatNumber(exam.EnrolledCount)}</td>
                      <td><Button size="sm" variant="ghost" onClick={() => onOpenExam(exam.ExamId)}>فتح الاختبار ←</Button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty title="لا توجد اختبارات" detail="أنشئ أول اختبار لتبدأ إدارة عملية التصحيح." />}
        </Card>
        <Card title="مؤشرات المعالجة" subtitle="حالة سير العمل في النظام">
          <div className="process-list">
            <div><span>سجلات الإجابات</span><strong>{formatNumber(summary.AnswerRecords)}</strong></div>
            <div><span>الأوراق المعتمدة بالكامل</span><strong>{formatNumber(summary.FullyApprovedSheets)}</strong></div>
            <div><span>بانتظار مراجعة التصحيح</span><strong>{formatNumber(summary.PendingGradingReview)}</strong></div>
            <div><span>عمليات الذكاء الاصطناعي الفاشلة</span><strong className={summary.FailedAiRuns ? 'text-danger' : ''}>{formatNumber(summary.FailedAiRuns)}</strong></div>
          </div>
          <div className="workflow-note">
            <span>ⓘ</span>
            <p>الدرجات النهائية لا تظهر إلا بعد اعتماد جميع إجابات الطالب. اقتراحات الذكاء الاصطناعي لا تعتمد تلقائياً.</p>
          </div>
        </Card>
      </div>
    </div>
  )
}
