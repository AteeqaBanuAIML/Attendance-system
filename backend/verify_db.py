import mysql.connector
import os

try:
    db = mysql.connector.connect(
        host="localhost",
        user="root",
        password="n#1728"
    )
    cursor = db.cursor()
    cursor.execute("CREATE DATABASE IF NOT EXISTS attendance_system")
    cursor.execute("USE attendance_system")
    
    # Check if subjects table exists
    cursor.execute("SHOW TABLES LIKE 'subjects'")
    if not cursor.fetchone():
        print("Tables don't exist. Running database.sql...")
        with open("database.sql", "r") as f:
            sql_script = f.read()
            # simple split by semicolon
            for statement in sql_script.split(';'):
                if statement.strip():
                    try:
                        cursor.execute(statement)
                    except Exception as e:
                        print("Error executing:", statement.strip(), "->", e)
    else:
        # check if student_count column exists
        cursor.execute("SHOW COLUMNS FROM subjects LIKE 'student_count'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE subjects ADD COLUMN student_count INT")
            print("Added student_count column to subjects table.")
        else:
            print("Database is already correct.")
            
    db.commit()
    cursor.close()
    db.close()
except Exception as e:
    print("DB Error:", e)
