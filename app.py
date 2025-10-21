from flask import Flask, render_template, session, redirect, url_for, request
from firebase_admin import firestore
import firebase_admin
from firebase_admin import credentials
from datetime import datetime
# --- ضع هذا أعلى الملف بعد التعريفات ---
from datetime import datetime, date

def _get_logged_doctor():
    """إرجاع معلومات الدكتور لعرضها في النافبار."""
    rid = session.get("radiologist_id")
    if not rid:
        return None
    doc = db.collection("Radiologists").document(rid).get()
    if not doc.exists:
        return None
    d = doc.to_dict() or {}
    return {
        "name": d.get("FullName", "Radiologist"),
        "email": d.get("Email", "N/A"),
        "ProfilePicture": d.get("ProfilePicture", None)
    }

def _parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None

# 🔹 Firebase Initialization
cred = credentials.Certificate("brainalyze-admin.json")
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app(cred)

app = Flask(__name__)
app.secret_key = "brainalyze-secret"

db = firestore.client()

# 🏠 الصفحة الرئيسية
@app.route("/")
def index():
    return render_template("index.html")

# 🔐 تسجيل دخول مؤقت (اختبار)
@app.route("/login")
def login():
    # Radiologist مؤقت للتجربة
    session["radiologist_id"] = "zK30CBUT9wXMiVwtLQc5vQtoWv62"
    return redirect(url_for("home"))

# 📅 دالة لتنسيق التاريخ
def _fmt_date(v):
    try:
        if hasattr(v, "strftime"):
            return v.strftime("%B %d, %Y — %I:%M %p")
        if hasattr(v, "isoformat"):
            return v.isoformat()
    except Exception:
        pass
    return str(v) if v else ""

# 🧠 صفحة الـ Home (تعرض آخر الفحوصات)
@app.route("/home")
def home():
    if "radiologist_id" not in session:
        return redirect(url_for("login"))

    radiologist_id = session["radiologist_id"]

    # 🩺 جلب بيانات الطبيب
    doc_ref = db.collection("Radiologists").document(radiologist_id)
    doc = doc_ref.get()
    if not doc.exists:
        return f"Radiologist {radiologist_id} not found in Firestore", 404

    doctor_data = doc.to_dict() or {}
    doctor = {
        "name": doctor_data.get("FullName", "Unknown"),
        "email": doctor_data.get("Email", "N/A"),
        "phone": doctor_data.get("ContactNumber", "N/A")
    }

    # 🧍‍♀️ جلب المرضى اللي أنشأهم الطبيب
    patients_query = db.collection("Patients").where(
        "CreatedBy", "==", db.document(f"Radiologists/{radiologist_id}")
    ).stream()

    patient_map = {}
    for p in patients_query:
        pdata = p.to_dict() or {}
        patient_map[f"/Patients/{p.id}"] = {
            "FullName": pdata.get("FullName", f"Patient ({p.id})"),
            "Age": pdata.get("Age", ""),
            "Gender": pdata.get("Gender", ""),
            "MedicalNotes": pdata.get("MedicalNotes", "")
        }

    # 🧠 جلب الفحوصات المرتبطة بمرضى هذا الطبيب
    cases = []
    for patient_ref in patient_map.keys():
        scans_query = db.collection("MRI_Scans").where(
            "PatientID", "==", db.document(patient_ref)
        ).stream()

        for s in scans_query:
            data = s.to_dict() or {}
            patient_data = patient_map.get(patient_ref, {})

            cases.append({
                "PatientName": patient_data.get("FullName", "Unknown"),
                "Age": patient_data.get("Age", ""),
                "Gender": patient_data.get("Gender", ""),
                "ClassificationResult": data.get("ClassificationResult", ""),
                "ConfidenceScore": data.get("ConfidenceScore", ""),
                "QuickDescription": data.get("QuickDescription", ""),
                "UploadDate": _fmt_date(data.get("UploadDate")),
                "MRIFilePath": data.get("MRIFilePath", "")
            })

    return render_template("home.html", doctor=doctor, cases=cases)


# 📊 صفحة Dashboard (الإحصائيات والتحليلات)
@app.route("/dashboard")
def dashboard():
    if "radiologist_id" not in session:
        return redirect(url_for("login"))

    radiologist_id = session["radiologist_id"]
    doc_ref = db.collection("Radiologists").document(radiologist_id)
    doc = doc_ref.get()
    doctor_data = doc.to_dict() if doc.exists else {}

    doctor = {
        "name": doctor_data.get("FullName", "Unknown"),
        "email": doctor_data.get("Email", "N/A"),
    }

    patients = list(db.collection("Patients").stream())
    scans = list(db.collection("MRI_Scans").stream())
    reports = list(db.collection("Reports").stream())

    total_patients = len(patients)
    total_scans = len(scans)
    total_reports = len(reports)

    now = datetime.now()
    new_scans_count = sum(
        1 for s in scans
        if "UploadDate" in s.to_dict()
        and isinstance(s.to_dict()["UploadDate"], datetime)
        and s.to_dict()["UploadDate"].month == now.month
    )

    conf_scores = []
    for s in scans:
        val = s.to_dict().get("ConfidenceScore")
        try:
            val_f = float(val)
            if 0 <= val_f <= 1:
                conf_scores.append(val_f)
            elif val_f > 1:
                conf_scores.append(val_f / 100)
        except Exception:
            pass
    ai_accuracy = (sum(conf_scores) / len(conf_scores) * 100) if conf_scores else 95

    tumor_counts = {}
    for s in scans:
        tumor = s.to_dict().get("ClassificationResult", "Unknown")
        tumor_counts[tumor] = tumor_counts.get(tumor, 0) + 1

    gender_counts = {"Male": 0, "Female": 0}
    for p in patients:
        g = p.to_dict().get("Gender", "Unknown")
        if g in gender_counts:
            gender_counts[g] += 1

    monthly_uploads = [0] * 12
    for s in scans:
        data = s.to_dict()
        if "UploadDate" in data and isinstance(data["UploadDate"], datetime):
            month_index = data["UploadDate"].month - 1
            monthly_uploads[month_index] += 1

    return render_template(
        "dashboard.html",
        doctor=doctor,
        total_patients=total_patients,
        new_scans=new_scans_count,
        ai_accuracy=f"{ai_accuracy:.0f}%",
        total_reports=total_reports,
        tumor_counts=tumor_counts,
        gender_counts=gender_counts,
        monthly_uploads=monthly_uploads
    )


# 👩‍⚕️ صفحة البروفايل (عرض وتعديل بيانات الطبيب)
@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "radiologist_id" not in session:
        return redirect(url_for("login"))

    radiologist_id = session["radiologist_id"]
    doc_ref = db.collection("Radiologists").document(radiologist_id)
    doc = doc_ref.get()

    if not doc.exists:
        return "Profile not found", 404

    data = doc.to_dict() or {}
    doctor = {
        "name": data.get("FullName", "Unknown"),
        "email": data.get("Email", "N/A"),
        "phone": data.get("ContactNumber", "N/A"),
        "specialty": data.get("Specialty", "N/A")
    }

    # ✅ تحديث البيانات في حالة الضغط على Save
    if request.method == "POST":
        new_name = request.form.get("name")
        new_email = request.form.get("email")
        new_phone = request.form.get("phone")
        new_specialty = request.form.get("specialty")

        doc_ref.update({
            "FullName": new_name,
            "Email": new_email,
            "ContactNumber": new_phone,
            "Specialty": new_specialty
        })

        doctor.update({
            "name": new_name,
            "email": new_email,
            "phone": new_phone,
            "specialty": new_specialty
        })

    return render_template("profile.html", doctor=doctor)
# --- راوت صفحة المرضى ---
# 👩‍⚕️ صفحة المرضى
# 🧠 صفحة المرضى
@app.route("/patients")
def patients():
    if "radiologist_id" not in session:
        return redirect(url_for("login"))

    rid = session["radiologist_id"]

    # جلب بيانات الدكتور
    doc_ref = db.collection("Radiologists").document(rid)
    doctor_data = doc_ref.get().to_dict() if doc_ref.get().exists else {}
    doctor = {
        "name": doctor_data.get("FullName", "Radiologist"),
        "email": doctor_data.get("Email", ""),
        "ProfilePicture": doctor_data.get("ProfilePicture", "")
    }

    # جلب المرضى التابعين للطبيب
    patients_query = db.collection("Patients").where("CreatedBy", "==", f"/Radiologists/{rid}").stream()
    patients = []
    for p in patients_query:
        pdata = p.to_dict()
        patients.append({
            "id": p.id,
            "FullName": pdata.get("FullName", ""),
            "Age": pdata.get("Age", ""),
            "Gender": pdata.get("Gender", ""),
            "LastMRI": pdata.get("LastMRI", "—")
        })

    return render_template("patients.html", doctor=doctor, patients=patients)
from flask import jsonify
from datetime import datetime

@app.route("/upload_mri", methods=["POST"])
def upload_mri():
    data = request.json
    patient_id = data.get("patient_id")
    description = data.get("description", "")

    if not patient_id:
        return jsonify({"status": "error", "message": "Missing patient ID"})

    if "radiologist_id" not in session:
        return jsonify({"status": "error", "message": "Not logged in"})

    rid = session["radiologist_id"]
    now = datetime.now().isoformat()

    # إنشاء سجل MRI جديد
    new_doc = db.collection("MRI_Scans").document()
    new_doc.set({
        "PatientID": f"/Patients/{patient_id}",
        "UploadedBy": f"/Radiologists/{rid}",
        "CreatedAt": now,
        "Description": description,
        "Analyzed": False
    })

    # تحديث آخر تاريخ MRI في سجل المريض
    db.collection("Patients").document(patient_id).update({"LastMRI": now[:10]})

    return jsonify({"status": "success", "message": "MRI uploaded successfully!"})


@app.route("/add_patient", methods=["POST"])
def add_patient():
    data = request.json
    name = data.get("FullName")
    age = data.get("Age")
    gender = data.get("Gender")
    notes = data.get("MedicalNotes", "")

    if not all([name, age, gender]):
        return jsonify({"status": "error", "message": "Missing required fields."})

    if "radiologist_id" not in session:
        return jsonify({"status": "error", "message": "Not logged in"})

    rid = session["radiologist_id"]
    now = datetime.now().isoformat()

    new_doc = db.collection("Patients").document()
    new_doc.set({
        "FullName": name,
        "Age": age,
        "Gender": gender,
        "MedicalNotes": notes,
        "CreatedBy": f"/Radiologists/{rid}",
        "CreatedAt": now,
        "LastMRI": ""
    })

    return jsonify({"status": "success", "message": "Patient added successfully!"})


# 🚀 تشغيل السيرفر
if __name__ == "__main__":
    app.run(debug=True)

