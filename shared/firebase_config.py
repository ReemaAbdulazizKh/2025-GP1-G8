import firebase_admin
from firebase_admin import credentials, firestore

# تحميل بيانات المفتاح الخاص بالخدمة
cred = credentials.Certificate("brainalyze-admin.json")

# تهيئة تطبيق Firebase مرة واحدة فقط
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app(cred)

# إنشاء اتصال مع Firestore
db = firestore.client()
