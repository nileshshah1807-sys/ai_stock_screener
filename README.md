# AI Stock Screener

Daily NSE stock screener with technical scoring, fundamentals, Reverse DCF analysis, CSV output, dashboard generation, and email delivery.

## Local Run

```powershell
pip install -r requirements.txt
python app.py
```

## Local Scheduler

```powershell
python scheduler.py --now
python scheduler.py --time 09:00 --timezone Asia/Kolkata
```

## Railway Deployment

This repo includes `railway.json`, so Railway can run:

```bash
python scheduler.py
```

Set these Railway variables:

```text
EMAIL_ENABLED=True
EMAIL_SENDER=nilesh.shah1807@gmail.com
EMAIL_RECEIVER=nilesh.shah1807@gmail.com
EMAIL_PASSWORD=<gmail app password>
ATTACH_CSV=True
SCHEDULE_TIME=09:00
SCHEDULE_TIMEZONE=Asia/Kolkata
SCAN_ALL_NSE=False
CUSTOM_WATCHLIST=RELIANCE,TCS,HDFCBANK,INFY,ICICIBANK
```

Use `SCAN_ALL_NSE=True` only after confirming the scheduled job is stable, because full NSE scans can take longer and may hit Yahoo/NSE rate limits.

## Secrets

Do not commit `config_local.py`, `.env`, logs, or generated reports. They are ignored by `.gitignore`.
