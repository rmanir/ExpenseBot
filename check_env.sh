echo "===== SYSTEM ====="
sw_vers || true
echo "arch: $(uname -m)"
sysctl -n machdep.cpu.brand_string || true

echo
echo "===== DEV TOOLS ====="
xcode-select -p 2>/dev/null || echo "Xcode CLT: not installed"
brew --version 2>/dev/null | head -n1 || echo "Homebrew: not found"
clang --version 2>/dev/null | head -n1 || true
gcc --version 2>/dev/null | head -n1 || true
pkg-config --version 2>/dev/null || echo "pkg-config: not found"

echo
echo "===== TESSERACT ====="
tesseract --version 2>/dev/null | head -n2 || echo "tesseract: not found"
pkg-config --modversion tesseract 2>/dev/null || echo "tesseract.pc: not found"

echo
echo "===== PYTHON (SYSTEM) ====="
which -a python3 || true
python3 --version 2>/dev/null || true

echo
echo "===== PYTHON (VENV) ====="
echo "VIRTUAL_ENV=$VIRTUAL_ENV"
which python; python --version
which pip; pip --version

echo
echo "===== KEY PYTHON PACKAGES ====="
python - <<'PY'
mods = [
  "telegram", "apscheduler", "tzlocal", "pytz", "urllib3", "six",
  "cv2", "pytesseract", "PIL", "gspread", "google", "dateutil"
]
for m in mods:
    try:
        mod = __import__(m)
        ver = getattr(mod, "__version__", None)
        if m == "cv2":
            import cv2; ver = cv2.__version__
        if m == "PIL":
            import PIL; ver = PIL.__version__
        print(f"{m:12} -> {ver or 'version attr missing'}  (OK)")
    except Exception as e:
        print(f"{m:12} -> NOT INSTALLED  ({e.__class__.__name__}: {e})")
PY

echo
echo "===== PTB/APScheduler wiring sanity ====="
python - <<'PY'
try:
    import telegram, apscheduler, tzlocal, pytz, platform
    print("python-telegram-bot:", getattr(telegram, "__version__", "unknown"))
    print("APScheduler:", getattr(apscheduler, "__version__", "unknown"))
    print("tzlocal:", getattr(tzlocal, "__version__", "unknown"))
    try:
        from tzlocal import get_localzone
        tz = get_localzone()
        print("tzlocal.get_localzone() ->", tz, "| type:", type(tz))
        import apscheduler.util as util
        try:
            util.astimezone(tz)
            print("apscheduler.util.astimezone(get_localzone()) ✓")
        except Exception as e:
            print("apscheduler.util.astimezone(get_localzone()) ERROR ->", e)
    except Exception as e:
        print("tzlocal probe error:", e)
    print("Platform:", platform.platform())
except Exception as e:
    print("Import probe failed:", e)
PY

echo
echo "===== PROJECT FILES ====="
ls -l | sed -n '1,200p'
[ -f service_account.json ] && echo "service_account.json: present" || echo "service_account.json: NOT FOUND"

echo
echo "===== .env (keys present? values hidden) ====="
if [ -f .env ]; then
  grep -E '^(TELEGRAM_BOT_TOKEN|GOOGLE_SHEETS_SPREADSHEET_ID)=' .env | sed 's/=.*/=<set>/'
else
  echo ".env: NOT FOUND"
fi
