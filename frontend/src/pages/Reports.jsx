import { formatDate, formatNumber } from '../lib/format'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Button, Card, Empty, Loading, PageTitle, Status } from '../components/common'

export default function Reports() {
  const [students, setStudents] = useState([])
  const [search, setSearch] = useState('')
  const [studentId, setStudentId] = useState('')
  const [report, setReport] = useState(null)
  const [overview, setOverview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [reportLoading, setReportLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [summary, studentData] = await Promise.all([
        api('/reports/overview'),
        api('/academic/students?limit=200'),
      ])
      setOverview(summary)
      setStudents(studentData.items || [])
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const openReport = async (id) => {
    setStudentId(String(id)); setReportLoading(true); setError('')
    try { setReport(await api(`/reports/students/${id}`)) }
    catch (err) { setError(err.message); setReport(null) }
    finally { setReportLoading(false) }
  }

  const filtered = students.filter((student) => `${student.FullName} ${student.AcademicId}`.toLowerCase().includes(search.toLowerCase()))

  if (loading) return <Loading label="جارٍ تحميل التقارير..." />

  return (
    <div className="page-stack">
      <PageTitle eyebrow="التقارير والتحليلات" title="تقارير الطلاب" subtitle="عرض السجل الأكاديمي والنتائج النهائية المعتمدة لكل طالب." />
      {error && <Alert tone="danger" onClose={() => setError('')}>{error}</Alert>}
      <div className="stats-grid stats-grid-compact">
        <div className="mini-stat"><span>إجمالي الطلاب</span><strong>{formatNumber(overview?.summary?.Students)}</strong></div>
        <div className="mini-stat"><span>الاختبارات</span><strong>{formatNumber(overview?.summary?.Exams)}</strong></div>
        <div className="mini-stat"><span>الصفحات المرفوعة</span><strong>{formatNumber(overview?.summary?.AnswerPages)}</strong></div>
        <div className="mini-stat"><span>الدرجات المعتمدة</span><strong>{formatNumber(overview?.summary?.ApprovedAnswers)}</strong></div>
      </div>
      <div className="report-columns">
        <Card title="اختيار الطالب" subtitle="ابحث بالاسم أو الرقم الأكاديمي لعرض السجل.">
          <div className="search-field search-field-full"><span>⌕</span><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="بحث..." /></div>
          <div className="student-picker">
            {filtered.map((student) => (
              <button key={student.StudentId} className={`student-picker-item ${String(student.StudentId) === studentId ? 'selected' : ''}`} onClick={() => openReport(student.StudentId)}>
                <span className="avatar-small">{student.FullName?.trim()?.charAt(0) || 'ط'}</span>
                <span><strong>{student.FullName}</strong><small>{student.AcademicId}</small></span>
                <b>←</b>
              </button>
            ))}
            {!filtered.length && <Empty title="لا يوجد طلاب مطابقون" />}
          </div>
        </Card>
        <div className="report-detail">
          {reportLoading ? <Loading /> : report ? (
            <>
              <div className="report-student-head">
                <div><div className="eyebrow">السجل الأكاديمي</div><h2>{report.student.FullName}</h2><p>{report.student.AcademicId} · رقم الطالب #{report.student.StudentId}</p></div>
              </div>
              <div className="stats-grid stats-grid-compact">
                <div className="mini-stat"><span>اختبارات مسجل بها</span><strong>{formatNumber(report.summary.enrolled_exams)}</strong></div>
                <div className="mini-stat"><span>نتائج نهائية</span><strong>{formatNumber(report.summary.final_results_count)}</strong></div>
                <div className="mini-stat"><span>متوسط النتائج النهائية</span><strong>{report.summary.average_final_percent == null ? '—' : `${formatNumber(report.summary.average_final_percent)}%`}</strong></div>
              </div>
              <Card title="نتائج الاختبارات">
                {report.exams.length ? <div className="table-wrap"><table><thead><tr><th>الاختبار</th><th>المادة</th><th>التاريخ</th><th>الحالة</th><th>النتيجة</th></tr></thead>
                  <tbody>{report.exams.map((exam) => <tr key={exam.ExamId}>
                    <td><strong>{exam.Title}</strong></td><td>{exam.SubjectName}</td><td>{formatDate(exam.ExamDate)}</td><td><Status value={exam.result_status} /></td>
                    <td><strong>{exam.final_score == null ? 'بانتظار الاعتماد' : `${formatNumber(exam.final_score)} / ${formatNumber(exam.TotalMarks)} (${formatNumber(exam.percentage)}%)`}</strong></td>
                  </tr>)}</tbody></table></div> : <Empty title="لا توجد اختبارات لهذا الطالب" />}
              </Card>
              <div className="policy-note">تُعرض النتائج النهائية فقط بعد اعتماد جميع أسئلة الاختبار. الدرجات المقترحة أو غير المعتمدة لا تدخل في المتوسط.</div>
            </>
          ) : <Card><Empty title="اختر طالباً لعرض تقريره" detail="سيظهر هنا ملخص الأداء والاختبارات والنتائج النهائية." /></Card>}
        </div>
      </div>
    </div>
  )
}
