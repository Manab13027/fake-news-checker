# Fake News Checker — Flask Edition (Improved)

- Flask + Bootstrap + Chart.js web dashboard
- Windows-friendly: **no lxml, no OpenCV**
- **Normalized scoring** over only the sections you actually provide (URL/text/image/video)
- **Auto-fetches page text** from URL to improve the Text score (BeautifulSoup + html5lib)
- Expanded **source heuristics**, resolves shorteners, HTTPS awareness
- Download JSON / Markdown reports

## Run
```powershell
cd fake-news-flask
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
set FLASK_APP=app.py
flask run
```
Open http://127.0.0.1:5000/
