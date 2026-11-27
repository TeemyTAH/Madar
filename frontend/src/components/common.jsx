import { useEffect } from 'react'

export function Button({ children, variant = 'primary', size = 'md', className = '', block = false, ...props }) {
  return <button className={`btn btn-${variant} btn-${size} ${block ? 'btn-block' : ''} ${className}`} {...props}>{children}</button>
}

export function Field({ label, hint, children, className = '' }) {
  return (
    <label className={`field ${className}`}>
      {label && <span className="field-label">{label}</span>}
      {children}
      {hint && <small className="field-hint">{hint}</small>}
    </label>
  )
}

export function PageTitle({ eyebrow, title, subtitle, actions }) {
  return (
    <div className="page-title">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="page-title-actions">{actions}</div>}
    </div>
  )
}

export function Card({ title, subtitle, action, children, className = '' }) {
  return (
    <section className={`card ${className}`}>
      {(title || subtitle || action) && (
        <div className="card-heading">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

export function Stat({ label, value, note, icon = '◈', tone = 'blue' }) {
  return (
    <div className={`stat-card stat-${tone}`}>
      <div className="stat-top">
        <span>{label}</span>
        <span className="stat-icon" aria-hidden="true">{icon}</span>
      </div>
      <strong>{value ?? '—'}</strong>
      {note && <small>{note}</small>}
    </div>
  )
}

export function Status({ value }) {
  const raw = String(value || '—')
  const tone = raw.includes('FINAL') || raw === 'FINALLY_APPROVED' || raw === 'SUCCEEDED' || raw === 'VALID'
    ? 'success'
    : raw.includes('PENDING') || raw.includes('REVIEW') || raw === 'REQUIRES_REVIEW'
      ? 'warning'
      : raw === 'FAILED' || raw === 'INVALID'
        ? 'danger'
        : 'neutral'
  const labels = {
    NOT_PROCESSED: 'لم تبدأ المعالجة',
    PROCESSED: 'تمت المعالجة',
    PENDING_REVIEW: 'بانتظار المراجعة',
    REVIEWED: 'تمت المراجعة',
    FINALLY_APPROVED: 'معتمد نهائياً',
    SUCCEEDED: 'ناجح',
    REQUIRES_REVIEW: 'يتطلب مراجعة',
    FAILED: 'فشل',
    VALID: 'صورة صالحة',
    LOW_QUALITY: 'جودة منخفضة',
    INVALID: 'غير صالحة',
    NO_ANSWER_SHEET: 'لا توجد ورقة',
    FINAL: 'نتيجة نهائية',
    FINAL_APPROVED: 'اعتماد نهائي',
    TEACHER_REVIEWED: 'راجعها المعلم',
  }
  return <span className={`status status-${tone}`}>{labels[raw] || raw.replaceAll('_', ' ')}</span>
}

export function Empty({ title = 'لا توجد بيانات بعد', detail = 'ستظهر البيانات هنا عند إضافتها إلى النظام.' }) {
  return <div className="empty-state"><span>◇</span><strong>{title}</strong><p>{detail}</p></div>
}

export function Loading({ label = 'جارٍ تحميل البيانات...' }) {
  return <div className="loading-state"><span className="spinner" />{label}</div>
}

export function Modal({ title, subtitle, onClose, children, wide = false }) {
  useEffect(() => {
    const onKey = (event) => event.key === 'Escape' && onClose?.()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose?.()}>
      <section className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal-header">
          <div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
          <button className="icon-button" onClick={onClose} aria-label="إغلاق">×</button>
        </header>
        <div className="modal-content">{children}</div>
      </section>
    </div>
  )
}

export function Alert({ tone = 'info', children, onClose }) {
  return (
    <div className={`alert alert-${tone}`} role="status">
      <span>{children}</span>
      {onClose && <button className="alert-close" onClick={onClose} aria-label="إغلاق">×</button>}
    </div>
  )
}

