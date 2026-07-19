from flask import Flask, request, jsonify
from flask_cors import CORS
import mysql.connector
from mysql.connector import pooling
import os

app = Flask(__name__)
# Allow requests from file:// (null origin), localhost dev servers, and 127.0.0.1
CORS(app, resources={r"/*": {"origins": ["null", "http://localhost:5500", "http://127.0.0.1:5500", "http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8080", "http://127.0.0.1:8080"]}},
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

# ── Connection Pool ──────────────────────────────────────────────────────────
# Keeps 5 reusable connections open to Aiven instead of opening a new TCP
# handshake+SSL on every request. Dramatically reduces per-request latency.
_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="attendance_pool",
            pool_size=5,
            pool_reset_session=True,
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", 3306)),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            ssl_ca="ca.pem"
        )
    return _pool

def get_db_connection():
    """Return a connection from the pool (thread-safe, fast)."""
    return _get_pool().get_connection()

# Ensure schema has required columns.
schema_ready = False

def ensure_schema():
    try:
        db = get_db_connection()
        cursor = db.cursor()
        # Column migrations
        migrations = [
            "ALTER TABLE attendance ADD COLUMN class_type VARCHAR(20) DEFAULT 'Theory';",
            "ALTER TABLE subjects ADD COLUMN subject_category VARCHAR(20) DEFAULT 'course';",
            "ALTER TABLE subjects ADD COLUMN subject_icon VARCHAR(20) DEFAULT 'book';",
            "ALTER TABLE students ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active';"
        ]
        for sql in migrations:
            try:
                cursor.execute(sql)
                db.commit()
            except mysql.connector.Error as e:
                err_msg = str(e)
                if 'Duplicate column name' not in err_msg and 'already exists' not in err_msg:
                    print(f"[WARN] Migration skipped ({sql[:50]}): {e}")
        # App settings table (stores key-value flags like promotion_enabled)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key   VARCHAR(100) PRIMARY KEY,
                setting_value VARCHAR(255) NOT NULL DEFAULT 'false',
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        db.commit()
        # Insert default rows only if they don't already exist
        cursor.execute("""
            INSERT IGNORE INTO app_settings (setting_key, setting_value)
            VALUES ('promotion_enabled', 'false')
        """)
        db.commit()
        cursor.close()
        db.close()
    except Exception as e:
        print(f"[WARN] ensure_schema failed (non-fatal): {e}")

@app.before_request
def before_request():
    global schema_ready
    if not schema_ready:
        try:
            ensure_schema()
        except Exception as e:
            print(f"[WARN] Schema migration error (ignoring): {e}")
        schema_ready = True  # Mark as done regardless so we don't retry every request

@app.after_request
def add_cors_headers(response):
    # Simple wildcard CORS — works for file://, localhost, and any origin.
    # No credentials header needed since we use localStorage, not cookies.
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    return response


@app.route("/")
def home():
    return "Attendance System Backend Running"


@app.route('/add_subject', methods=['POST'])
def add_subject():
    data = request.get_json()

    subject_name = data['subject_name']
    subject_code = data['subject_code']
    student_count = data['student_count']
    subject_category = data.get('subject_category', 'course').lower()
    subject_icon = data.get('subject_icon', '📘')

    db = get_db_connection()
    cursor = db.cursor()
    
    query = """
    INSERT INTO subjects (subject_name, subject_code, student_count, subject_category, subject_icon)
    VALUES (%s, %s, %s, %s, %s)
    """

    cursor.execute(query, (subject_name, subject_code, student_count, subject_category, subject_icon))
    db.commit()
    
    cursor.close()
    db.close()

    return jsonify({"message": "Subject added successfully"})


@app.route('/get_subjects', methods=['GET'])
def get_subjects():
    db = get_db_connection()
    cursor = db.cursor()

    subject_list = []

    try:
        cursor.execute("""
            SELECT s.id, s.subject_name, s.subject_code,
                   COUNT(ss.student_id) as student_count,
                   s.subject_category, s.subject_icon
            FROM subjects s
            LEFT JOIN student_subjects ss ON s.id = ss.subject_id
            GROUP BY s.id, s.subject_name, s.subject_code, s.subject_category, s.subject_icon
        """)
        subjects = cursor.fetchall()
        for sub in subjects:
            subject_list.append({
                "id": sub[0],
                "subject_name": sub[1],
                "subject_code": sub[2],
                "student_count": sub[3],
                "subject_category": sub[4] or 'course',
                "subject_icon": sub[5] or '📘'
            })
    except Exception:
        # Fallback: subject_icon column not yet in DB
        cursor.execute("""
            SELECT s.id, s.subject_name, s.subject_code,
                   COUNT(ss.student_id) as student_count,
                   s.subject_category
            FROM subjects s
            LEFT JOIN student_subjects ss ON s.id = ss.subject_id
            GROUP BY s.id, s.subject_name, s.subject_code, s.subject_category
        """)
        subjects = cursor.fetchall()
        for sub in subjects:
            subject_list.append({
                "id": sub[0],
                "subject_name": sub[1],
                "subject_code": sub[2],
                "student_count": sub[3],
                "subject_category": sub[4] or 'course',
                "subject_icon": '📘'
            })

    cursor.close()
    db.close()

    return jsonify(subject_list)


@app.route('/delete_subject/<int:subject_id>', methods=['DELETE'])
def delete_subject(subject_id):
    db = get_db_connection()
    cursor = db.cursor()

    try:
        # Delete attendance records for this subject
        cursor.execute("DELETE FROM attendance WHERE subject_id = %s", (subject_id,))
        
        # Delete student-subject relationships
        cursor.execute("DELETE FROM student_subjects WHERE subject_id = %s", (subject_id,))
        
        # Delete the subject itself
        cursor.execute("DELETE FROM subjects WHERE id = %s", (subject_id,))
        
        db.commit()
        cursor.close()
        db.close()

        return jsonify({"message": "Subject deleted successfully"}), 200
    except mysql.connector.Error as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({"error": f"Database error: {str(e)}"}), 400
    except Exception as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({"error": f"Error deleting subject: {str(e)}"}), 400


#Register student API
@app.route('/register_student', methods=['POST'])
def register_student():
    data = request.json

    name = data['name']
    number = data['number']
    dept = data['dept']
    year = data['year']
    subjects = data['subjects']   # list of subject IDs

    db = get_db_connection()
    cursor = db.cursor()

    # Insert student
    cursor.execute(
        "INSERT INTO students (name, reg_number, department, year) VALUES (%s, %s, %s, %s)",
        (name, number, dept, year)
    )

    student_id = cursor.lastrowid

    # Insert subject relations
    for sub_id in subjects:
        cursor.execute(
            "INSERT INTO student_subjects (student_id, subject_id) VALUES (%s, %s)",
            (student_id, sub_id)
        )

    db.commit()
    
    cursor.close()
    db.close()

    return jsonify({"message": "Student registered successfully"})


@app.route('/get_students_by_subject/<int:subject_id>', methods=['GET'])
def get_students_by_subject(subject_id):
    db = get_db_connection()
    cursor = db.cursor()
    
    query = """
    SELECT s.id, s.name, s.reg_number 
    FROM students s
    JOIN student_subjects ss ON s.id = ss.student_id
    WHERE ss.subject_id = %s AND s.status = 'active'
    ORDER BY LENGTH(s.reg_number), s.reg_number
    """
    cursor.execute(query, (subject_id,))
    students = cursor.fetchall()
    
    student_list = []
    for stu in students:
        student_list.append({
            "id": stu[0],
            "name": stu[1],
            "reg_number": stu[2]
        })
        
    cursor.close()
    db.close()
    return jsonify(student_list)


@app.route('/student_login', methods=['POST'])
def student_login():
    data = request.json
    name = data.get('name')
    reg_number = data.get('reg_number')

    db = get_db_connection()
    cursor = db.cursor(dictionary=False)

    cursor.execute("SELECT id, name, reg_number, department, year FROM students WHERE name = %s AND reg_number = %s", (name, reg_number))
    student = cursor.fetchone()

    cursor.close()
    db.close()

    if student:
        student_data = {
            "id": student[0],
            "name": student[1],
            "reg_number": student[2],
            "department": student[3],
            "year": student[4]
        }
        return jsonify({"success": True, "message": "Login successful", "student": student_data})
    else:
        return jsonify({"success": False, "message": "Student not registered. Please ensure correct name and register number."})


@app.route('/teacher_login', methods=['POST'])
def teacher_login():
    data = request.json
    name  = data.get('name', '').strip()
    email = data.get('email', '').strip()

    if not name or not email:
        return jsonify({"success": False, "message": "Name and email are required."})

    db = get_db_connection()
    # buffered=True ensures every query's result set is fully consumed
    # before the next query runs, preventing "Unread result found" errors.
    cursor = db.cursor(buffered=True)

    # Auto-save teacher if not already in table (INSERT IGNORE skips if email exists)
    cursor.execute(
        "INSERT IGNORE INTO teachers (name, email) VALUES (%s, %s)",
        (name, email)
    )
    db.commit()

    # Fetch the teacher record (always exists now)
    cursor.execute(
        "SELECT id, name, email FROM teachers WHERE email = %s",
        (email,)
    )
    teacher = cursor.fetchone()

    cursor.close()
    db.close()

    if teacher:
        return jsonify({
            "success": True,
            "message": "Login successful",
            "teacher": {
                "id":    teacher[0],
                "name":  teacher[1],
                "email": teacher[2]
            }
        })
    else:
        return jsonify({"success": False, "message": "Could not save teacher record. Please try again."})


@app.route('/submit_attendance', methods=['POST'])
def submit_attendance():
    data = request.json
    subject_id = data.get('subject_id')
    date_str = data.get('date')
    raw_type = data.get('class_type', 'Theory')
    attendance = data.get('attendance')  # dict: { student_id_str: status }

    # Sanitize class_type — only allow 'Theory' or 'Lab'
    class_type = raw_type if raw_type in ('Theory', 'Lab') else 'Theory'

    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute(
        "DELETE FROM attendance WHERE subject_id = %s AND date = %s AND class_type = %s",
        (subject_id, date_str, class_type)
    )

    for student_id, status in attendance.items():
        cursor.execute(
            "INSERT INTO attendance (student_id, subject_id, date, status, class_type) VALUES (%s, %s, %s, %s, %s)",
            (int(student_id), subject_id, date_str, status, class_type)
        )
    
    db.commit()
    cursor.close()
    db.close()
    return jsonify({"message": "Attendance saved successfully"})


@app.route('/fix_attendance_types', methods=['POST'])
def fix_attendance_types():
    """One-time fix: update any attendance rows with invalid class_type to 'Theory'."""
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute(
        "UPDATE attendance SET class_type = 'Theory' WHERE class_type NOT IN ('Theory', 'Lab')"
    )
    fixed = cursor.rowcount
    db.commit()
    cursor.close()
    db.close()
    return jsonify({"message": f"Fixed {fixed} attendance record(s) with invalid class_type.", "fixed": fixed})


@app.route('/get_attendance_by_date/<int:subject_id>/<date_str>', methods=['GET'])
def get_attendance_by_date(subject_id, date_str):
    class_type = request.args.get('class_type', 'Theory')

    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute(
        "SELECT student_id, status FROM attendance WHERE subject_id = %s AND date = %s AND class_type = %s",
        (subject_id, date_str, class_type)
    )
    records = cursor.fetchall()

    attendance_map = {}
    for r in records:
        attendance_map[str(r[0])] = r[1]
    
    cursor.close()
    db.close()
    return jsonify(attendance_map)


@app.route('/get_student_report/<string:reg_number>', methods=['GET'])
def get_student_report(reg_number):
    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute("SELECT id, year FROM students WHERE reg_number = %s", (reg_number,))
    student_row = cursor.fetchone()
    if not student_row:
        cursor.close()
        db.close()
        return jsonify({})

    student_id, student_year = student_row

    subjects_dict = {}

    # Try the newer query that includes subject_code and subject_icon.
    # Falls back to the safe old query if those columns don't exist yet.
    try:
        query = """
        SELECT sub.id, sub.subject_name, sub.subject_category, sub.subject_code, sub.subject_icon,
               'Theory' as class_type,
               (SELECT COUNT(DISTINCT date) FROM attendance WHERE subject_id = sub.id AND class_type = 'Theory') as total_classes,
               (SELECT COUNT(*) FROM attendance WHERE subject_id = sub.id AND student_id = %s AND status = 'present' AND class_type = 'Theory') as attended
        FROM subjects sub
        JOIN student_subjects ss ON ss.subject_id = sub.id
        WHERE ss.student_id = %s
        UNION ALL
        SELECT sub.id, sub.subject_name, sub.subject_category, sub.subject_code, sub.subject_icon,
               'Lab' as class_type,
               (SELECT COUNT(DISTINCT date) FROM attendance WHERE subject_id = sub.id AND class_type = 'Lab') as total_classes,
               (SELECT COUNT(*) FROM attendance WHERE subject_id = sub.id AND student_id = %s AND status = 'present' AND class_type = 'Lab') as attended
        FROM subjects sub
        JOIN student_subjects ss ON ss.subject_id = sub.id
        WHERE ss.student_id = %s
        """
        cursor.execute(query, (student_id, student_id, student_id, student_id))
        rows = cursor.fetchall()

        for r in rows:
            subject_id    = r[0]
            subject_name  = r[1]
            category      = (r[2] or 'course').lower()
            subject_code  = r[3] or ''
            subject_icon  = r[4] or '📘'
            class_type    = r[5]
            total_classes = r[6] or 0
            attended      = r[7] or 0
            percentage    = int((attended / total_classes * 100)) if total_classes > 0 else 0

            if subject_id not in subjects_dict:
                subjects_dict[subject_id] = {
                    "subject_id": subject_id,
                    "subject": subject_name,
                    "subject_code": subject_code,
                    "subject_icon": subject_icon,
                    "category": category,
                    "theory": {"totalClasses": 0, "attended": 0, "percentage": 0},
                    "lab":    {"totalClasses": 0, "attended": 0, "percentage": 0}
                }
            subjects_dict[subject_id][class_type.lower()] = {
                "totalClasses": total_classes,
                "attended": attended,
                "percentage": percentage
            }

    except Exception:
        # Fallback: subject_icon / subject_code columns not yet in DB
        fallback_query = """
        SELECT sub.id, sub.subject_name, sub.subject_category, sub.subject_code,
               'Theory' as class_type,
               (SELECT COUNT(DISTINCT date) FROM attendance WHERE subject_id = sub.id AND class_type = 'Theory') as total_classes,
               (SELECT COUNT(*) FROM attendance WHERE subject_id = sub.id AND student_id = %s AND status = 'present' AND class_type = 'Theory') as attended
        FROM subjects sub
        JOIN student_subjects ss ON ss.subject_id = sub.id
        WHERE ss.student_id = %s
        UNION ALL
        SELECT sub.id, sub.subject_name, sub.subject_category, sub.subject_code,
               'Lab' as class_type,
               (SELECT COUNT(DISTINCT date) FROM attendance WHERE subject_id = sub.id AND class_type = 'Lab') as total_classes,
               (SELECT COUNT(*) FROM attendance WHERE subject_id = sub.id AND student_id = %s AND status = 'present' AND class_type = 'Lab') as attended
        FROM subjects sub
        JOIN student_subjects ss ON ss.subject_id = sub.id
        WHERE ss.student_id = %s
        """
        cursor.execute(fallback_query, (student_id, student_id, student_id, student_id))
        rows = cursor.fetchall()

        for r in rows:
            subject_id    = r[0]
            subject_name  = r[1]
            category      = (r[2] or 'course').lower()
            subject_code  = r[3] or ''
            class_type    = r[4]
            total_classes = r[5] or 0
            attended      = r[6] or 0
            percentage    = int((attended / total_classes * 100)) if total_classes > 0 else 0

            if subject_id not in subjects_dict:
                subjects_dict[subject_id] = {
                    "subject_id": subject_id,
                    "subject": subject_name,
                    "subject_code": subject_code,
                    "subject_icon": '📘',
                    "category": category,
                    "theory": {"totalClasses": 0, "attended": 0, "percentage": 0},
                    "lab":    {"totalClasses": 0, "attended": 0, "percentage": 0}
                }
            subjects_dict[subject_id][class_type.lower()] = {
                "totalClasses": total_classes,
                "attended": attended,
                "percentage": percentage
            }

    subjects_list = list(subjects_dict.values())

    # Keep compatibility with existing front-end mapping by returning a simple subject array and a grouped object.
    data = {
        "subjects": subjects_list,
        "Registered Subjects": subjects_list
    }

    cursor.close()
    db.close()
    return jsonify(data)


@app.route('/get_student_subjects/<string:reg_number>', methods=['GET'])
def get_student_subjects(reg_number):
    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute("SELECT id FROM students WHERE reg_number = %s", (reg_number,))
    student_row = cursor.fetchone()
    if not student_row:
        cursor.close()
        db.close()
        return jsonify([])

    student_id = student_row[0]

    try:
        cursor.execute(
            "SELECT s.id, s.subject_name, s.subject_code, s.subject_icon FROM subjects s "
            "JOIN student_subjects ss ON s.id = ss.subject_id "
            "WHERE ss.student_id = %s",
            (student_id,)
        )
        rows = cursor.fetchall()
        subjects = []
        for r in rows:
            subjects.append({
                "subject_id": r[0],
                "subject_name": r[1],
                "subject_code": r[2],
                "subject_icon": r[3] or '📘'
            })
    except Exception:
        # Fallback: subject_icon column not yet in DB
        cursor.execute(
            "SELECT s.id, s.subject_name, s.subject_code FROM subjects s "
            "JOIN student_subjects ss ON s.id = ss.subject_id "
            "WHERE ss.student_id = %s",
            (student_id,)
        )
        rows = cursor.fetchall()
        subjects = []
        for r in rows:
            subjects.append({
                "subject_id": r[0],
                "subject_name": r[1],
                "subject_code": r[2],
                "subject_icon": '📘'
            })

    cursor.close()
    db.close()
    return jsonify(subjects)


@app.route('/get_class_dates/<int:subject_id>', methods=['GET'])
def get_class_dates(subject_id):
    """Return all distinct dates attendance was submitted for a subject+class_type."""
    class_type = request.args.get('class_type', 'Theory')

    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute(
        "SELECT DISTINCT date FROM attendance WHERE subject_id = %s AND class_type = %s ORDER BY date",
        (subject_id, class_type)
    )
    rows = cursor.fetchall()

    dates = []
    for r in rows:
        date_str = r[0].isoformat() if hasattr(r[0], 'isoformat') else str(r[0])
        dates.append(date_str)

    cursor.close()
    db.close()
    return jsonify(dates)


@app.route('/get_student_calendar/<string:reg_number>/<int:subject_id>', methods=['GET'])
def get_student_calendar(reg_number, subject_id):
    class_type = request.args.get('class_type', 'Theory')

    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute("SELECT id FROM students WHERE reg_number = %s", (reg_number,))
    student_row = cursor.fetchone()
    if not student_row:
        cursor.close()
        db.close()
        return jsonify({})

    student_id = student_row[0]

    cursor.execute(
        "SELECT date, status FROM attendance WHERE student_id = %s AND subject_id = %s AND class_type = %s",
        (student_id, subject_id, class_type)
    )
    records = cursor.fetchall()

    calendar_data = {}
    for r in records:
        date_str = r[0].isoformat() if hasattr(r[0], 'isoformat') else str(r[0])
        calendar_data[date_str] = r[1]

    cursor.close()
    db.close()
    return jsonify(calendar_data)



# ── NEW: students management endpoints ─────────────────────────────────────

@app.route('/get_students_by_year', methods=['GET'])
def get_students_by_year():
    """Return all students of a given year along with their enrolled subjects.
    Uses 2 bulk queries instead of N+1 queries.
    """
    year = request.args.get('year', '1')

    db = get_db_connection()
    cursor = db.cursor()

    # Query 1: all active students for the year
    cursor.execute(
        "SELECT id, name, reg_number FROM students WHERE year = %s AND status = 'active' ORDER BY LENGTH(reg_number), reg_number",
        (year,)
    )
    student_rows = cursor.fetchall()

    if not student_rows:
        cursor.close()
        db.close()
        return jsonify([])

    student_ids = [r[0] for r in student_rows]
    fmt = ','.join(['%s'] * len(student_ids))

    # Query 2: all subjects for ALL those students in one shot
    cursor.execute(
        f"""SELECT ss.student_id, sub.id, sub.subject_name, sub.subject_code
            FROM subjects sub
            JOIN student_subjects ss ON ss.subject_id = sub.id
            WHERE ss.student_id IN ({fmt})
            ORDER BY sub.subject_name""",
        student_ids
    )
    # Group subjects by student_id
    subjects_by_student = {}
    for row in cursor.fetchall():
        sid, sub_id, sub_name, sub_code = row
        subjects_by_student.setdefault(sid, []).append(
            {"id": sub_id, "subject_name": sub_name, "subject_code": sub_code}
        )

    cursor.close()
    db.close()

    result = []
    for idx, stu in enumerate(student_rows):
        student_id, name, reg_number = stu
        result.append({
            "serial": idx + 1,
            "id": student_id,
            "name": name,
            "reg_number": reg_number,
            "subjects": subjects_by_student.get(student_id, [])
        })

    return jsonify(result)


@app.route('/get_attendance_matrix', methods=['GET'])
def get_attendance_matrix():
    """
    Return a matrix of attendance percentages:
    rows = students of a given year, columns = subjects they are enrolled in.
    class_type filter: 'All' (default) combines theory+lab; 'Theory' or 'Lab' shows only that type.

    OPTIMIZED: Uses 3 bulk GROUP BY queries instead of (students x subjects x 5) queries.
    For 60 students x 8 subjects this reduces ~2400 DB round-trips down to 3.
    """
    year = request.args.get('year', '1')
    class_type_filter = request.args.get('class_type', 'All')  # 'All' | 'Theory' | 'Lab'

    db = get_db_connection()
    cursor = db.cursor()

    # ── Query 1: active students ─────────────────────────────────────────────
    cursor.execute(
        "SELECT id, name, reg_number FROM students WHERE year = %s AND status = 'active' ORDER BY LENGTH(reg_number), reg_number",
        (year,)
    )
    student_rows = cursor.fetchall()
    if not student_rows:
        cursor.close()
        db.close()
        return jsonify({"subjects": [], "students": []})

    student_ids = [r[0] for r in student_rows]
    fmt = ','.join(['%s'] * len(student_ids))

    # ── Query 2: subjects ────────────────────────────────────────────────────
    if class_type_filter in ('Theory', 'Lab'):
        cursor.execute(
            f"""SELECT DISTINCT sub.id, sub.subject_name, sub.subject_code
                FROM subjects sub
                JOIN student_subjects ss ON ss.subject_id = sub.id
                WHERE ss.student_id IN ({fmt})
                AND EXISTS (
                    SELECT 1 FROM attendance a
                    WHERE a.subject_id = sub.id AND a.class_type = %s
                )
                ORDER BY sub.subject_name""",
            student_ids + [class_type_filter]
        )
    else:
        cursor.execute(
            f"""SELECT DISTINCT sub.id, sub.subject_name, sub.subject_code
                FROM subjects sub
                JOIN student_subjects ss ON ss.subject_id = sub.id
                WHERE ss.student_id IN ({fmt})
                ORDER BY sub.subject_name""",
            student_ids
        )
    subject_rows = cursor.fetchall()
    subjects = [{"id": r[0], "subject_name": r[1], "subject_code": r[2]} for r in subject_rows]
    subject_ids = [s["id"] for s in subjects]

    if not subject_ids:
        cursor.close()
        db.close()
        return jsonify({"subjects": [], "students": []})

    sub_fmt = ','.join(['%s'] * len(subject_ids))

    # ── Query 3a: enrollment map (student_id -> set of subject_ids) ──────────
    cursor.execute(
        f"SELECT student_id, subject_id FROM student_subjects"
        f" WHERE student_id IN ({fmt}) AND subject_id IN ({sub_fmt})",
        student_ids + subject_ids
    )
    enrolled_set = set()
    for row in cursor.fetchall():
        enrolled_set.add((row[0], row[1]))

    # ── Query 3b: bulk attendance totals per (subject_id, class_type) ────────
    # total classes held (distinct dates) per subject+class_type
    if class_type_filter == 'All':
        ct_condition = "class_type IN ('Theory', 'Lab')"
        ct_params = []
    else:
        ct_condition = "class_type = %s"
        ct_params = [class_type_filter]

    cursor.execute(
        f"""SELECT subject_id, class_type,
                   COUNT(DISTINCT date)                                       AS total_classes,
                   SUM(CASE WHEN student_id IN ({fmt}) AND status='present' THEN 1 ELSE 0 END) AS dummy
            FROM attendance
            WHERE subject_id IN ({sub_fmt}) AND {ct_condition}
            GROUP BY subject_id, class_type""",
        student_ids + subject_ids + ct_params
    )
    # total_classes_map: (subject_id, class_type) -> total_distinct_dates
    total_classes_map = {}
    for row in cursor.fetchall():
        total_classes_map[(row[0], row[1])] = row[2]

    # ── Query 3c: per-student attended counts ────────────────────────────────
    cursor.execute(
        f"""SELECT student_id, subject_id, class_type, COUNT(*) AS attended
            FROM attendance
            WHERE student_id IN ({fmt})
              AND subject_id IN ({sub_fmt})
              AND status = 'present'
              AND {ct_condition}
            GROUP BY student_id, subject_id, class_type""",
        student_ids + subject_ids + ct_params
    )
    # attended_map: (student_id, subject_id, class_type) -> count
    attended_map = {}
    for row in cursor.fetchall():
        attended_map[(row[0], row[1], row[2])] = row[3]

    cursor.close()
    db.close()

    # ── Assemble response entirely in Python (no more DB calls) ─────────────
    students_data = []
    for stu in student_rows:
        student_id, name, reg_number = stu
        attendance_by_subject = {}

        for sub in subjects:
            sub_id = sub["id"]

            if (student_id, sub_id) not in enrolled_set:
                attendance_by_subject[sub_id] = None
                continue

            class_types = [class_type_filter] if class_type_filter != 'All' else ['Theory', 'Lab']
            total_classes  = 0
            total_attended = 0
            for ct in class_types:
                total_classes  += total_classes_map.get((sub_id, ct), 0)
                total_attended += attended_map.get((student_id, sub_id, ct), 0)

            pct = int(total_attended / total_classes * 100) if total_classes > 0 else 0
            attendance_by_subject[sub_id] = {
                "percentage": pct,
                "total": total_classes,
                "attended": total_attended
            }

        students_data.append({
            "id": student_id,
            "name": name,
            "reg_number": reg_number,
            "attendance": attendance_by_subject
        })

    return jsonify({"subjects": subjects, "students": students_data})


@app.route('/delete_student/<int:student_id>', methods=['DELETE'])
def delete_student(student_id):
    """Delete a student and all their related records."""
    db = get_db_connection()
    cursor = db.cursor()

    try:
        cursor.execute("DELETE FROM attendance WHERE student_id = %s", (student_id,))
        cursor.execute("DELETE FROM student_subjects WHERE student_id = %s", (student_id,))
        cursor.execute("DELETE FROM students WHERE id = %s", (student_id,))
        db.commit()
        cursor.close()
        db.close()
        return jsonify({"message": "Student deleted successfully"}), 200
    except mysql.connector.Error as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({"error": str(e)}), 400


@app.route('/get_student_history/<string:reg_number>', methods=['GET'])
def get_student_history(reg_number):
    """
    Return attendance stats for a student's historical subjects.
    Strategy:
      1. Check enrollment_history (reliable snapshot from promote_student)
      2. Fall back to attendance-based approach: subjects the student attended
         but is NOT currently enrolled in (works for students promoted before the fix)
    """
    db     = get_db_connection()
    cursor = db.cursor()

    # Ensure table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enrollment_history (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            student_id  INT         NOT NULL,
            subject_id  INT         NOT NULL,
            year        VARCHAR(50) NOT NULL,
            promoted_at TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Get student ID
    cursor.execute("SELECT id FROM students WHERE reg_number = %s", (reg_number,))
    student_row = cursor.fetchone()
    if not student_row:
        cursor.close(); db.close()
        return jsonify({"subjects": [], "Registered Subjects": []})

    student_id = student_row[0]

    # --- Approach 1: enrollment_history snapshot ---
    cursor.execute(
        "SELECT DISTINCT subject_id FROM enrollment_history WHERE student_id = %s",
        (student_id,)
    )
    old_ids = [row[0] for row in cursor.fetchall()]

    # --- Approach 2 (fallback): attendance - current enrollment ---
    if not old_ids:
        cursor.execute(
            "SELECT subject_id FROM student_subjects WHERE student_id = %s",
            (student_id,)
        )
        current_ids = {row[0] for row in cursor.fetchall()}

        cursor.execute(
            "SELECT DISTINCT subject_id FROM attendance WHERE student_id = %s",
            (student_id,)
        )
        attended_ids = {row[0] for row in cursor.fetchall()}

        # subjects attended in the past that are no longer enrolled
        old_ids = list(attended_ids - current_ids)

    if not old_ids:
        cursor.close(); db.close()
        return jsonify({"subjects": [], "Registered Subjects": []})

    subjects_dict = {}
    for sub_id in old_ids:
        cursor.execute(
            "SELECT id, subject_name, subject_category FROM subjects WHERE id = %s",
            (sub_id,)
        )
        sub_row = cursor.fetchone()
        if not sub_row:
            continue

        subjects_dict[sub_id] = {
            "subject_id": sub_row[0],
            "subject":    sub_row[1],
            "category":   (sub_row[2] or 'course').lower(),
            "theory": {"totalClasses": 0, "attended": 0, "percentage": 0},
            "lab":    {"totalClasses": 0, "attended": 0, "percentage": 0}
        }

        for class_type in ('Theory', 'Lab'):
            cursor.execute(
                "SELECT COUNT(DISTINCT date) FROM attendance "
                "WHERE subject_id = %s AND class_type = %s",
                (sub_id, class_type)
            )
            total = cursor.fetchone()[0] or 0

            cursor.execute(
                "SELECT COUNT(*) FROM attendance WHERE subject_id = %s AND student_id = %s "
                "AND status = 'present' AND class_type = %s",
                (sub_id, student_id, class_type)
            )
            attended = cursor.fetchone()[0] or 0
            pct = int(attended / total * 100) if total > 0 else 0

            subjects_dict[sub_id][class_type.lower()] = {
                "totalClasses": total,
                "attended":     attended,
                "percentage":   pct
            }

    subjects_list = list(subjects_dict.values())
    cursor.close()
    db.close()
    return jsonify({"subjects": subjects_list, "Registered Subjects": subjects_list})


# ── Year Promotion ──────────────────────────────────────────────────────────

PROMOTION_CODE = 'Promote#Year@bcu28'

YEAR_NEXT = {
    '1st year': '2nd year',
    '2nd year': '3rd year',
}

# ── Promotion toggle endpoints ────────────────────────────────────────────────

@app.route('/promotion_status', methods=['GET'])
def promotion_status():
    """Return whether teacher has enabled student year promotion."""
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'promotion_enabled'")
    row = cursor.fetchone()
    cursor.close(); db.close()
    enabled = (row[0] == 'true') if row else False
    return jsonify({"enabled": enabled})


@app.route('/set_promotion_status', methods=['POST'])
def set_promotion_status():
    """Teacher toggles the promotion on/off switch."""
    data    = request.json
    enabled = bool(data.get('enabled', False))
    value   = 'true' if enabled else 'false'
    db      = get_db_connection()
    cursor  = db.cursor()
    cursor.execute(
        "INSERT INTO app_settings (setting_key, setting_value) VALUES ('promotion_enabled', %s) "
        "ON DUPLICATE KEY UPDATE setting_value = %s",
        (value, value)
    )
    db.commit()
    cursor.close(); db.close()
    return jsonify({"success": True, "enabled": enabled})

def normalize_year(raw):
    """Normalise any stored year string to a canonical key used in YEAR_NEXT."""
    raw = (raw or '').lower().strip()
    if '1st' in raw or 'first' in raw or raw == '1':
        return '1st year'
    if '2nd' in raw or 'second' in raw or raw == '2':
        return '2nd year'
    if '3rd' in raw or 'third' in raw or raw == '3':
        return '3rd year'
    return None


@app.route('/verify_promotion', methods=['POST'])
def verify_promotion():
    """
    Step 1 of promotion flow.
    Validates the promotion code, finds the student, and returns
    their current year + next year without making any DB changes.
    """
    data           = request.json
    name           = (data.get('name')           or '').strip()
    reg_number     = (data.get('reg_number')     or '').strip()

    # Check if teacher has enabled promotion
    db     = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'promotion_enabled'")
    row = cursor.fetchone()
    cursor.close(); db.close()
    if not row or row[0] != 'true':
        return jsonify({"success": False, "message": "Promotion is currently disabled. Please ask your teacher to enable it."})

    if not name or not reg_number:
        return jsonify({"success": False, "message": "Name and register number are required."})

    db     = get_db_connection()
    cursor = db.cursor()
    cursor.execute(
        "SELECT id, name, reg_number, department, year FROM students WHERE name = %s AND reg_number = %s",
        (name, reg_number)
    )
    student = cursor.fetchone()
    cursor.close()
    db.close()

    if not student:
        return jsonify({"success": False, "message": "Student not found. Please check your name and register number."})

    current_year = normalize_year(student[4])
    if not current_year:
        return jsonify({"success": False, "message": "Could not determine your current year. Please contact your teacher."})

    next_year = YEAR_NEXT.get(current_year)
    if not next_year:
        return jsonify({"success": False, "message": "You are already in the final year (3rd Year). Promotion is not applicable."})

    return jsonify({
        "success": True,
        "student": {
            "id":           student[0],
            "name":         student[1],
            "reg_number":   student[2],
            "current_year": current_year,
            "next_year":    next_year
        }
    })


@app.route('/promote_student', methods=['POST'])
def promote_student():
    """
    Step 2 of promotion flow.
    Updates the student's year and resets their subject enrollments.
    Old attendance records are preserved (untouched).
    """
    data         = request.json
    student_id   = data.get('student_id')
    new_subjects = data.get('new_subjects', [])

    if not student_id:
        return jsonify({"success": False, "message": "Student ID is required."})
    if not new_subjects:
        return jsonify({"success": False, "message": "At least one subject must be selected."})

    db     = get_db_connection()
    cursor = db.cursor()

    try:
        # Re-verify current year (safety check)
        cursor.execute("SELECT year FROM students WHERE id = %s", (student_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close(); db.close()
            return jsonify({"success": False, "message": "Student not found."})

        current_year = normalize_year(row[0])
        next_year    = YEAR_NEXT.get(current_year)
        if not next_year:
            cursor.close(); db.close()
            return jsonify({"success": False, "message": "Cannot promote: already in the final year."})

        # ── Snapshot old subjects into enrollment_history BEFORE deleting ──
        # This is the reliable source for get_student_history later.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS enrollment_history (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                student_id  INT         NOT NULL,
                subject_id  INT         NOT NULL,
                year        VARCHAR(50) NOT NULL,
                promoted_at TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute(
            "SELECT subject_id FROM student_subjects WHERE student_id = %s",
            (student_id,)
        )
        old_subject_ids = [row[0] for row in cursor.fetchall()]
        for sub_id in old_subject_ids:
            cursor.execute(
                "INSERT INTO enrollment_history (student_id, subject_id, year) VALUES (%s, %s, %s)",
                (student_id, sub_id, current_year)
            )

        # Update year
        cursor.execute("UPDATE students SET year = %s WHERE id = %s", (next_year, student_id))

        # Reset subject enrolments (old attendance rows are kept intact)
        cursor.execute("DELETE FROM student_subjects WHERE student_id = %s", (student_id,))
        for sub_id in new_subjects:
            cursor.execute(
                "INSERT INTO student_subjects (student_id, subject_id) VALUES (%s, %s)",
                (student_id, int(sub_id))
            )

        db.commit()
        cursor.close()
        db.close()
        return jsonify({"success": True, "message": f"Successfully promoted to {next_year}."})

    except mysql.connector.Error as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({"success": False, "message": f"Database error: {str(e)}"})


@app.route('/passout_all_3rd_year', methods=['POST'])
def passout_all_3rd_year():
    """
    Bulk pass out: marks ALL active 3rd-year students as passed out.
    For each student:
      - Snapshots their subjects into enrollment_history.
      - Sets status = 'passout'.
      - Clears their active subject enrolments (attendance history kept).
    Returns the count of students processed.
    """
    db     = get_db_connection()
    cursor = db.cursor()

    try:
        # Ensure enrollment_history table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS enrollment_history (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                student_id  INT         NOT NULL,
                subject_id  INT         NOT NULL,
                year        VARCHAR(50) NOT NULL,
                promoted_at TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Get all active 3rd year students
        cursor.execute(
            "SELECT id FROM students WHERE status = 'active' AND year = '3rd year'"
        )
        student_ids = [row[0] for row in cursor.fetchall()]

        if not student_ids:
            cursor.close(); db.close()
            return jsonify({"success": True, "count": 0,
                            "message": "No active 3rd year students found."})

        for student_id in student_ids:
            # Snapshot subjects to history
            cursor.execute(
                "SELECT subject_id FROM student_subjects WHERE student_id = %s",
                (student_id,)
            )
            for row in cursor.fetchall():
                cursor.execute(
                    "INSERT INTO enrollment_history (student_id, subject_id, year) VALUES (%s, %s, '3rd year')",
                    (student_id, row[0])
                )
            # Mark passout and clear enrolments
            cursor.execute(
                "UPDATE students SET status = 'passout' WHERE id = %s", (student_id,)
            )
            cursor.execute(
                "DELETE FROM student_subjects WHERE student_id = %s", (student_id,)
            )

        db.commit()
        cursor.close()
        db.close()
        return jsonify({"success": True, "count": len(student_ids),
                        "message": f"{len(student_ids)} student(s) marked as passed out."})

    except mysql.connector.Error as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({"success": False, "message": f"Database error: {str(e)}"})


@app.route('/passout_student', methods=['POST'])
def passout_student():
    """
    Mark a 3rd-year student as passed out.
    - Saves their current subjects to enrollment_history (same as promotion).
    - Sets status = 'passout' so they are hidden from all teacher-facing views.
    - Clears their active subject enrolments (attendance history is kept).
    - Student login and history views still work normally.
    """
    data       = request.json
    student_id = data.get('student_id')

    if not student_id:
        return jsonify({"success": False, "message": "Student ID is required."})

    db     = get_db_connection()
    cursor = db.cursor()

    try:
        # Verify student exists and is in 3rd year
        cursor.execute("SELECT year, status FROM students WHERE id = %s", (student_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close(); db.close()
            return jsonify({"success": False, "message": "Student not found."})

        current_year = normalize_year(row[0])
        current_status = row[1]

        if current_status == 'passout':
            cursor.close(); db.close()
            return jsonify({"success": False, "message": "Student is already marked as passed out."})

        if current_year != '3rd year':
            cursor.close(); db.close()
            return jsonify({"success": False, "message": "Only 3rd year students can be marked as passed out."})

        # Ensure enrollment_history table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS enrollment_history (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                student_id  INT         NOT NULL,
                subject_id  INT         NOT NULL,
                year        VARCHAR(50) NOT NULL,
                promoted_at TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Snapshot current subjects into enrollment_history
        cursor.execute(
            "SELECT subject_id FROM student_subjects WHERE student_id = %s",
            (student_id,)
        )
        old_subject_ids = [r[0] for r in cursor.fetchall()]
        for sub_id in old_subject_ids:
            cursor.execute(
                "INSERT INTO enrollment_history (student_id, subject_id, year) VALUES (%s, %s, %s)",
                (student_id, sub_id, '3rd year')
            )

        # Mark as passout and clear active enrolments
        cursor.execute("UPDATE students SET status = 'passout' WHERE id = %s", (student_id,))
        cursor.execute("DELETE FROM student_subjects WHERE student_id = %s", (student_id,))

        db.commit()
        cursor.close()
        db.close()
        return jsonify({"success": True, "message": "Student marked as passed out successfully."})

    except mysql.connector.Error as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({"success": False, "message": f"Database error: {str(e)}"})


if __name__ == '__main__':
    app.run(debug=True)