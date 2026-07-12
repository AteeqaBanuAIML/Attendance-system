import mysql.connector

def check_db():
    try:
        db = mysql.connector.connect(
            host="localhost",
            user="root",
            password="n#1728",
            database="attendance_system"
        )
        cursor = db.cursor()
        
        # Assume a valid student_id like 1 or do a reg_number query
        cursor.execute("SELECT id FROM students LIMIT 1")
        student_id = cursor.fetchone()[0]
        
        query = """
        SELECT sub.id, sub.subject_name,
               (SELECT COUNT(DISTINCT date) FROM attendance WHERE subject_id = sub.id) as total_classes,
               (SELECT COUNT(*) FROM attendance WHERE subject_id = sub.id AND student_id = %s AND status = 'present') as attended
        FROM subjects sub
        JOIN student_subjects ss ON ss.subject_id = sub.id
        WHERE ss.student_id = %s
        """
        cursor.execute(query, (student_id, student_id))
        rows = cursor.fetchall()
        print("Success rows:", rows)
        
    except Exception as e:
        print("MYSQL ERROR CAUGHT:", e)

if __name__ == "__main__":
    check_db()
