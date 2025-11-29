from flask import Flask, render_template, session, redirect, url_for, request, jsonify, flash
from firebase_admin import firestore, auth, credentials
import firebase_admin
from datetime import datetime, date
import os

app = Flask(__name__)
app.secret_key = "brainalyze-secret"

cred = credentials.Certificate("brainalyze-admin.json")
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ==========================================================
# 🔹 إعداد المجلد الخاص برفع الصور
# ==========================================================
UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# ==========================================================
# 🔹 دوال مساعدة
# ==========================================================
def _get_logged_doctor():
    rid = session.get("radiologist_id")
    if not rid:
        return None

    doc = db.collection("Radiologists").document(rid).get()
    if not doc.exists:
        return None

    d = doc.to_dict() or {}
    return {
        "id": rid,
        "name": d.get("FullName", "Radiologist"),
        "email": d.get("Email", "N/A"),
        "ProfilePicture": d.get("ProfilePicture", None)
    }



def compute_initials(full_name: str) -> str:
    """Return first+last initials (or first only if single-word name)."""
    name = (full_name or "").strip()
    if not name:
        return ""
    parts = name.split()
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[1][0]).upper()

# ==========================================================
# 🔹 الصفحات الأساسية
# ==========================================================
@app.route("/")
def index():
    return render_template("index.html")


# ==========================================================
# 🔐 صفحات التوثيق
# ==========================================================
@app.route("/register_login")
def register_login():
    return render_template("register_login.html")


@app.route("/verify")
def verify():
    mode = request.args.get("mode")
    oob_code = request.args.get("oobCode")

    if mode == "verifyEmail":
        return render_template("verify.html")  # صفحة توثيق الإيميل الحالية
    
    elif mode == "resetPassword":
        return render_template("reset_password.html", oob_code=oob_code)  # صفحة تعديل كلمة السر
    
    else:
        return render_template("verify.html") 

@app.route("/forget")
def forget():
    return render_template("forget.html")


@app.route("/check_email")
def check_email():
    return render_template("check_email.html")


@app.route("/login_from_firebase")
def login_from_firebase():
    uid = request.args.get("uid")
    if not uid:
        return "Missing UID", 400
    try:
        user_record = auth.get_user(uid)
    except Exception as e:
        return f"Invalid Firebase user: {str(e)}", 403

    session["radiologist_id"] = uid
    return redirect(url_for("home"))


# ==========================================================
# 🧠 صفحة الـ Home
# ==========================================================
@app.route("/home")
def home():
    doctor = _get_logged_doctor()
    if not doctor:
        return redirect(url_for("register_login"))

    patients_query = db.collection("Patients").where(
        "CreatedBy", "==", f"/Radiologists/{doctor['id']}"
    ).stream()

    cases = []
    today = datetime.now().date()

    today_patients = 0
    today_completed = 0
    today_pending = 0

    for p in patients_query:
        pdata = p.to_dict()
        patient_id = p.id

        scans_query = db.collection("MRI_Scans").where(
    "PatientID", "==", f"/Patients/{patient_id}"
).stream()


        for s in scans_query:
            sdata = s.to_dict()
            upload_date = sdata.get("UploadDate")

            cases.append({
                "id": s.id,
                "PatientName": pdata.get("FullName", ""),
                "UploadDate": upload_date.strftime("%Y-%m-%d %H:%M") if hasattr(upload_date, "strftime") else "",
            })

            if isinstance(upload_date, datetime) and upload_date.date() == today:
                today_completed += 1

        created_at = pdata.get("CreatedAt")

        if created_at:
            try:
                if isinstance(created_at, str):
                    created_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").date()

                elif isinstance(created_at, datetime):
                    created_dt = created_at.date()

                else:
                    created_dt = None

                if created_dt == today:
                    today_patients += 1

            except Exception as e:
                print(" Error parsing CreatedAt:", e)
                pass

    cases = sorted(cases, key=lambda x: x["UploadDate"], reverse=True)

    return render_template(
        "home.html",
        doctor=doctor,
        cases=cases,
        total_patients=today_patients,
        completed_scans=today_completed,
        pending_reports=today_pending,
    
    )


# ==========================================================
# 📊 صفحة Dashboard
# ==========================================================
@app.route("/dashboard")
def dashboard():
    doctor = _get_logged_doctor()
    if not doctor:
        return redirect(url_for("register_login"))

    patients = list(
        db.collection("Patients")
        .where("CreatedBy", "==", f"/Radiologists/{doctor['id']}")
        .stream()
    )
    scans = list(db.collection("MRI_Scans").stream())
    reports = list(db.collection("Reports").stream())

    total_patients = len(patients)
    total_scans = len(scans)
    total_reports = len(reports)

    now = datetime.now()
    new_scans = sum(
        1 for s in scans
        if isinstance(s.to_dict().get("UploadDate"), datetime)
        and s.to_dict()["UploadDate"].month == now.month
    )

    conf_scores = []
    for s in scans:
        val = s.to_dict().get("ConfidenceScore")
        try:
            val_f = float(val)
            conf_scores.append(val_f if val_f <= 1 else val_f / 100)
        except:
            pass

    ai_accuracy = f"{(sum(conf_scores) / len(conf_scores) * 100):.0f}%" if conf_scores else "95%"

    tumor_counts, gender_counts = {}, {"Male": 0, "Female": 0}
    for s in scans:
        tumor = s.to_dict().get("ClassificationResult", "Unknown")
        tumor_counts[tumor] = tumor_counts.get(tumor, 0) + 1
    for p in patients:
        g = p.to_dict().get("Gender", "")
        if g in gender_counts:
            gender_counts[g] += 1

    monthly_uploads = [0] * 12
    for s in scans:
        d = s.to_dict().get("UploadDate")
        if isinstance(d, datetime):
            monthly_uploads[d.month - 1] += 1

    return render_template(
        "dashboard.html",
        doctor=doctor,
        total_patients=total_patients,
        total_reports=total_reports,
        new_scans=new_scans,
        ai_accuracy=ai_accuracy,
        tumor_counts=tumor_counts,
        gender_counts=gender_counts,
        monthly_uploads=monthly_uploads
    )


# ==========================================================
# 👨‍⚕️ صفحة البروفايل
# ==========================================================
@app.route("/profile", methods=["GET", "POST"])
def profile():
    doctor = _get_logged_doctor()
    if not doctor:
        return redirect(url_for("register_login"))

    doc_ref = db.collection("Radiologists").document(doctor["id"])
    snap = doc_ref.get()
    data = snap.to_dict() or {}

    # ---------------- POST: Update Profile ----------------
    if request.method == "POST":
        updated = {
            "FullName": request.form.get("name", "").strip(),
            "Email": request.form.get("email", "").strip(),
            "ContactNumber": request.form.get("phone", "").strip(),
            "Specialty": request.form.get("specialty", "").strip(),
        }

        # --- Upload profile picture locally ---
        file = request.files.get("profile_pic")
        if file and file.filename.strip():
            filename = f"{doctor['id']}.jpg"
            path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(path)
            updated["ProfilePicture"] = f"/static/uploads/{filename}"
        else:
            updated["ProfilePicture"] = data.get("ProfilePicture", "/static/images/user.png")

        # --- Update Firestore ---
        doc_ref.update(updated)
        data.update(updated)

        # --- Update phone number in Firebase Auth ---
        try:
            phone = updated["ContactNumber"]
            if phone and phone.startswith("+"):
                auth.update_user(doctor["id"], phone_number=phone)
        except Exception as e:
            print("⚠ Auth phone update Failed:", e)

        flash("Profile updated successfully!", "success")
        return redirect(url_for("profile"))

    # ---------------- GET: Load Profile ----------------
    doctor_ctx = {
        "name": data.get("FullName", ""),
        "email": data.get("Email", ""),
        "phone": data.get("ContactNumber", ""),
        "specialty": data.get("Specialty", ""),
        "ProfilePicture": data.get("ProfilePicture", "/static/images/user.png"),
    }

    return render_template("profile.html", doctor=doctor_ctx)
# ==========================================================
# 🔄 تحديث البروفايل عبر AJAX (بدون ريلود)
# ==========================================================
@app.route("/profile/update_ajax", methods=["POST"])
def update_profile_ajax():
    doctor = _get_logged_doctor()
    if not doctor:
        return jsonify({"status": "error", "message": "Not logged in"}), 403

    doc_ref = db.collection("Radiologists").document(doctor["id"])
    old_data = doc_ref.get().to_dict() or {}

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    specialty = request.form.get("specialty", "").strip()

    updated = {
        "FullName": name,
        "Email": email,
        "ContactNumber": phone,
        "Specialty": specialty
    }

    # ---- صورة البروفايل ----
    file = request.files.get("profile_pic")
    if file and file.filename.strip():
        filename = f"{doctor['id']}.jpg"
        upload_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(upload_path)
        updated["ProfilePicture"] = f"/static/uploads/{filename}"
    else:
        updated["ProfilePicture"] = old_data.get("ProfilePicture", "/static/images/user.png")

    doc_ref.update(updated)

    return jsonify({
        "status": "success",
        "message": "Profile updated successfully!",
        "updated_data": updated
    })

# ==========================================================
# 👩‍⚕️ المرضى
# ==========================================================
@app.route("/patients", methods=["GET", "POST"])
def patients():
    doctor = _get_logged_doctor()
    if not doctor:
        return redirect(url_for("register_login"))

    if request.method == "POST":
        full_name = request.form.get("FullName", "").strip()
        age = request.form.get("Age", "").strip()
        gender = request.form.get("Gender", "").strip()
        tumor_type = request.form.get("TumorType", "").strip()
        last_mri_date = request.form.get("LastMRIDate", "").strip()

        medical_notes = request.form.get("MedicalNotes", "").strip()
        contact_number = request.form.get("ContactNumber", "").strip()
        if contact_number and not contact_number.startswith("+966"):
            contact_number = "+966" + contact_number

        if full_name and age and gender:
            new_patient = {
                "FullName": full_name,
                "ContactNumber": contact_number,
                "Age": int(age) if age.isdigit() else age,
                "Gender": gender,
                "TumorType": tumor_type,
                "MedicalNotes": medical_notes, 
                "CreatedBy": f"/Radiologists/{doctor['id']}",
                "CreatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            db.collection("Patients").add(new_patient)

            flash("Patient added successfully.", "success")
            return redirect(url_for("patients"))

    q = request.args.get("q", "").strip().lower()
    tumor = request.args.get("tumor", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()

    patients_ref = db.collection("Patients").where("CreatedBy", "==", f"/Radiologists/{doctor['id']}")
    patients_query = patients_ref.stream()

    patients = []
    tumor_types = set()

    for p in patients_query:
        pdata = p.to_dict()
        pdata["id"] = p.id
        pdata["FullName"] = pdata.get("FullName", "")
        pdata["Age"] = pdata.get("Age", "")
        pdata["Gender"] = pdata.get("Gender", "")
        pdata["TumorType"] = pdata.get("TumorType", "")
        pdata["LastMRIDate"] = pdata.get("LastMRIDate", "")
        pdata["Initials"] = compute_initials(pdata["FullName"])
        tumor_types.add(pdata["TumorType"])

        if q and (q not in pdata["FullName"].lower() and q not in p.id.lower()):
            continue

        patients.append(pdata)

    return render_template(
        "patients.html",
        doctor=doctor,
        patients=patients,
        tumor_types=sorted(list(filter(None, tumor_types))),
        q=q,
        tumor=tumor,
        date_from=date_from,
        date_to=date_to
    )


# ==========================================================
# 🧾 APIs
# ==========================================================
@app.route("/add_patient", methods=["POST"])
def add_patient():
    if "radiologist_id" not in session:
        return jsonify({"status": "error", "message": "Not logged in"})

    data = request.json
    name = data.get("FullName")
    age = data.get("Age")
    gender = data.get("Gender")
    notes = data.get("MedicalNotes", "")

    if not all([name, age, gender]):
        return jsonify({"status": "error", "message": "Missing fields"})

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
    return jsonify({"status": "success", "message": "Patient added successfully"})



# ==========================================================
# 🧑‍🤝‍🧑 Patient Profile (view/update + list scans)
# ==========================================================

import os
@app.route("/patients/<patient_id>/profile", methods=["GET", "POST"], endpoint="patient_profile")
def patient_profile(patient_id):
    doctor = _get_logged_doctor()
    if not doctor:
        return redirect(url_for("register_login"))

    p_ref = db.collection("Patients").document(patient_id)
    snap = p_ref.get()
    if not snap.exists:
        return "Patient not found", 404

    p = snap.to_dict() or {}
    if p.get("CreatedBy") != f"/Radiologists/{doctor['id']}":
        return "Unauthorized", 403

    if request.method == "POST":
        full_name = request.form.get("name", "").strip()
        age_str = request.form.get("age", "").strip()
        gender = request.form.get("gender", "").strip()
        phone = request.form.get("phone", "").strip()
        notes = request.form.get("notes", "").strip()

        updated = {}

        if full_name:
            updated["FullName"] = full_name
        if age_str:
            updated["Age"] = int(age_str) if age_str.isdigit() else age_str
        if gender:
            updated["Gender"] = gender
        if phone:
            if not phone.startswith("+966"):
                phone = "+966" + phone
            updated["ContactNumber"] = phone
        updated["MedicalNotes"] = notes

       
        file = request.files.get("profile_pic")
        if file and file.filename.strip():
            ext = os.path.splitext(file.filename)[1] or ".jpg"
            folder = os.path.join(app.config["UPLOAD_FOLDER"], "patients")
            os.makedirs(folder, exist_ok=True)
            filename = f"{patient_id}{ext}"
            path = os.path.join(folder, filename)
            file.save(path)
            updated["ProfilePicture"] = f"/static/uploads/patients/{filename}"
        else:
            updated["ProfilePicture"] = p.get("ProfilePicture", "/static/images/user.png")

        if updated:
            p_ref.update(updated)

        return redirect(url_for("patient_profile", patient_id=patient_id))

    # ============================
    # GET: Patient Data
    # ============================
    patient_ctx = {
        "patient_id": patient_id,
        "name": p.get("FullName", ""),
        "age": p.get("Age", ""),
        "gender": p.get("Gender", ""),
        "phone": p.get("ContactNumber", ""),
        "ProfilePicture": p.get("ProfilePicture", "/static/images/user.png"),
        "MedicalNotes": p.get("MedicalNotes", ""),
        "LastScanDate": p.get("LastMRIDate", ""),
    }

    # ============================
    # GET CASES (Each Case + Last Update)
    # ============================
    cases_query = (
        db.collection("Cases")
        .where("PatientID", "==", f"/Patients/{patient_id}")
        .order_by("CreatedAt", direction=firestore.Query.ASCENDING)
        .stream()
    )

    cases = []
    for c in cases_query:
        cd = c.to_dict() or {}

        # scans for this case
        scans_for_case = db.collection("MRI_Scans").where(
            "CaseID", "==", f"/Cases/{c.id}"
        ).stream()

        scan_dates = []
        for sc in scans_for_case:
            dt = sc.to_dict().get("UploadDate")
            if isinstance(dt, datetime):
                scan_dates.append(dt)

        # determine last update
        if scan_dates:
            last_update_clean = max(scan_dates).strftime("%Y-%m-%d %H:%M")
        else:
            raw = cd.get("LastUpdate")
            if isinstance(raw, datetime):
                last_update_clean = raw.strftime("%Y-%m-%d %H:%M")
            else:
                last_update_clean = "—"

        cases.append({
            "id": c.id,
            "diagnosis": cd.get("Diagnosis", "—"),
            "treatment_plan": cd.get("TreatmentPlan", "—"),
            "status": cd.get("Status", "—"),
            "start_date": cd.get("StartDate", "—"),
            "end_date": cd.get("EndDate", None),
            "last_update": last_update_clean
        })

    # sort + add display_id
    cases_sorted = sorted(cases, key=lambda x: x["start_date"] if x["start_date"] != "—" else "")
    for idx, c in enumerate(cases_sorted, start=1):
        c["display_id"] = idx

    # ============================
    # GET SCANS (All scans for this patient)
    # ============================
    scans_query = db.collection("MRI_Scans").where(
        "PatientID", "==", f"/Patients/{patient_id}"
    ).order_by("UploadDate", direction=firestore.Query.ASCENDING).stream()

    scans = []
    for s in scans_query:
        sd = s.to_dict() or {}
        dt = sd.get("UploadDate")
        dt_clean = dt.strftime("%Y-%m-%d %H:%M") if isinstance(dt, datetime) else "—"

        scans.append({
            "id": s.id,
            "path": sd.get("MRIFilePath", ""),
            "date": dt_clean,
            "case_id": sd.get("CaseID", "")
        })

    has_scans = len(scans) > 0

    # ============================
    # FINAL RETURN – كل شيء يرجع هنا
    # ============================
    return render_template(
        "patient_profile.html",
        doctor=doctor,
        patient=patient_ctx,
        cases=cases_sorted,
        scans=scans,
        has_scans=has_scans,
        current_date_iso=date.today().isoformat()
    )


@app.route("/patients/<patient_id>/update", methods=["POST"])
def update_patient(patient_id):
    return redirect(url_for("patient_profile", patient_id=patient_id))

@app.route("/patients/<patient_id>/create_case", methods=["POST"])
def create_case(patient_id):
    doctor = _get_logged_doctor()
    if not doctor:
        return redirect(url_for("register_login"))

    # 1) Fetch patient
    patient_ref = db.collection("Patients").document(patient_id)
    snap = patient_ref.get()
    if not snap.exists:
        return "Patient not found", 404

    # 2) Form data
    treatment_plan = request.form.get("treatment_plan", "").strip()

    # 3) MRI file (required)
    first_scan = request.files.get("mri_file")
    if not first_scan:
        return "Missing MRI scan", 400

    # 4) Create case
    now = datetime.now()
    case_ref = db.collection("Cases").document()
    case_id = case_ref.id

    case_ref.set({
        "PatientID": f"/Patients/{patient_id}",
        "Diagnosis": "",
        "TreatmentPlan": treatment_plan,
        "Status": "Active",
        "StartDate": now.strftime("%Y-%m-%d"),
        "EndDate": None,
        "Notes": "",
        "CreatedAt": now,
        "LastUpdate": now,
        "FirstScanID": None
    })

    # 5) Save first scan file
    filename = f"{case_id}_{first_scan.filename}"
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    first_scan.save(save_path)

    rel_path = "/" + save_path.replace("\\", "/")

    # 6) Redirect to scans page WITH paths
    return redirect(url_for(
        "scans",
        patient_id=patient_id,
        case_id=case_id,
        first_image=rel_path
    ))
@app.route("/patients/<patient_id>/cases/<case_id>")
def view_case(patient_id, case_id):
    doctor = _get_logged_doctor()
    if not doctor:
        return redirect(url_for("register_login"))

    # ===== Fetch Case =====
    case_doc = db.collection("Cases").document(case_id).get()
    if not case_doc.exists:
        return "Case not found", 404

    case = case_doc.to_dict() or {}

    # ===== إعادة ترقيم الحالات Case #1, #2 =========
    all_cases = list(
        db.collection("Cases")
        .where("PatientID", "==", f"/Patients/{patient_id}")
        .stream()
    )

    sorted_cases = sorted(
        all_cases,
        key=lambda x: (x.to_dict().get("StartDate") or "")
    )

    display_number = 1
    for idx, cc in enumerate(sorted_cases, start=1):
        if cc.id == case_id:
            display_number = idx
            break

    case["DisplayID"] = display_number

    # ===== Format LastUpdate =====
  

    # ===== Fetch Scans for this Case =====
    scans = list(
        db.collection("MRI_Scans")
        .where("CaseID", "==", f"/Cases/{case_id}")
        .stream()
    )

    scans_list = []
    for s in scans:
        d = s.to_dict()
        dt = d.get("UploadDate")

        if isinstance(dt, datetime):
            clean_date = dt.strftime("%Y-%m-%d %H:%M")
        else:
            clean_date = "—"

        scans_list.append({
            "id": s.id,
            "MRIFilePath": d.get("MRIFilePath", ""),
            "UploadDate": clean_date,
            "ClassificationResult": d.get("ClassificationResult", ""),
        })
        # ===== Last Scan (REAL scan timestamp) =====
    if scans_list:
        case["LastUpdateFormatted"] = scans_list[-1]["UploadDate"]
    else:
        case["LastUpdateFormatted"] = "—"


    # ===== (NEW) Assign Diagnosis Automatically From First Scan =====
    first_scan_diagnosis = None

    if scans_list:
        first_scan_diagnosis = scans_list[0].get("ClassificationResult", "").strip()

    if not case.get("Diagnosis") or case["Diagnosis"].strip() == "":
        if first_scan_diagnosis:
            case["Diagnosis"] = first_scan_diagnosis
            db.collection("Cases").document(case_id).update({
                "Diagnosis": first_scan_diagnosis
            })
        else:
            case["Diagnosis"] = "Pending Diagnosis"
    # ===== Fetch Patient Name =====
    p_doc = db.collection("Patients").document(patient_id).get()
    patient_name = ""
    if p_doc.exists:
        patient_name = p_doc.to_dict().get("FullName", "")


    # ===== Render =====
    return render_template(
        "view_case.html",
        doctor=doctor,
        case_id=case_id,
        case_number=display_number,
        patient_id=patient_id,
        patient_name=patient_name,
        case=case,
        scans=scans_list
    )
@app.route("/patients/<patient_id>/cases/<case_id>/update_treatment", methods=["POST"])
def update_treatment_plan(patient_id, case_id):
    doctor = _get_logged_doctor()
    if not doctor:
        return redirect(url_for("register_login"))

    new_plan = request.form.get("treatment_plan", "").strip()

    db.collection("Cases").document(case_id).update({
        "TreatmentPlan": new_plan,
        "LastUpdate": datetime.now()
    })

    return redirect(url_for("view_case", patient_id=patient_id, case_id=case_id))

# ==========================================================
# 🚪 تسجيل الخروج
# ==========================================================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/2FA_Prosses")
def twofa_prosses():
    return render_template("2FA_Prosses.html")
# ==========================================================
# 🧠 صفحة تحليل السكانات (Scans Analysis)
# ==========================================================
@app.route("/scans")
def scans():
    doctor = _get_logged_doctor()
    if not doctor:
        return redirect(url_for("register_login"))

    patient_id = request.args.get("patient_id")
    case_id = request.args.get("case_id")
    first_image = request.args.get("first_image")   # ⭐ جديد

    return render_template(
        "scans.html",
        doctor=doctor,
        patient_id=patient_id,
        case_id=case_id,
        first_image=first_image    # ⭐ نرسلها للواجهة
    )

#===================model import load_segmentation_model, segment_image========================

from models.segmentation_model import load_segmentation_model, segment_image
from models.classification_model import (
    load_classifier_model,
    classify_image,
    generate_gradcam   
)
seg_model = load_segmentation_model()
cls_model = load_classifier_model()


@app.route("/analyze_mri", methods=["POST"])
def analyze_mri():
    try:
        file = request.files.get("file")
        patient_id = request.form.get("patient_id", "")
        case_id = request.form.get("case_id", "")

        if not file or not patient_id:
            return jsonify({"status": "error", "message": "Missing file or patient_id"}), 400

        # ===== 1) حفظ الصورة =====
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(save_path)

        rel_original = "/" + save_path.replace("\\", "/")

        # ===== 2) إنشاء وثيقة السكان =====
        now = datetime.now()
        scan_ref = db.collection("MRI_Scans").document()
        scan_id = scan_ref.id

    
        tumor_type, confidence = classify_image(cls_model, save_path)
        gradcam_path, pred_idx = generate_gradcam(
            cls_model, save_path, save_name=f"gradcam_{scan_id}.png")
        

        rel_gradcam = "/" + gradcam_path.replace("\\", "/")

        # ===== 4) حفظ السكان بدون Segmentation =====
        scan_ref.set({
            "ScanID": scan_id,
            "PatientID": f"/Patients/{patient_id}",
            "CaseID": f"/Cases/{case_id}",
            "MRIFilePath": rel_original,
            "SegmentationMaskPath": None,  # لا يوجد ماسك حتى الآن
            "GradCAMPath": rel_gradcam,
            "ClassificationResult": tumor_type,
            "ConfidenceScore": confidence,
            "QuickDescription": f"Detected {tumor_type} with {confidence:.1f}% confidence",
            "UploadDate": now,
            "UploadDateStr": now.strftime("%d %b %Y %H:%M")
        })

        # تحديث آخر فحص للمريض
        db.collection("Patients").document(patient_id).update({
            "LastMRIDate": now.strftime("%Y-%m-%d")
        })

        # ===== 5) رجّع فقط التصنيف بدون ماسك =====
        return jsonify({
            "status": "success",
            "scan_id": scan_id,
            "original": rel_original,
            "mask": None,
            "gradcam": rel_gradcam,
            "tumor_type": tumor_type,
            "confidence": confidence,
            "description": f"Detected {tumor_type} with {confidence:.1f}% confidence"
        }), 200

    except Exception as e:
        print(" Error in /analyze_mri:", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    
@app.route("/segment_only", methods=["POST"])
def segment_only():
    try:
        scan_id = request.form.get("scan_id", "").strip()
        if not scan_id:
            return jsonify({"status": "error", "message": "Missing scan_id"}), 400
        scan_ref = db.collection("MRI_Scans").document(scan_id)
        snap = scan_ref.get()
        if not snap.exists:
            return jsonify({"status": "error", "message": "Scan not found"}), 404

        data = snap.to_dict() or {}
        mri_path = data.get("MRIFilePath")
        if not mri_path:
            return jsonify({"status": "error", "message": "Missing MRIFilePath"}), 400

        mri_fs_path = mri_path.lstrip("/")
        mask_path = segment_image(seg_model, mri_fs_path, scan_id=scan_id)
        rel_mask = "/" + mask_path.replace("\\", "/")

        scan_ref.update({
            "SegmentationMaskPath": rel_mask,
            "LastUpdate": datetime.now()
        })

        return jsonify({
            "status": "success",
            "mask": rel_mask
        }), 200

    except Exception as e:
        print("Error in /segment_only:", e)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/view_scan")
def view_scan():
    doctor = _get_logged_doctor()
    if not doctor:
        return redirect(url_for("register_login"))

    scan_id = request.args.get("scan_id")
    scan_number = request.args.get("scan_number")
    case_id = request.args.get("case_id")
    case_number = request.args.get("case_number")

    if not scan_id:
        return "Missing scan_id", 400

    # 🟦 1) نجيب بيانات السكان
    snap = db.collection("MRI_Scans").document(scan_id).get()
    if not snap.exists:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"status": "error", "message": "Scan not found"}), 404
        return "Scan not found", 404

    d = snap.to_dict() or {}

    # 🟦 استخراج patient_id
    patient_ref = d.get("PatientID")
    patient_id = None
    if isinstance(patient_ref, str):
        patient_id = patient_ref.split("/")[-1]

    # 🟦 استخراج case_id إذا ما انرسل بالرابط
    if not case_id:
        case_ref = d.get("CaseID")
        if isinstance(case_ref, str):
            case_id = case_ref.split("/")[-1]

    # 🟦 جلب case_number إذا ما انرسل
    if case_id and not case_number:
        all_cases = list(
            db.collection("Cases")
            .where("PatientID", "==", f"/Patients/{patient_id}")
            .stream()
        )
        sorted_cases = sorted(
            all_cases,
            key=lambda x: x.to_dict().get("StartDate") or ""
        )
        for idx, c in enumerate(sorted_cases, start=1):
            if c.id == case_id:
                case_number = idx
                break

    # 🟦 جلب patient
    patient = None
    if patient_id:
        p_doc = db.collection("Patients").document(patient_id).get()
        if p_doc.exists:
            pdata = p_doc.to_dict() or {}
            patient = {
                "patient_id": patient_id,
                "name": pdata.get("FullName", "")
            }

    # 🟦 AJAX → JSON
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "status": "success",
            "tumor_type": d.get("ClassificationResult"),
            "confidence": d.get("ConfidenceScore"),
            "original": d.get("MRIFilePath"),
            "gradcam": d.get("GradCAMPath"),
            "mask": d.get("SegmentationMaskPath"),
            "description": d.get("QuickDescription")
        })

    # 🟦 HTML
    return render_template(
        "scan_view.html",
        doctor=doctor,
        scan_id=scan_id,
        scan_number=scan_number,
        case_id=case_id,
        case_number=case_number,
        patient=patient
    )



@app.route("/load_more_scans")
def load_more_scans():
    offset = int(request.args.get("offset", 0))

    scans_query = db.collection("MRI_Scans").stream()

    scans_list = []
    for s in scans_query:
        sd = s.to_dict()
        upload_date = sd.get("UploadDate")

        patient_ref = sd.get("PatientID")

        # ⭐ يدعم String + DocumentReference
        if isinstance(patient_ref, str):
            patient_id = patient_ref.split("/")[-1]
        elif hasattr(patient_ref, "id"):
            patient_id = patient_ref.id
        else:
            patient_id = None

        # جلب بيانات المريض
        pdata = {}
        if patient_id:
            patient_doc = db.collection("Patients").document(patient_id).get()
            pdata = patient_doc.to_dict() if patient_doc.exists else {}

        scans_list.append({
            "id": s.id,
            "FullName": pdata.get("FullName", ""),
            "UploadDate": upload_date.strftime("%Y-%m-%d %H:%M") if hasattr(upload_date, "strftime") else "",
        })

    # ترتيب الأحدث
    scans_list = sorted(scans_list, key=lambda x: x["UploadDate"], reverse=True)

    # إرجاع 5 فقط
    more = scans_list[offset: offset + 5]

    return jsonify({
        "scans": more,
        "count": len(more)
    })


@app.route("/delete_patient/<patient_id>", methods=["POST"])
def delete_patient(patient_id):
    # 1) حذف المريض نفسه من Firestore
    patient_ref = db.collection("Patients").document(patient_id)
    patient_ref.delete()

    # 2) حذف الحالات المرتبطة بالمريض
    cases_ref = db.collection("Cases").where("PatientID", "==", patient_id).stream()

    for case in cases_ref:
        case_id = case.id

        # 3) حذف السكانات المرتبطة بالحالة
        scans_ref = db.collection("MRI_Scans").where("CaseID", "==", case_id).stream()

        for scan in scans_ref:
            scan_data = scan.to_dict()

            # حذف الملفات من Storage إذا موجودة
            paths = [
                scan_data.get("MRIFilePath"),
                scan_data.get("GradCAMPath"),
                scan_data.get("SegmentationMaskPath"),
            ]

            for p in paths:
                if p:
                    try:
                        bucket = storage.bucket()
                        blob = bucket.blob(p.replace("/storage/", ""))
                        blob.delete()
                    except Exception:
                        pass

            # حذف سجل السكان
            db.collection("MRI_Scans").document(scan.id).delete()

        # حذف الكيس
        db.collection("Cases").document(case_id).delete()

    flash("Patient deleted successfully.", "success")
    return redirect(url_for("patients"))


from firebase_admin import auth

def get_verify_link(email):
    try:
        # Firebase Admin generates the verification link directly
        link = auth.generate_email_verification_link(email)
        print("🔥 Firebase verification link:", link)
        return link

    except Exception as e:
        print("❌ Error generating verify link:", e)
        raise Exception("فشل إنشاء رابط التحقق من Firebase.")




from send_verification_email import send_verification_email

@app.route("/send_verification_email", methods=["POST"])
def send_verification_email_route():
    data = request.json
    email = data.get("email")
    name = data.get("name")

    firebase_link = auth.generate_email_verification_link(email)

    continue_url = "https://127.0.0.1:5000/registar_login#login"
    final_link = firebase_link + f"&continueUrl={continue_url}"

    send_verification_email(email, name, final_link)

    return {"status": "ok"}



@app.route("/patients/<patient_id>/cases/<case_id>/delete", methods=["POST"])
def delete_case(patient_id, case_id):
    doctor = _get_logged_doctor()
    if not doctor:
        return redirect(url_for("register_login"))

    # 1) تأكيد أن الكيس موجود ويتبع نفس الدكتور
    case_ref = db.collection("Cases").document(case_id)
    case_snap = case_ref.get()

    if not case_snap.exists:
        return ("Case not found", 404)

    case_data = case_snap.to_dict()
    if case_data.get("PatientID") != f"/Patients/{patient_id}":
        return ("Unauthorized", 403)

    # 2) احذف جميع سكانات هذا الكيس
    scans_to_delete = db.collection("MRI_Scans").where(
        "CaseID", "==", f"/Cases/{case_id}"
    ).stream()

    for s in scans_to_delete:
        s.reference.delete()

    # 3) احذف الكيس نفسه
    case_ref.delete()

    return redirect(url_for("patient_profile", patient_id=patient_id))


# ==========================================================
# 🚀 تشغيل السيرفر
# ==========================================================
if __name__ == "__main__":
    app.run(debug=True)