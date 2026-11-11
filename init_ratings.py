import sqlite3

# ငြိမ်းရဲ့ Database File နာမည်
DB_NAME = 'database.db' 

def fix_ratings_table():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # ၁။ Column မှားနေတဲ့ Table အဟောင်းကို ဖျက်လိုက်ခြင်း
        cursor.execute("DROP TABLE IF EXISTS Ratings")

        # ၂။ id လို့ နာမည်ပေးထားတဲ့ Ratings Table အသစ် ပြန်ဆောက်ခြင်း
        cursor.execute('''
        CREATE TABLE Ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            resource_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (resource_id) REFERENCES resources(id),
            UNIQUE(user_id, resource_id)
        )
        ''')

        conn.commit()
        conn.close()
        print("✅ Ratings table successfully updated with 'id' column!")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == '__main__':
    fix_ratings_table()