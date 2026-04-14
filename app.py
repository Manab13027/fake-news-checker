from flask import Flask, render_template, request, send_file, redirect, url_for
import os, io, json, time
from werkzeug.utils import secure_filename
from fakecheck.pipeline import FakeCheckPipeline

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

LAST_RESULT = None

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    global LAST_RESULT
    url = request.form.get("url") or None
    text = request.form.get("text") or None

    image_path = None
    video_path = None

    if "image" in request.files and request.files["image"].filename:
        img = request.files["image"]
        fname = "img_" + str(int(time.time())) + "_" + secure_filename(img.filename)
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
        img.save(image_path)

    if "video" in request.files and request.files["video"].filename:
        vid = request.files["video"]
        fname = "vid_" + str(int(time.time())) + "_" + secure_filename(vid.filename)
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
        vid.save(video_path)

    pipe = FakeCheckPipeline()
    result = pipe.run(text=text, url=url, image_path=image_path, video_path=video_path)
    LAST_RESULT = result
    return render_template("report.html", result=result)

@app.route("/download/json")
def download_json():
    if not LAST_RESULT:
        return redirect(url_for("index"))
    data = json.dumps(LAST_RESULT, ensure_ascii=False, indent=2).encode("utf-8")
    return send_file(io.BytesIO(data), mimetype="application/json", as_attachment=True, download_name="report.json")

@app.route("/download/md")
def download_md():
    if not LAST_RESULT:
        return redirect(url_for("index"))
    data = LAST_RESULT["markdown_report"].encode("utf-8")
    return send_file(io.BytesIO(data), mimetype="text/markdown", as_attachment=True, download_name="report.md")

if __name__ == "__main__":
    app.run(debug=True)

