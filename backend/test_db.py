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
        
        cursor.execute("SELECT * FROM students")
        print("Students:", cursor.fetchall())
        
        cursor.execute("SELECT * FROM subjects")
        print("Subjects:", cursor.fetchall())
        
        cursor.execute("SELECT * FROM student_subjects")
        print("Student Subjects:", cursor.fetchall())

        cursor.close()
        db.close()
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    check_db()
