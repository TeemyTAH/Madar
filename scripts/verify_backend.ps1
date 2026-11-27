$ErrorActionPreference = 'Stop'

Write-Host "`n========== MADAR BACKEND VERIFICATION ==========" -ForegroundColor Cyan

Write-Host "`n[1/3] Python compilation" -ForegroundColor Yellow
python -m compileall -q backend ai_engine
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed." }

Write-Host "`n[2/3] Automated tests" -ForegroundColor Yellow
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Automated test suite failed." }

Write-Host "`n[3/3] SQLite integrity" -ForegroundColor Yellow
@'
import sqlite3
from pathlib import Path

path = Path("storage/SmartArabicGraderDB.sqlite3")
if not path.is_file():
    raise SystemExit(f"Database not found: {path}")
conn = sqlite3.connect(path)
try:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
finally:
    conn.close()
print("Integrity:", integrity)
print("Foreign-key violations:", len(foreign_keys))
if integrity != "ok" or foreign_keys:
    raise SystemExit("SQLite integrity verification failed.")
'@ | python -
if ($LASTEXITCODE -ne 0) { throw "SQLite integrity verification failed." }

Write-Host "`nMADAR BACKEND VERIFICATION: ALL CHECKS PASSED" -ForegroundColor Green
