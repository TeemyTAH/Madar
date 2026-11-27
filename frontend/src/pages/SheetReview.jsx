import { formatNumber } from '../lib/format'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, apiBlob } from '../lib/api'
import { Alert, Button, Card, Empty, Field, Loading, Modal, Status } from '../components/common'

function clamp(value, min = 0, max = 1) {
  return Math.min(max, Math.max(min, value))
}

function RegionModal({ answer, pages, existing, onClose, onSaved }) {
  const [pageId, setPageId] = useState(pages[0]?.PageId ? String(pages[0].PageId) : '')
  const [imageUrl, setImageUrl] = useState('')
  const [imageBusy, setImageBusy] = useState(false)
  const [selection, setSelection] = useState(null)
  const [dragging, setDragging] = useState(false)
  const start = useRef(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let active = true
    let objectUrl = ''
    if (!pageId) { setImageUrl(''); return undefined }
    setImageBusy(true); setError('')
    apiBlob(`/uploads/pages/${pageId}/image?variant=original`)
      .then((blob) => {
        if (!active) return
        objectUrl = URL.createObjectURL(blob)
        setImageUrl(objectUrl)
      })
      .catch((err) => { if (active) setError(err.message) })
      .finally(() => { if (active) setImageBusy(false) })
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [pageId])

  const point = (event) => {
    const rect = event.currentTarget.getBoundingClientRect()
    return {
      x: clamp((event.clientX - rect.left) / rect.width),
      y: clamp((event.clientY - rect.top) / rect.height),
    }
  }
  const begin = (event) => {
    if (!imageUrl) return
    event.preventDefault()
    event.currentTarget.setPointerCapture?.(event.pointerId)
    const p = point(event)
    start.current = p
    setSelection({ x: p.x, y: p.y, width: 0, height: 0 })
    setDragging(true)
  }
  const move = (event) => {
    if (!dragging || !start.current) return
    const p = point(event)
    const x = Math.min(start.current.x, p.x)
    const y = Math.min(start.current.y, p.y)
    setSelection({
      x, y,
      width: Math.abs(p.x - start.current.x),
      height: Math.abs(p.y - start.current.y),
    })
  }
  const end = () => setDragging(false)

  const saveRegion = async (fullPage = false) => {
    if (!pageId) return
    if (!fullPage && (!selection || selection.width < 0.01 || selection.height < 0.01)) {
      setError('حدد مساحة الإجابة بالسحب على الصورة، أو اختر ربط الصفحة كاملة.')
      return
    }
    setSaving(true); setError('')
    const nextOrder = Math.max(0, ...existing.map((item) => Number(item.SegmentOrder) || 0)) + 1
    const body = {
      page_id: Number(pageId),
      segment_order: nextOrder,
      region_x: fullPage ? null : Number(selection.x.toFixed(6)),
      region_y: fullPage ? null : Number(selection.y.toFixed(6)),
      region_width: fullPage ? null : Number(selection.width.toFixed(6)),
      region_height: fullPage ? null : Number(selection.height.toFixed(6)),
    }
    try {
      await api(`/answers/${answer.AnswerId}/regions`, { method: 'POST', body })
      await onSaved()
      onClose()
    } catch (err) { setError(err.message) }
    finally { setSaving(false) }
  }

  return (
    <Modal title={`ربط منطقة الإجابة · السؤال ${answer.QuestionNumber}`} subtitle="اختر صفحة الطالب واسحب لتحديد منطقة الإجابة فقط. الإحداثيات تحفظ كنسب من أبعاد الصورة." onClose={onClose} wide>
      <div className="form-stack">
        {error && <Alert tone="danger">{error}</Alert>}
        <Field label="صفحة الإجابة">
          <select value={pageId} onChange={(e) => { setPageId(e.target.value); setSelection(null) }}>
            {pages.map((page) => <option key={page.PageId} value={page.PageId}>الصفحة {page.PageNumber} · #{page.PageId}</option>)}
          </select>
        </Field>
        <div className="crop-instructions">اسحب بالماوس أو اللمس حول إجابة السؤال. يمكنك ربط أكثر من منطقة إذا كانت الإجابة موزعة على صفحات متعددة.</div>
        <div className="region-canvas-wrap">
          {imageBusy ? <Loading label="جارٍ تحميل صورة الصفحة..." /> : imageUrl ? (
            <div
              className="region-image-wrap"
              onPointerDown={begin}
              onPointerMove={move}
              onPointerUp={end}
              onPointerCancel={end}
              style={{ touchAction: 'none' }}
            >
              <img src={imageUrl} alt={`صفحة الإجابة ${pageId}`} draggable="false" />
              {selection && <div className="selection-box" style={{
                left: `${selection.x * 100}%`, top: `${selection.y * 100}%`,
                width: `${selection.width * 100}%`, height: `${selection.height * 100}%`,
              }} />}
            </div>
          ) : <Empty title="تعذر عرض الصورة" detail={error || 'لا توجد صورة أصلية لهذه الصفحة.'} />}
        </div>
        <div className="form-actions split-actions">
          <Button variant="secondary" onClick={onClose}>إلغاء</Button>
          <div className="inline-actions">
            <Button variant="secondary" disabled={saving || !pageId} onClick={() => saveRegion(true)}>ربط الصفحة كاملة</Button>
            <Button disabled={saving || !pageId} onClick={() => saveRegion(false)}>{saving ? 'جارٍ الحفظ...' : 'حفظ المنطقة المحددة'}</Button>
          </div>
        </div>
      </div>
    </Modal>
  )
}

function AnswerCard({ answer, question, pages, user, notify, refresh }) {
  const [text, setText] = useState(answer.EditedText ?? answer.ExtractedText ?? '')
  const [choiceId, setChoiceId] = useState(answer.SelectedChoiceId ? String(answer.SelectedChoiceId) : '')
  const [isEmpty, setIsEmpty] = useState(Boolean(answer.IsEmptyAnswer))
  const [regions, setRegions] = useState([])
  const [regionOpen, setRegionOpen] = useState(false)
  const [busy, setBusy] = useState('')
  const [adjustOpen, setAdjustOpen] = useState(false)
  const [score, setScore] = useState(answer.AdjustedScore ?? answer.SuggestedScore ?? '')
  const [justification, setJustification] = useState('')
  const [notes, setNotes] = useState('')
  const [approvalOpen, setApprovalOpen] = useState(false)
  const [approvalScore, setApprovalScore] = useState('')
  const [approvalNote, setApprovalNote] = useState('')
  const [error, setError] = useState('')

  const objective = ['MULTIPLE_CHOICE', 'TRUE_FALSE'].includes(answer.QuestionType)
  const approved = Boolean(answer.IsApproved)
  const canEdit = ['Admin', 'Teacher'].includes(user.role_name) && !approved
  const canAdjust = user.role_name === 'Teacher' && !approved
  const canApprove = user.role_name === 'Admin' && !approved

  const loadRegions = useCallback(async () => {
    try {
      const result = await api(`/answers/${answer.AnswerId}/regions`)
      setRegions(result.regions || [])
    } catch (err) { setError(err.message) }
  }, [answer.AnswerId])

  useEffect(() => {
    setText(answer.EditedText ?? answer.ExtractedText ?? '')
    setChoiceId(answer.SelectedChoiceId ? String(answer.SelectedChoiceId) : '')
    setIsEmpty(Boolean(answer.IsEmptyAnswer))
    setScore(answer.AdjustedScore ?? answer.SuggestedScore ?? '')
  }, [answer])

  useEffect(() => { loadRegions() }, [loadRegions])

  const run = async (key, operation, successText) => {
    setBusy(key); setError('')
    try {
      await operation()
      if (successText) notify(successText, 'success')
      await refresh()
    } catch (err) { setError(err.message) }
    finally { setBusy('') }
  }

  const saveResponse = () => run('save', async () => {
    const body = { is_empty_answer: isEmpty }
    if (objective) body.selected_choice_id = isEmpty || !choiceId ? null : Number(choiceId)
    else body.edited_text = isEmpty ? null : text
    await api(`/academic/answers/${answer.AnswerId}/response`, { method: 'PATCH', body })
  }, 'تم حفظ تصحيح الإجابة.')

  const recognize = () => run('ocr', async () => {
    if (!regions.length) throw new Error('اربط صفحة أو منطقة الإجابة أولاً قبل تشغيل التعرف على الكتابة.')
    await api(`/ai/answers/${answer.AnswerId}/recognize`, { method: 'POST' })
  }, 'انتهى التعرف على الكتابة. راجع النص المستخرج.')

  const evaluate = () => run('grade', async () => {
    await api(`/grading/answers/${answer.AnswerId}/evaluate`, { method: 'POST' })
  }, 'تم إنشاء اقتراح التصحيح. لم يتم اعتماده نهائياً.')

  const adjust = (event) => {
    event.preventDefault()
    run('adjust', async () => {
      await api(`/academic/answers/${answer.AnswerId}/grade`, {
        method: 'PATCH',
        body: { adjusted_score: Number(score), teacher_justification: justification, teacher_notes: notes || null },
      })
      setAdjustOpen(false)
    }, 'تم حفظ الدرجة المعدلة بانتظار الاعتماد الإداري.')
  }

  const approve = (event) => {
    event.preventDefault()
    run('approve', async () => {
      await api(`/academic/answers/${answer.AnswerId}/approve`, {
        method: 'POST',
        body: { approved_score: approvalScore === '' ? null : Number(approvalScore), approval_note: approvalNote },
      })
      setApprovalOpen(false)
    }, 'تم اعتماد درجة الإجابة نهائياً.')
  }

  const pageLabels = regions.map((region) => {
    const page = pages.find((item) => Number(item.PageId) === Number(region.PageId))
    return page ? `ص${page.PageNumber}` : `#${region.PageId}`
  })

  return (
    <article className={`answer-card ${approved ? 'answer-approved' : ''}`}>
      <div className="answer-card-head">
        <div>
          <div className="answer-kicker">السؤال {answer.QuestionNumber} · {answer.QuestionType.replaceAll('_', ' ')}</div>
          <h3>{answer.QuestionText}</h3>
          <small>الدرجة القصوى: {formatNumber(answer.MaxMarks)}</small>
        </div>
        <div className="answer-head-status">
          {approved ? <Status value="FINAL_APPROVED" /> : answer.NeedsOcrReview ? <Status value="REQUIRES_REVIEW" /> : <Status value={answer.NeedsGradingReview ? 'PENDING_REVIEW' : 'NOT_PROCESSED'} />}
          <span className="answer-id">#{answer.AnswerId}</span>
        </div>
      </div>

      {error && <Alert tone="danger" onClose={() => setError('')}>{error}</Alert>}

      {objective ? (
        <Field label="الإجابة المحددة">
          <select disabled={!canEdit} value={choiceId} onChange={(e) => setChoiceId(e.target.value)}>
            <option value="">لم يتم تحديد إجابة</option>
            {(question?.choices || []).map((choice) => (
              <option key={choice.ChoiceId} value={choice.ChoiceId}>{choice.ChoiceLabel} — {choice.ChoiceText}</option>
            ))}
          </select>
        </Field>
      ) : (
        <div className="answer-text-grid">
          <div className="recognized-text">
            <div className="small-label">النص المستخرج من HTR</div>
            <p>{answer.ExtractedText || 'لم يتم استخراج نص بعد.'}</p>
            {answer.OcrConfidence !== null && answer.OcrConfidence !== undefined && <small>ثقة التعرف: {formatNumber(answer.OcrConfidence)}%</small>}
          </div>
          <Field label="النص بعد مراجعة المعلم">
            <textarea rows="4" disabled={!canEdit} value={text} onChange={(e) => setText(e.target.value)} placeholder="راجع النص المستخرج وعدّله عند الحاجة..." />
          </Field>
        </div>
      )}

      <div className="answer-controls">
        <label className="check-line"><input type="checkbox" checked={isEmpty} disabled={!canEdit} onChange={(e) => setIsEmpty(e.target.checked)} /> إجابة فارغة / غير مقروءة</label>
        <div className="inline-actions">
          <span className="region-count">المناطق المرتبطة: {regions.length ? pageLabels.join('، ') : 'لا توجد'}</span>
          {canEdit && <Button size="sm" variant="secondary" onClick={() => setRegionOpen(true)}>＋ ربط منطقة</Button>}
          {canEdit && <Button size="sm" variant="secondary" onClick={saveResponse} disabled={busy !== ''}>{busy === 'save' ? 'حفظ...' : 'حفظ الإجابة'}</Button>}
        </div>
      </div>

      <div className="score-summary">
        <div><span>اقتراح الذكاء الاصطناعي</span><strong>{answer.SuggestedScore === null ? '—' : `${formatNumber(answer.SuggestedScore)} / ${formatNumber(answer.MaxMarks)}`}</strong></div>
        <div><span>درجة المعلم</span><strong>{answer.AdjustedScore === null ? '—' : `${formatNumber(answer.AdjustedScore)} / ${formatNumber(answer.MaxMarks)}`}</strong></div>
        <div><span>الدرجة المعتمدة</span><strong className={approved ? 'text-success' : ''}>{answer.ApprovedScore === null ? '—' : `${formatNumber(answer.ApprovedScore)} / ${formatNumber(answer.MaxMarks)}`}</strong></div>
      </div>
      {answer.SuggestedJustification && <div className="evaluation-note"><strong>تفسير الاقتراح:</strong> {answer.SuggestedJustification}</div>}
      {answer.TeacherJustification && <div className="evaluation-note"><strong>مبرر تعديل المعلم:</strong> {answer.TeacherJustification}</div>}
      {canApprove && Boolean(answer.NeedsGradingReview) && answer.AdjustedScore === null && <div className="evaluation-note">هذه الإجابة تتطلب مراجعة المعلم أولاً قبل اعتمادها نهائياً.</div>}

      {!approved && (
        <div className="answer-actions">
          {canEdit && <Button size="sm" variant="secondary" onClick={() => setRegionOpen(true)}>تحديد المنطقة</Button>}
          {canEdit && <Button size="sm" variant="secondary" onClick={recognize} disabled={busy !== '' || !regions.length}>{busy === 'ocr' ? 'جارٍ التعرف...' : 'تشغيل HTR'}</Button>}
          {canEdit && <Button size="sm" variant="secondary" onClick={evaluate} disabled={busy !== ''}>{busy === 'grade' ? 'جارٍ التصحيح...' : 'اقتراح درجة'}</Button>}
          {canAdjust && <Button size="sm" onClick={() => setAdjustOpen(!adjustOpen)}>مراجعة المعلم</Button>}
          {canApprove && <Button size="sm" variant="success" disabled={(Boolean(answer.NeedsGradingReview) && answer.AdjustedScore === null) || (answer.SuggestedScore === null && answer.AdjustedScore === null)} onClick={() => setApprovalOpen(!approvalOpen)}>اعتماد نهائي</Button>}
        </div>
      )}

      {adjustOpen && canAdjust && (
        <form className="inline-review-form" onSubmit={adjust}>
          <h4>مراجعة الدرجة بواسطة المعلم</h4>
          <div className="form-row">
            <Field label={`الدرجة (من ${answer.MaxMarks})`}><input required type="number" min="0" max={answer.MaxMarks} step="0.25" value={score} onChange={(e) => setScore(e.target.value)} /></Field>
            <Field label="مبرر التعديل"><input required minLength="3" value={justification} onChange={(e) => setJustification(e.target.value)} placeholder="سبب منح الدرجة..." /></Field>
          </div>
          <Field label="ملاحظات إضافية"><textarea rows="2" value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
          <div className="form-actions"><Button type="button" variant="secondary" onClick={() => setAdjustOpen(false)}>إلغاء</Button><Button type="submit" disabled={busy !== ''}>حفظ مراجعة المعلم</Button></div>
        </form>
      )}

      {approvalOpen && canApprove && (
        <form className="inline-review-form approval-form" onSubmit={approve}>
          <h4>اعتماد الدرجة النهائية بواسطة المسؤول</h4>
          <p>اترك الدرجة فارغة لاعتماد الدرجة المعدلة أو المقترحة وفق قواعد النظام.</p>
          <div className="form-row">
            <Field label="الدرجة المعتمدة (اختياري)"><input type="number" min="0" max={answer.MaxMarks} step="0.25" value={approvalScore} onChange={(e) => setApprovalScore(e.target.value)} placeholder="استخدم الدرجة المتاحة" /></Field>
            <Field label="ملاحظة الاعتماد"><input required minLength="3" value={approvalNote} onChange={(e) => setApprovalNote(e.target.value)} placeholder="ملاحظة الاعتماد..." /></Field>
          </div>
          <div className="form-actions"><Button type="button" variant="secondary" onClick={() => setApprovalOpen(false)}>إلغاء</Button><Button type="submit" variant="success" disabled={busy !== ''}>تأكيد الاعتماد النهائي</Button></div>
        </form>
      )}

      {regionOpen && (
        <RegionModal answer={answer} pages={pages} existing={regions} onClose={() => setRegionOpen(false)} onSaved={loadRegions} />
      )}
    </article>
  )
}

export default function SheetReview({ sheetId, user, onBack, notify }) {
  const [sheet, setSheet] = useState(null)
  const [pages, setPages] = useState([])
  const [answers, setAnswers] = useState([])
  const [questions, setQuestions] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [sheetData, pageData, answerData] = await Promise.all([
        api(`/academic/answer-sheets/${sheetId}`),
        api(`/academic/answer-sheets/${sheetId}/pages`),
        api(`/academic/answer-sheets/${sheetId}/answers`),
      ])
      setSheet(sheetData)
      setPages(pageData.items || [])
      setAnswers(answerData || [])
      const uniqueIds = [...new Set((answerData || []).map((item) => item.QuestionId))]
      const questionData = await Promise.all(uniqueIds.map((id) => api(`/academic/questions/${id}`)))
      setQuestions(Object.fromEntries(questionData.map((item) => [item.QuestionId, item])))
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }, [sheetId])

  useEffect(() => { refresh() }, [refresh])

  const approvedCount = useMemo(() => answers.filter((answer) => Boolean(answer.IsApproved)).length, [answers])

  if (loading && !sheet) return <Loading label="جارٍ تحميل ورقة الإجابة..." />

  return (
    <div className="page-stack">
      <div className="back-row"><Button variant="ghost" onClick={onBack}>→ العودة إلى الاختبارات</Button><span>مراجعة ورقة الإجابة</span></div>
      <div className="sheet-hero">
        <div><div className="eyebrow">ورقة إجابة · #{sheet?.AnswerSheetId}</div><h1>{sheet?.FullName || 'الطالب'} <small>{sheet?.AcademicId}</small></h1><p>{sheet?.ExamTitle} · اختبار #{sheet?.ExamId}</p></div>
        <div className="sheet-hero-meta"><Status value={sheet?.ProcessingStatus} /><strong>{approvedCount} / {answers.length} إجابة معتمدة</strong><Button variant="secondary" size="sm" onClick={refresh}>↻ تحديث</Button></div>
      </div>
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="stats-grid stats-grid-compact">
        <div className="mini-stat"><span>الصفحات</span><strong>{pages.length}</strong></div>
        <div className="mini-stat"><span>عدد الأسئلة</span><strong>{answers.length}</strong></div>
        <div className="mini-stat"><span>المعتمدة نهائياً</span><strong>{approvedCount}</strong></div>
        <div className="mini-stat"><span>المتبقية</span><strong>{Math.max(0, answers.length - approvedCount)}</strong></div>
      </div>

      <Card title="صفحات إجابة الطالب" subtitle="تُحمّل الصور من التخزين المحلي عبر نقطة API محمية.">
        {pages.length ? (
          <div className="page-thumb-grid">
            {pages.map((page) => <PageThumb key={page.PageId} page={page} />)}
          </div>
        ) : <Empty title="لم تُرفع صفحات لهذه الورقة" detail="ارفع صور الإجابة من مساحة الاختبار أولاً." />}
      </Card>

      <div className="section-heading"><div><h2>مراجعة الإجابات والتصحيح</h2><p>تحقق من نص OCR، اربط مناطق الإجابة، ثم أنشئ اقتراح الدرجة وراجعها.</p></div></div>
      {answers.length ? answers.map((answer) => (
        <AnswerCard key={answer.AnswerId} answer={answer} question={questions[answer.QuestionId]} pages={pages} user={user} notify={notify} refresh={refresh} />
      )) : <Card><Empty title="لا توجد سجلات إجابات" detail="أضف أسئلة للاختبار قبل إنشاء أوراق الإجابة." /></Card>}
    </div>
  )
}

function PageThumb({ page }) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    let objectUrl = ''
    apiBlob(`/uploads/pages/${page.PageId}/image?variant=original`)
      .then((blob) => { if (active) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl) } })
      .catch((err) => { if (active) setError(err.message) })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [page.PageId])
  return (
    <div className="page-thumb">
      {url ? <img src={url} alt={`صفحة ${page.PageNumber}`} /> : <div className="thumb-placeholder">{error ? 'تعذر العرض' : 'تحميل...'}</div>}
      <div><strong>الصفحة {page.PageNumber}</strong><Status value={page.ImageQualityStatus} /></div>
      <small>{page.ImageWidth} × {page.ImageHeight} px</small>
    </div>
  )
}
