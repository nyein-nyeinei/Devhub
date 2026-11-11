# For DevHub
import os
import re
import math
import sqlite3
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__) 
DATABASE = 'database.db'

# 🔑 Flask Session သုံးရန်အတွက် လုံခြုံရေး Key သတ်မှတ်ခြင်း
app.secret_key = 'devhub_ucsm_secret_key_by_freya'

# 📂 Profile ပုံများ သိမ်းဆည်းမည့် Static Folder သတ်မှတ်ခြင်း ('webp' အပါအဝင် ဖြည့်စွက်ထားပါသည်)
UPLOAD_FOLDER = 'static/uploads/profile_pics'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 🖼️ ပုံ extension စစ်ဆေးသည့် Helper Function
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 🛠️ Database Auto Migration (category_id Column မရှိပါက အလိုအလျောက် ထည့်ပေးမည်)
def fix_database_schema():
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(Resources)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'category_id' not in columns:
            cursor.execute("ALTER TABLE Resources ADD COLUMN category_id INTEGER DEFAULT 1")
            conn.commit()
        conn.close()
    except Exception as e:
        print("Schema fix error:", e)

fix_database_schema()

@app.context_processor
def inject_notifications():
    unread_count = 0

    if 'user_id' in session:
        conn = sqlite3.connect(DATABASE, timeout=20)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT COUNT(*)
                FROM Notifications
                WHERE receiver_id = ?
                AND is_read = 0
            """, (session['user_id'],))

            result = cursor.fetchone()
            if result:
                unread_count = result[0]
        except Exception as e:
            print("Context processor error:", e)
        finally:
            conn.close()

    return {
        "unread_count": unread_count
    }

# 🛠 Database နဲ့ Table ၈ ခုလုံးကို စတင်တည်ဆောက်မည့် Function
def init_db():
    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()
    
    # 1. Users Table (🌟 is_admin Column ပါဝင်ပြီး)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            account_type TEXT NOT NULL,
            profile_pic TEXT DEFAULT 'default.png',
            is_admin INTEGER DEFAULT 0
        )
    ''')
    
    # 2. Categories Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            icon TEXT NOT NULL
        )
    ''')
    
    # 3. Resources Table (✨ is_deleted Column ကို Error မတက်အောင် ဖြည့်စွက်ထားသည်)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            description TEXT,
            level TEXT NOT NULL,
            view_count INTEGER DEFAULT 0,
            user_id INTEGER,
            is_deleted INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES Users (id)
        )
    ''')
    
    # 4. Resource_Categories Table (Many-to-Many)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Resource_Categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_id INTEGER,
            category_id INTEGER,
            FOREIGN KEY (resource_id) REFERENCES Resources (id),
            FOREIGN KEY (category_id) REFERENCES Categories (id)
        )
    ''')
    
    # 5. Bookmarks Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            resource_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES Users (id),
            FOREIGN KEY (resource_id) REFERENCES Resources (id)
        )
    ''')
    
    # 6. Upvotes Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Upvotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            resource_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES Users (id),
            FOREIGN KEY (resource_id) REFERENCES Resources (id)
        )
    ''')
    
    # 7. Reports Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            resource_id INTEGER,
            reason TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (user_id) REFERENCES Users (id),
            FOREIGN KEY (resource_id) REFERENCES Resources (id)
        )
    ''')
    
    # 8. Comments Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_id INTEGER,
            user_id INTEGER,
            comment_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (resource_id) REFERENCES Resources (id),
            FOREIGN KEY (user_id) REFERENCES Users (id)
        )
    ''')
    # Reply support အတွက် parent_id ထည့်ခြင်း
    try:
        cursor.execute("""
            ALTER TABLE Comments
            ADD COLUMN parent_id INTEGER DEFAULT NULL
        """)
    except sqlite3.OperationalError:
        # parent_id column ရှိပြီးသားဆိုရင် Error မတက်အောင် ကျော်သွားမယ်
        pass
    
    # 9. Ratings Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Ratings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            resource_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(user_id, resource_id),

            FOREIGN KEY(user_id) REFERENCES Users(id),
            FOREIGN KEY(resource_id) REFERENCES Resources(id)
        )
    ''')
    # 10. Notifications Table
    cursor.execute('''
         CREATE TABLE IF NOT EXISTS Notifications(
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             sender_id INTEGER NOT NULL,
             receiver_id INTEGER NOT NULL,
            resource_id INTEGER,
            type TEXT NOT NULL,
            message TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(sender_id) REFERENCES Users(id),
            FOREIGN KEY(receiver_id) REFERENCES Users(id),
            FOREIGN KEY(resource_id) REFERENCES Resources(id)
        )
    ''')

    # 📁 Categories Table တည်ဆောက်ခြင်း
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')

    # 📂 ကဏ္ဍ ၇ ခုကို ဒေတာဘေ့စ်ထဲသို့ အော်တို အဆင်သင့် ထည့်သွင်းခြင်း
    default_categories = [
        ('Python & Backend', '🐍'),
        ('Web Frontend', '💻'),
        ('UI/UX Design', '🎨'),
        ('English for Tech', '🇬🇧'),
        ('Career & Interview', '💼'),
        ('Mobile App Dev', '📱'),
        ('AI & Data Science', '🤖')
    ]
    
    for name, icon in default_categories:
        cursor.execute('''
            INSERT OR IGNORE INTO Categories (name, icon) VALUES (?, ?)
        ''', (name, icon))
        
    conn.commit()
    conn.close()

# 📂 Profile ပုံသိမ်းမည့် Folder မရှိပါက အော်တိုဆောက်ခိုင်းခြင်း
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# 🛡 App စတားတိုင်း Table များကို အမြဲတမ်း စစ်ဆေးပြီး အလိုအလျောက် ဆောက်ပေးစေရန်
init_db()

# ==================== ROUTES (လမ်းကြောင်းများ) ====================

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_user_id = session['user_id']
    selected_cat_id = request.args.get('category_id', type=int)
    search_query = request.args.get('search', type=str, default='').strip()
    sort_by = request.args.get('sort', type=str, default='latest')

    page = request.args.get('page', type=int, default=1)
    per_page = 10
    offset = (page - 1) * per_page

    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()

    # ==============================
    # Total Posts တွက်ချက်ခြင်း
    # ==============================
    count_query = '''
        SELECT COUNT(DISTINCT Resources.id)
        FROM Resources
        LEFT JOIN Resource_Categories
            ON Resources.id = Resource_Categories.resource_id
        WHERE Resources.is_deleted = 0
    '''

    count_params = []

    if selected_cat_id:
        count_query += '''
            AND Resource_Categories.category_id = ?
        '''
        count_params.append(selected_cat_id)

    if search_query:
        count_query += '''
            AND (
                Resources.title LIKE ?
                OR Resources.description LIKE ?
            )
        '''
        count_params.append(f'%{search_query}%')
        count_params.append(f'%{search_query}%')

    cursor.execute(count_query, count_params)

    total_posts = cursor.fetchone()[0]
    total_pages = math.ceil(total_posts / per_page) if total_posts > 0 else 1

    # ==============================
    # Main Resources Query
    # ==============================
    query = '''
        SELECT DISTINCT
            Resources.id,                                           -- res[0]
            Resources.title,                                        -- res[1]
            Resources.url,                                          -- res[2]
            Resources.description,                                  -- res[3]
            Resources.level,                                        -- res[4]
            Resources.view_count,                                   -- res[5]
            Users.username,                                         -- res[6]
            Resources.created_at,                                   -- res[7]

            (
                SELECT COUNT(*) 
                FROM Upvotes 
                WHERE Upvotes.resource_id = Resources.id
            ) AS like_count,                                        -- res[8]

            (
                SELECT COUNT(*)
                FROM Upvotes
                WHERE Upvotes.resource_id = Resources.id
                AND Upvotes.user_id = ?
            ) AS user_liked,                                        -- res[9]

            (
                SELECT COUNT(*)
                FROM Bookmarks
                WHERE Bookmarks.resource_id = Resources.id
                AND Bookmarks.user_id = ?
            ) AS user_saved,                                        -- res[10]

            (
                SELECT ROUND(COALESCE(AVG(rating), 0), 1)
                FROM Ratings 
                WHERE Ratings.resource_id = Resources.id
            ) AS avg_rating,                                        -- res[11]

            (
                SELECT COUNT(DISTINCT user_id) 
                FROM Ratings 
                WHERE Ratings.resource_id = Resources.id
            ) AS total_voters,                                      -- res[12]

            (
                SELECT rating 
                FROM Ratings 
                WHERE Ratings.resource_id = Resources.id 
                AND Ratings.user_id = ?
            ) AS user_rating                                        -- res[13]

        FROM Resources

        JOIN Users
            ON Resources.user_id = Users.id

        LEFT JOIN Resource_Categories
            ON Resources.id = Resource_Categories.resource_id

        WHERE Resources.is_deleted = 0
    '''
    params = [
        current_user_id,
        current_user_id,
        current_user_id
    ]

    # ==============================
    # Category Filter
    # ==============================
    if selected_cat_id:
        query += '''
            AND Resource_Categories.category_id = ?
        '''
        params.append(selected_cat_id)

    # ==============================
    # Search Filter
    # ==============================
    if search_query:
        query += '''
            AND (
                Resources.title LIKE ?
                OR Resources.description LIKE ?
            )
        '''

        params.append(f'%{search_query}%')
        params.append(f'%{search_query}%')

    # ==============================
    # Group By
    # ==============================
    query += '''
        GROUP BY Resources.id
    '''

    # ==============================
    # Sorting
    # ==============================
    if sort_by == 'popular':

        query += '''
            ORDER BY
                Resources.view_count DESC,
                like_count DESC
        '''

    else:

        query += '''
            ORDER BY
                Resources.created_at DESC
        '''

    # ==============================
    # Pagination
    # ==============================
    query += '''
        LIMIT ? OFFSET ?
    '''

    params.append(per_page)
    params.append(offset)

    cursor.execute(query, params)

    resources = cursor.fetchall()

    # ==========================================================
    # Comments + Replies
    # ==========================================================
    enhanced_resources = []

    for res in resources:

        res_id = res[0]

        # ==============================
        # Main Comments
        # parent_id IS NULL
        # ==============================
        cursor.execute('''
            SELECT
                Comments.comment_text,          -- comment[0]
                COALESCE(Users.username, 'Unknown') AS username, -- comment[1]
                COALESCE(Users.profile_pic, 'default.png') AS profile_pic, -- comment[2] (COALESCE ဖြုတ်လိုက်ပါ)
                Comments.created_at,            -- comment[3]
                Users.id,                       -- comment[4]
                Comments.id                     -- comment[5]
                                                   -- comment[5] (Comment ID)
            FROM Comments

            LEFT JOIN Users
                ON Comments.user_id = Users.id

            WHERE Comments.resource_id = ?
            AND Comments.parent_id IS NULL

            ORDER BY Comments.created_at ASC

        ''', (res_id,))

        main_comments = cursor.fetchall()

        comments_with_replies = []

        # ==============================
        # Replies for each comment
        # ==============================
        for comment in main_comments:

            comment_id = comment[5] # Comment ID ကို ယူပါသည်

            cursor.execute('''
                SELECT
                    Comments.comment_text,                         -- reply[0]
                    COALESCE(Users.username, 'Unknown') AS username, -- reply[1] (Username)
                    COALESCE(Users.profile_pic, 'default.png') AS profile_pic,    -- reply[2] (Profile Pic)
                    Comments.created_at,                            -- reply[3]
                    Users.id,                                       -- reply[4] (User ID)
                    Comments.id                                     -- reply[5] (Comment ID)
                FROM Comments

                LEFT JOIN Users
                    ON Comments.user_id = Users.id

                WHERE Comments.parent_id = ?

                ORDER BY Comments.created_at ASC

            ''', (comment_id,))

            replies = cursor.fetchall()

            # Main Comment + Replies -> (comment[0], comment[1], comment[2], comment[3], comment[4], comment[5], replies)
            comments_with_replies.append(
                comment + (replies,)
            )

        # res ထဲသို့ Comments များကို နောက်ဆုံး index အနေဖြင့် ပေါင်းထည့်ခြင်း
        enhanced_resources.append(
            res + (comments_with_replies,)
        )

    conn.close()  # <-- for res in resources: နဲ့ တစ်တန်းတည်း ဖြစ်ရပါမည် (Shift + Tab ၂ ချက်နှိပ်ပါ)

    # ==============================
    # AJAX Request
    # ==============================
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':

        return jsonify({
            'status': 'success',

            'html_content': render_template(
                'partials/resource_cards.html',

                resources=enhanced_resources,

                total_pages=total_pages,

                page=page,

                selected_cat_id=selected_cat_id,

                sort_by=sort_by
            ),

            'total_pages': total_pages,

            'current_page': page
        })

    # ==============================
    # Normal Page Load
    # ==============================
    return render_template(
        'index.html',

        categories=categories,

        resources=enhanced_resources,

        selected_cat_id=selected_cat_id,

        sort_by=sort_by,

        page=page,

        total_pages=total_pages
    )

@app.route('/add-comment/<int:resource_id>', methods=['POST'])
def add_comment(resource_id):
    if 'user_id' not in session:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'Login ဝင်ရန် လိုအပ်ပါသည်'}), 401
        return redirect(url_for('login'))

    user_id = session['user_id']
    username = session.get('username', 'Unknown')
    comment_text = request.form.get('comment_text', '').strip()
    parent_id = request.form.get('parent_id')

    if not comment_text:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'မှတ်ချက် စာသား ဗလာဖြစ်နေပါသည်'}), 400
        return redirect(request.referrer or url_for('index'))

    if parent_id:
        try:
            parent_id = int(parent_id)
        except ValueError:
            parent_id = None
    else:
        parent_id = None

    conn = None
    try:
        conn = sqlite3.connect(DATABASE, timeout=20)
        cursor = conn.cursor()

        # Reply ဖြစ်ပါက မူရင်း Comment ရှိ/မရှိ စစ်ဆေးခြင်း
        if parent_id is not None:
            cursor.execute("""
                SELECT id, user_id FROM Comments
                WHERE id = ? AND resource_id = ?
            """, (parent_id, resource_id))
            if not cursor.fetchone():
                return jsonify({'status': 'error', 'message': 'Reply ပြန်မည့် Comment မတွေ့ပါ'}), 404

        # Comment / Reply သိမ်းဆည်းခြင်း
        cursor.execute("""
            INSERT INTO Comments (resource_id, user_id, comment_text, parent_id)
            VALUES (?, ?, ?, ?)
        """, (resource_id, user_id, comment_text, parent_id))
        
        comment_id = cursor.lastrowid

        # Notification ပို့ရန် စစ်ဆေးခြင်း
        cursor.execute("SELECT user_id, title FROM Resources WHERE id = ?", (resource_id,))
        owner = cursor.fetchone()

        receiver_id = None
        notification_type = None

        if parent_id is not None:
            cursor.execute("SELECT user_id FROM Comments WHERE id = ?", (parent_id,))
            parent_comment = cursor.fetchone()
            if parent_comment:
                receiver_id = parent_comment[0]
                notification_type = "reply"
        elif owner:
            receiver_id = owner[0]
            notification_type = "comment"

        if receiver_id is not None and receiver_id != user_id:
            resource_title = owner[1] if owner else "your resource"
            message = (
                f"{username} replied to your comment on '{resource_title}'"
                if notification_type == "reply"
                else f"{username} commented on your resource '{resource_title}'"
            )

            cursor.execute("""
                INSERT INTO Notifications (sender_id, receiver_id, resource_id, type, message, is_read)
                VALUES (?, ?, ?, ?, ?, 0)
            """, (user_id, receiver_id, resource_id, notification_type, message))

        conn.commit()

        # Frontend အတွက် User Info (profile_pic ပါ) ပြန်လည်ယူခြင်း
        cursor.execute("""
            SELECT Users.username, Users.profile_pic, Comments.created_at
            FROM Comments
            JOIN Users ON Comments.user_id = Users.id
            WHERE Comments.id = ?
        """, (comment_id,))
        user_info = cursor.fetchone()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'status': 'success',
                'comment_id': comment_id,
                'parent_id': parent_id,
                'username': user_info[0] if user_info else username,
                'profile_pic': user_info[1] if (user_info and user_info[1]) else 'default.png',
                'created_at': user_info[2][:16] if (user_info and user_info[2]) else '',
                'comment_text': comment_text,
                'current_user': username
            })

        return redirect(request.referrer or url_for('index'))

    except Exception as e:
        if conn:
            conn.rollback()
        print("Add comment error:", e)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'Server error occurred'}), 500
        return redirect(request.referrer or url_for('index'))
    finally:
        if conn:
            conn.close()
            
@app.route('/delete-comment/<int:comment_id>', methods=['POST'])
def delete_comment(comment_id):
    user_id = session.get('user_id') 
    is_admin = session.get('is_admin', 0) 
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    if not user_id:
        if is_ajax:
            return jsonify({'status': 'error', 'message': 'မှတ်ချက်ဖျက်ရန် အရင်ဆုံး လော့ဂ်အင်ဝင်ပါရှင့်။ ❌'}), 401
        flash("မှတ်ချက်ဖျက်ရန် အရင်ဆုံး လော့ဂ်အင်ဝင်ပါရှင့်။ ❌", "danger")
        return redirect(url_for('login'))

    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()
    
    # Comment ရေးသူ ID နှင့် Post တင်သူ (Resource Owner) ID ကို ရှာခြင်း
    cursor.execute("""
        SELECT Comments.user_id, Resources.user_id 
        FROM Comments 
        JOIN Resources ON Comments.resource_id = Resources.id 
        WHERE Comments.id = ?
    """, (comment_id,))
    comment_data = cursor.fetchone()
    
    if comment_data:
        comment_author_id, resource_owner_id = comment_data
        
        # (၁) Comment/Reply ရေးသူ၊ (၂) Post ပိုင်ရှင် သို့မဟုတ် (၃) Admin ဖြစ်ပါက ဖျက်ခွင့်ပေးမည်
        if user_id == comment_author_id or user_id == resource_owner_id or is_admin == 1:
            # Comment ရော အောက်က Reply များပါ ပျက်သွားစေရန် OR parent_id ထည့်ထားပါသည်
            cursor.execute("DELETE FROM Comments WHERE id = ? OR parent_id = ?", (comment_id, comment_id))
            conn.commit()
            conn.close()
            
            if is_ajax:
                return jsonify({'status': 'success', 'message': 'မှတ်ချက်ကို အောင်မြင်စွာ ဖျက်လိုက်ပါပြီ။ ✨'})
                
            flash("မှတ်ချက်ကို အောင်မြင်စွာ ဖျက်လိုက်ပါပြီ။ ✨", "success")
            return redirect(request.headers.get('Referer', url_for('index')))
            
    conn.close()
    if is_ajax:
        return jsonify({'status': 'error', 'message': 'ဖျက်ပိုင်ခွင့် မရှိပါရှင့်။ ❌'}), 403
        
    flash("ဖျက်ပိုင်ခွင့် မရှိပါရှင့်။ ❌", "danger")
    return redirect(request.headers.get('Referer', url_for('index')))

@app.route("/rate-resource", methods=["POST"])
def rate_resource():
    # 1. Login စစ်ဆေးခြင်း
    if "user_id" not in session:
        return (
            jsonify({"status": "error", "message": "မဲပေးရန် Login ဝင်ပါ"}),
            401,
        )

    # 2. JSON Data ရယူခြင်း
    data = request.get_json(silent=True) or {}
    user_id = session["user_id"]
    resource_id = data.get("resource_id")
    rating = data.get("rating")

    # 3. Validation စစ်ဆေးခြင်း
    try:
        rating = int(rating)
        resource_id = int(resource_id)
    except (TypeError, ValueError):
        return (
            jsonify(
                {"status": "error", "message": "အချက်အလက် မမှန်ကန်ပါ (Invalid ID/Rating)"}
            ),
            400,
        )

    if not (1 <= rating <= 5):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Rating သည် 1 မှ 5 အတွင်း ဖြစ်ရပါမည်",
                }
            ),
            400,
        )

    # 4. Database Connection ဖွင့်ခြင်း
    db = sqlite3.connect(DATABASE, timeout=20)
    cursor = db.cursor()

    try:
        # Ratings Table ထဲသို့ Rating ထည့်ခြင်း (သို့) ပြင်ဆင်ခြင်း
        cursor.execute(
            """
            INSERT INTO Ratings (user_id, resource_id, rating)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, resource_id) DO UPDATE SET rating = excluded.rating
        """,
            (user_id, resource_id, rating),
        )

        db.commit()

        # 5. Average Rating နှင့် Total Voters ပြန်လည်တွက်ချက်ခြင်း
        cursor.execute(
            """
            SELECT AVG(rating), COUNT(rating)
            FROM Ratings
            WHERE resource_id = ?
        """,
            (resource_id,),
        )

        avg_res, count_res = cursor.fetchone()
        avg_rating = round(avg_res, 1) if avg_res else 0.0
        total_voters = count_res if count_res else 0

        db.close()

        return jsonify({
            "status": "success",
            "message": "Rating ပေးပြီးပါပြီ",
            "avg_rating": f"{avg_rating:.1f}",
            "total_voters": total_voters,
            "user_rating": rating,
        })

    except Exception as e:
        db.rollback()
        db.close()
        print(f"Rating Error: {e}")
        return (
            jsonify({
                "status": "error",
                "message": "Database အမှားတစ်ခု ဖြစ်ပေါ်နေပါသည်",
            }),
            500,
        )
    
@app.route('/my-saved')
def my_saved():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    current_user_id = session['user_id']
    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    
    query = '''
        SELECT Resources.id, Resources.title, Resources.url, Resources.description, 
               Resources.level, Resources.view_count, Users.username, Resources.created_at,
               COUNT(DISTINCT Upvotes.id) AS like_count,
               (SELECT COUNT(*) FROM Upvotes WHERE Upvotes.resource_id = Resources.id AND Upvotes.user_id = ?) AS user_liked,
               1 AS user_saved  
        FROM Resources
        JOIN Users ON Resources.user_id = Users.id
        JOIN Bookmarks ON Resources.id = Bookmarks.resource_id  
        LEFT JOIN Upvotes ON Resources.id = Upvotes.resource_id
        WHERE Bookmarks.user_id = ? AND Resources.is_deleted = 0
        GROUP BY Resources.id 
        ORDER BY Resources.id DESC  
    '''
    
    cursor.execute(query, [current_user_id, current_user_id])
    saved_resources = cursor.fetchall()
    conn.close()
    
    return render_template('saved.html', categories=categories, resources=saved_resources)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email'].strip()
        password = request.form['password']
        account_type = request.form['account_type']
        
        if (len(password) < 8 or 
            not re.search(r"[a-z]", password) or 
            not re.search(r"[A-Z]", password) or 
            not re.search(r"[0-9]", password)):
            flash("Password သည် အနည်းဆုံး ၈ လုံး ရှိရမည်ဖြစ်ပြီး စာလုံးကြီး (A-Z) နှင့် ဂဏန်း (0-9) အနည်းဆုံး တစ်လုံးစီ ပါဝင်ရပါမည်။ ❌", "danger")
            return render_template('register.html')
            
        hashed_password = generate_password_hash(password)
        is_admin_value = 1 if email == 'nyeinnyeinei1705@gmail.com' else 0
        
        try:
            conn = sqlite3.connect(DATABASE, timeout=20)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO Users (username, email, password, account_type, is_admin)
                VALUES (?, ?, ?, ?, ?)
            ''', (username, email, hashed_password, account_type, is_admin_value))
            conn.commit()
            conn.close()
            flash("အကောင့်ဖွင့်ခြင်း အောင်မြင်ပါသည်! လော့ဂ်အင်ဝင်နိုင်ပါပြီ။ 🎉", "success")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("စိတ်မကောင်းပါဘူး... ဒီ Email နဲ့ အကောင့်ဖွင့်ထားပြီးသား ရှိနေပါတယ်ရှင့်။ ❌", "danger")
            return render_template('register.html')
            
    return render_template('register.html')
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password']
        
        conn = sqlite3.connect(DATABASE, timeout=20)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM Users WHERE email = ?', (email,))
        user = cursor.fetchone()
        conn.close()
        
        if user and check_password_hash(user[3], password):
            # ⛔ 1. Banned Account ဟုတ်မဟုတ် စစ်ဆေးခြင်း
            conn_check = sqlite3.connect(DATABASE)
            c = conn_check.cursor()
            c.execute("SELECT is_banned FROM Users WHERE id = ?", (user[0],))
            banned_status = c.fetchone()
            conn_check.close()
            
            if banned_status and banned_status[0] == 1:
                flash("သင့်အကောင့်မှာ ပိတ်ပင် (Ban) ခံထားရပါသဖြင့် Login ဝင်၍မရပါ။ ❌", "danger")
                return render_template('login.html')

            # 🟢 2. Normal Login Flow (Session များ သတ်မှတ်ခြင်း)
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['is_admin'] = user[6]
            
            # 💡 role ကိုပါ session ထဲ အလိုအလျောက် သတ်မှတ်ပေးခြင်း
            if user[6] == 1 or user[1] == 'Nyein Nyein Ei':
                session['role'] = 'admin'
            else:
                session['role'] = 'user'
                
            return redirect(url_for('index'))
        else:
            flash("Email သို့မဟုတ် Password မှားယွင်းနေပါတယ်ရှင့်။ ❌", "danger")
            return render_template('login.html')
            
    return render_template('login.html')

@app.route('/share', methods=['GET', 'POST'])
def share_resource():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        title = request.form['title']
        url = request.form['url']
        description = request.form['description']
        level = request.form['level']
        category_id = int(request.form['category_id'])
        user_id = session['user_id']
        
        conn = sqlite3.connect(DATABASE, timeout=20)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO Resources (title, url, description, level, user_id)
                VALUES (?, ?, ?, ?, ?)
            ''', (title, url, description, level, user_id))
            resource_id = cursor.lastrowid
            cursor.execute('''
                INSERT INTO Resource_Categories (resource_id, category_id)
                VALUES (?, ?)
            ''', (resource_id, category_id))
            conn.commit()
            flash("Resource အသစ်ကို အောင်မြင်စွာ မျှဝေလိုက်ပါပြီ။ 🎉", "success")
        except Exception as e:
            print(f"Error occurred: {e}")
            conn.rollback()
        finally:
            conn.close()
            
        return redirect(url_for('index'))
    return redirect(url_for('index'))

@app.route('/open-link/<int:resource_id>')
def open_link(resource_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()
    cursor.execute('UPDATE Resources SET view_count = view_count + 1 WHERE id = ?', (resource_id,))
    cursor.execute('SELECT url FROM Resources WHERE id = ?', (resource_id,))
    result = cursor.fetchone()
    conn.commit()
    conn.close()
    
    if result:
        return redirect(result[0])
    else:
        return "Resource not found", 404
    
@app.route('/like/<int:resource_id>', methods=['POST'])
def like_resource(resource_id):
    if 'user_id' not in session:
        return {"status": "error", "message": "Unauthorized"}, 401
        
    user_id = session['user_id']
    username = session.get('username', 'Someone')
    
    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()
    
    # Resource ပိုင်ရှင်နှင့် Title ကို ရှာခြင်း
    cursor.execute('SELECT user_id, title FROM Resources WHERE id = ?', (resource_id,))
    owner = cursor.fetchone()
    
    cursor.execute('SELECT id FROM Upvotes WHERE user_id = ? AND resource_id = ?', (user_id, resource_id))
    like_exists = cursor.fetchone()
    
    if like_exists:
        cursor.execute('DELETE FROM Upvotes WHERE user_id = ? AND resource_id = ?', (user_id, resource_id))
        is_liked = False
    else:
        cursor.execute('INSERT INTO Upvotes (user_id, resource_id) VALUES (?, ?)', (user_id, resource_id))
        is_liked = True
        
        # 🔔 Notification ထည့်သွင်းခြင်း (မိမိကိုယ်တိုင် Like ပေးပါက နိုတီမသွားစေရ)
        if owner and owner[0] != user_id:
            message = f"{username} liked your resource '{owner[1]}'"
            cursor.execute("""
                INSERT INTO Notifications (sender_id, receiver_id, resource_id, type, message, is_read)
                VALUES (?, ?, ?, 'like', ?, 0)
            """, (user_id, owner[0], resource_id, message))
        
    conn.commit()
    cursor.execute('SELECT COUNT(id) FROM Upvotes WHERE resource_id = ?', (resource_id,))
    total_likes = cursor.fetchone()[0]
    conn.close()
    
    return {
        "status": "success", 
        "liked": is_liked, 
        "like_count": total_likes
    }

@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()

    try:
        # Notification များကို ယူခြင်း (Notifications.is_read ကို Index 5 အဖြစ် ထည့်ယူခြင်း)
        cursor.execute("""
            SELECT
                Notifications.id,
                Notifications.message,
                Notifications.type,
                Notifications.resource_id,
                Notifications.created_at,
                Notifications.is_read,
                Users.username
            FROM Notifications
            JOIN Users
                ON Notifications.sender_id = Users.id
            WHERE Notifications.receiver_id = ?
            ORDER BY Notifications.created_at DESC
        """, (session['user_id'],))

        notifications = cursor.fetchall()

        # ဖတ်ပြီးသားအဖြစ် ပြောင်းခြင်း
        cursor.execute("""
            UPDATE Notifications
            SET is_read = 1
            WHERE receiver_id = ?
            AND is_read = 0
        """, (session['user_id'],))

        conn.commit()

    except Exception as e:
        conn.rollback()
        print("Notification error:", e)
        notifications = []

    finally:
        conn.close()

    return render_template(
        "notifications.html",
        notifications=notifications
    )

# 🔍 Resource Detail Route
@app.route('/resource/<int:resource_id>')
def resource_detail(resource_id):
    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()

    try:
        # 1. Resource ရှာမယ်
        cursor.execute("SELECT * FROM Resources WHERE id = ? AND is_deleted = 0", (resource_id,))
        resource = cursor.fetchone()

        if not resource:
            return "Resource Not Found", 404

        # 2. Main Comments များ ရှာမယ် (parent_id IS NULL)
        cursor.execute('''
            SELECT
                Comments.comment_text,                         -- comment[0]
                COALESCE(Users.username, 'Unknown') AS username, -- comment[1]
                COALESCE(Users.profile_pic, 'default.png'),    -- comment[2]
                Comments.created_at,                            -- comment[3]
                Users.id,                                       -- comment[4]
                Comments.id                                     -- comment[5]
            FROM Comments
            LEFT JOIN Users ON Comments.user_id = Users.id
            WHERE Comments.resource_id = ? AND Comments.parent_id IS NULL
            ORDER BY Comments.created_at ASC
        ''', (resource_id,))
        main_comments = cursor.fetchall()

        comments_with_replies = []

        # 3. Replies များ ရှာမယ်
        for comment in main_comments:
            comment_id = comment[5]
            cursor.execute('''
                SELECT
                    Comments.comment_text,                         -- reply[0]
                    COALESCE(Users.username, 'Unknown') AS username, -- reply[1]
                    COALESCE(Users.profile_pic, 'default.png'),    -- reply[2]
                    Comments.created_at,                            -- reply[3]
                    Users.id,                                       -- reply[4]
                    Comments.id                                     -- reply[5]
                FROM Comments
                LEFT JOIN Users ON Comments.user_id = Users.id
                WHERE Comments.parent_id = ?
                ORDER BY Comments.created_at ASC
            ''', (comment_id,))
            replies = cursor.fetchall()
            comments_with_replies.append(comment + (replies,)) # comment[6] = replies

        return render_template('partials/resource_detail.html', resource=resource, comments=comments_with_replies)
    finally:
        conn.close()

# 💬 Comment / Reply အသစ် ထည့်သွင်းသည့် Route
@app.route('/add-comment/<int:resource_id>', methods=['POST'])
def add_reply(resource_id):
    if 'user_id' not in session:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'ကျေးဇူးပြု၍ Login အရင်ဝင်ပါ'}), 401
        return redirect(url_for('login'))

    user_id = session['user_id']
    username = session.get('username', 'Unknown')
    comment_text = request.form.get('comment_text', '').strip()
    parent_id = request.form.get('parent_id', type=int)

    if not comment_text:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'မှတ်ချက် စာသား ရေးသားပေးပါ'}), 400
        return redirect(request.referrer)

    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO Comments (resource_id, user_id, comment_text, parent_id)
        VALUES (?, ?, ?, ?)
    ''', (resource_id, user_id, comment_text, parent_id))
    
    conn.commit()
    cursor.execute('SELECT created_at FROM Comments WHERE id = last_insert_rowid()')
    created_at = cursor.fetchone()[0]
    conn.close()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'status': 'success',
            'username': username,
            'comment_text': comment_text,
            'created_at': created_at[:16] if created_at else ''
        })

    return redirect(request.referrer or url_for('index'))

@app.route('/save/<int:resource_id>', methods=['POST'])
def save_resource(resource_id):
    if 'user_id' not in session:
        return {"status": "error", "message": "Unauthorized"}, 401
        
    user_id = session['user_id']
    username = session.get('username', 'Someone')
    
    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()
    
    # Resource ပိုင်ရှင်နှင့် Title ကို ရှာခြင်း
    cursor.execute('SELECT user_id, title FROM Resources WHERE id = ?', (resource_id,))
    owner = cursor.fetchone()
    
    cursor.execute('SELECT id FROM Bookmarks WHERE user_id = ? AND resource_id = ?', (user_id, resource_id))
    bookmark_exists = cursor.fetchone()
    
    if bookmark_exists:
        cursor.execute('DELETE FROM Bookmarks WHERE user_id = ? AND resource_id = ?', (user_id, resource_id))
        is_saved = False
    else:
        cursor.execute('INSERT INTO Bookmarks (user_id, resource_id) VALUES (?, ?)', (user_id, resource_id))
        is_saved = True
        
        # 🔔 Notification ထည့်သွင်းခြင်း (မိမိကိုယ်တိုင် Save ပါက နိုတီမသွားစေရ)
        if owner and owner[0] != user_id:
            message = f"{username} saved your resource '{owner[1]}'"
            cursor.execute("""
                INSERT INTO Notifications (sender_id, receiver_id, resource_id, type, message, is_read)
                VALUES (?, ?, ?, 'save', ?, 0)
            """, (user_id, owner[0], resource_id, message))
        
    conn.commit()
    conn.close()
    
    return {
        "status": "success", 
        "saved": is_saved
    }

# ---------------- PROFILE ROUTE ----------------
@app.route('/profile')
def profile():
  if 'user_id' not in session:
    return redirect(url_for('login'))

  current_user_id = session['user_id']
  conn = sqlite3.connect(DATABASE, timeout=20)
  cursor = conn.cursor()

  cursor.execute(
      'SELECT profile_pic FROM Users WHERE id = ?', (current_user_id,)
  )
  user_pic_result = cursor.fetchone()
  user_pic = (
      user_pic_result[0]
      if user_pic_result and user_pic_result[0]
      else 'default.png'
  )

  cursor.execute(
      '''
        SELECT COUNT(Upvotes.id) 
        FROM Upvotes 
        JOIN Resources ON Upvotes.resource_id = Resources.id
        WHERE Resources.user_id = ? AND Resources.is_deleted = 0
    ''',
      (current_user_id,),
  )
  total_likes_received = cursor.fetchone()[0] or 0

  cursor.execute(
      '''
        SELECT Resources.id, Resources.title, Resources.url, Resources.description, 
               Resources.level, Resources.view_count, 
               COUNT(DISTINCT Upvotes.id) AS like_count,
               (SELECT COUNT(*) FROM Bookmarks WHERE Bookmarks.resource_id = Resources.id AND Bookmarks.user_id = ?) AS user_saved
        FROM Resources
        LEFT JOIN Upvotes ON Resources.id = Upvotes.resource_id
        WHERE Resources.user_id = ? AND Resources.is_deleted = 0
        GROUP BY Resources.id
        ORDER BY Resources.created_at DESC
    ''',
      (current_user_id, current_user_id),
  )
  my_resources = cursor.fetchall()

  cursor.execute(
      '''
        SELECT Comments.id, Comments.comment_text, Comments.created_at, Resources.title, Resources.id
        FROM Comments
        JOIN Resources ON Comments.resource_id = Resources.id
        WHERE Comments.user_id = ? AND Resources.is_deleted = 0
        ORDER BY Comments.created_at DESC
    ''',
      (current_user_id,),
  )
  my_comments = cursor.fetchall()

  conn.close()

  return render_template(
      'profile.html',
      total_likes=total_likes_received,
      resources=my_resources,
      user_pic=user_pic,
      my_comments=my_comments,
  )

@app.route('/logout')
def logout():
    session.clear()
    flash("လော့ဂ်အောက် လုပ်ပြီးပါပြီ။ 👋", "success")
    return redirect(url_for('login'))

# ---------------- UPLOAD PROFILE PIC ROUTE ----------------
@app.route('/upload-profile-pic', methods=['POST'])
def upload_profile_pic():
  if 'user_id' not in session:
    return redirect(url_for('login'))

  current_user_id = session['user_id']
  if 'profile_pic' not in request.files:
    flash('ပုံ ရွေးချယ်မှု မရှိပါ❌', 'danger')
    return redirect(url_for('profile'))

  file = request.files['profile_pic']
  if file.filename == '':
    flash('ကျေးဇူးပြု၍ ပုံ ရွေးချယ်ပေးပါရန်။', 'warning')
    return redirect(url_for('profile'))

  if file:
    filename = secure_filename(file.filename)
    unique_filename = f'{current_user_id}_{filename}'

    # Upload Folder မရှိသေးရင် အလိုအလျောက် ဆောက်ပေးခြင်း
    upload_folder = app.config.get('UPLOAD_FOLDER', 'static/uploads/profile_pics')
    os.makedirs(upload_folder, exist_ok=True)

    file.save(os.path.join(upload_folder, unique_filename))

    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE Users SET profile_pic = ? WHERE id = ?',
        (unique_filename, current_user_id),
    )
    conn.commit()
    conn.close()
    flash('Profile ပုံကို အောင်မြင်စွာ ပြောင်းလဲလိုက်ပါပြီ။ ✨', 'success')

  return redirect(url_for('profile'))

# ---------------- REMOVE PROFILE PIC ROUTE ----------------
@app.route('/remove-profile-pic', methods=['POST'])
def remove_profile_pic():
  if 'user_id' not in session:
    return redirect(url_for('login'))

  current_user_id = session['user_id']
  conn = sqlite3.connect(DATABASE, timeout=20)
  cursor = conn.cursor()

  cursor.execute(
      'SELECT profile_pic FROM Users WHERE id = ?', (current_user_id,)
  )
  row = cursor.fetchone()
  current_pic = row[0] if row else None

  if current_pic and current_pic != 'default.png':
    upload_folder = app.config.get('UPLOAD_FOLDER', 'static/uploads/profile_pics')
    file_path = os.path.join(upload_folder, current_pic)
    if os.path.exists(file_path):
      os.remove(file_path)

  cursor.execute(
      'UPDATE Users SET profile_pic = "default.png" WHERE id = ?',
      (current_user_id,),
  )
  conn.commit()
  conn.close()
  flash('Profile ပုံကို ဖယ်ရှားလိုက်ပါပြီ။', 'success')

  return redirect(url_for('profile'))

# ---------------- EDIT PROFILE ROUTE ----------------
@app.route('/edit-profile', methods=['POST'])
def edit_profile():
  if 'user_id' not in session:
    return redirect(url_for('login'))

  current_user_id = session['user_id']
  new_username = request.form['username'].strip()

  if not new_username:
    flash('Username သည် အလွတ်မဖြစ်ရပါ❌', 'danger')
    return redirect(url_for('profile'))

  conn = sqlite3.connect(DATABASE, timeout=20)
  cursor = conn.cursor()

  try:
    cursor.execute(
        'UPDATE Users SET username = ? WHERE id = ?',
        (new_username, current_user_id),
    )
    conn.commit()
    session['username'] = new_username
    flash('Profile အချက်အလက် ပြင်ဆင်ပြီးပါပြီ။ ✨', 'success')
  except sqlite3.IntegrityError:
    flash(
        'ဤ Username ကို အခြားသူတစ်ဦး အသုံးပြုထားပြီးဖြစ်ပါသည်❌', 'danger'
    )
  finally:
    conn.close()

  return redirect(url_for('profile'))

@app.route('/delete-resource/<int:resource_id>', methods=['POST'])
def delete_resource(resource_id):
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Login ဝင်ရန် လိုအပ်ပါသည်'}), 401
        
    current_user_id = session['user_id']
    is_admin = session.get('is_admin', 0)
    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT user_id FROM Resources WHERE id = ? AND is_deleted = 0', (resource_id,))
        resource = cursor.fetchone()
        
        if resource and (resource[0] == current_user_id or is_admin == 1):
            cursor.execute('UPDATE Resources SET is_deleted = 1 WHERE id = ?', (resource_id,))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Resource ကို ဖျက်သိမ်းလိုက်ပါပြီ။ ✨'})
        else:
            return jsonify({'status': 'error', 'message': 'ဤအကြောင်းအရာအား ဖျက်ခွင့်မရှိပါ သို့မဟုတ် မရှိတော့ပါရှင့်။ ❌'}), 403
    finally:
        conn.close()  # 🛡️ Error တက်တက်၊ မတက်တက် Connection သေချာပေါက် အမြဲပိတ်မည်

@app.route('/api/search')
def api_search():
    if 'user_id' not in session:
        return {"error": "Unauthorized"}, 401
        
    current_user_id = session['user_id']
    search_query = request.args.get('search', type=str, default='').strip()
    
    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()
    
    query = '''
        SELECT Resources.id, Resources.title, Resources.url, Resources.description, 
               Resources.level, Resources.view_count, Users.username, Resources.created_at,
               COUNT(DISTINCT Upvotes.id) AS like_count
        FROM Resources
        JOIN Users ON Resources.user_id = Users.id
        WHERE (Resources.title LIKE ? OR Resources.description LIKE ?) AND Resources.is_deleted = 0
        GROUP BY Resources.id
        ORDER BY Resources.created_at DESC
    '''
    
    cursor.execute(query, (f'%{search_query}%', f'%{search_query}%'))
    resources = cursor.fetchall()
    conn.close()
    
    results = []
    for res in resources:
        results.append({
            "id": res[0],
            "title": res[1],
            "url": res[2],
            "description": res[3],
            "level": res[4],
            "view_count": res[5],
            "username": res[6],
            "created_at": res[7],
            "like_count": res[8]
        })
        
    return {"resources": results}

@app.route('/api/extract-meta', methods=['POST'])
def extract_meta():
    data = request.get_json()
    url = data.get('url')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
        
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code != 200:
            return jsonify({'error': 'Cannot fetch URL'}), 400
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title_tag = soup.find('meta', property='og:title') or soup.find('meta', name='title')
        title = title_tag['content'] if title_tag else (soup.title.string if soup.title else "No Title Found")
        
        image_tag = soup.find('meta', property='og:image') or soup.find('meta', name='image')
        image_url = image_tag['content'] if image_tag else ""
        
        return jsonify({
            'title': title.strip(),
            'image_url': image_url
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ---------------------------------------------------------
# ⚡ DEVHUB ADMIN DASHBOARD & MANAGEMENT ROUTES
# ---------------------------------------------------------
@app.route('/admin')
def admin_dashboard():
    # 🔐 Admin Access Security Check (is_admin နှင့် role နှစ်ခုလုံးကို စစ်ဆေးခြင်း)
    if 'user_id' not in session:
        flash('ကျေးဇူးပြု၍ အရင်ဆုံး Login ဝင်ပေးပါ။', 'warning')
        return redirect(url_for('login'))
        
    is_admin_user = session.get('is_admin') == 1 or session.get('role') == 'admin' or session.get('username') == 'Nyein Nyein Ei'
    
    if not is_admin_user:
        flash('ဤစာမျက်နှာကို ဝင်ရောက်ကြည့်ရှုရန် ခွင့်ပြုချက်မရှိပါ။ (Admin Only)', 'danger')
        return redirect(url_for('index'))

    # 📊 Database Logic
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM Users")
    users = cursor.fetchall()

    cursor.execute("""
        SELECT Resources.id, Resources.title, Users.username, 
               Categories.name as category_name, Resources.views, Resources.rating
        FROM Resources
        LEFT JOIN Users ON Resources.user_id = Users.id
        LEFT JOIN Categories ON Resources.category_id = Categories.id
        ORDER BY Resources.id DESC
    """)
    resources = cursor.fetchall()
    
    resource_list = []
    for res in resources:
        resource_list.append({
            'id': res[0],
            'title': res[1],
            'author_name': res[2] if res[2] else 'Unknown',
            'category_name': res[3] if res[3] else 'General',
            'views': res[4] if res[4] else 0,
            'rating': res[5] if res[5] else 0.0
        })

    cursor.execute("SELECT COUNT(*) FROM Comments")
    total_comments = cursor.fetchone()[0]

    cursor.execute("""
        SELECT Categories.name, COUNT(Resources.id) as post_count
        FROM Categories
        LEFT JOIN Resources ON Categories.id = Resources.category_id
        GROUP BY Categories.id
    """)
    cat_stats_raw = cursor.fetchall()
    category_stats = [{'name': row[0], 'count': row[1]} for row in cat_stats_raw]

    conn.close()

    return render_template('admin.html', 
                           users=users, 
                           resources=resource_list, 
                           total_comments=total_comments, 
                           category_stats=category_stats)

@app.route('/admin/resource/delete/<int:res_id>', methods=['POST'])
def admin_delete_resource(res_id):
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 403
        
    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM Resources WHERE id = ?", (res_id,))
        cursor.execute("DELETE FROM Comments WHERE resource_id = ?", (res_id,))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

# ---------------------------------------------------------
# 👥 ADMIN USER MANAGEMENT ROUTES
# ---------------------------------------------------------

@app.route('/admin/users')
def admin_users():
    if 'user_id' not in session or not session.get('is_admin'):
        flash("Unauthorized access!", "danger")
        return redirect(url_for('index'))
    
    conn = sqlite3.connect(DATABASE, timeout=20)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # User များ၏ အချက်အလက်များနှင့် တင်ထားသော Resource အရေအတွက်ကို တစ်ခါတည်း JOIN ဆွဲခြင်း
    cursor.execute("""
        SELECT Users.*, COUNT(Resources.id) AS total_posts 
        FROM Users 
        LEFT JOIN Resources ON Users.id = Resources.user_id 
        GROUP BY Users.id
        ORDER BY Users.id DESC
    """)
    users = cursor.fetchall()
    conn.close()

    return render_template('admin_users.html', users=users)


@app.route('/admin/user/toggle_admin/<int:u_id>', methods=['POST'])
def toggle_admin_role(u_id):
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    # မိမိကိုယ်တိုင်၏ Admin Status ကို ပြန်ဖျက်မရအောင် ကာကွယ်ခြင်း
    if u_id == session.get('user_id'):
        return jsonify({'success': False, 'message': 'You cannot revoke your own admin rights!'}), 400

    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()
    
    try:
        # လက်ရှိ Role ကို စစ်ဆေးပြီး ပြောင်းပြန်လှန်ခြင်း (0 -> 1, 1 -> 0)
        cursor.execute("SELECT is_admin FROM Users WHERE id = ?", (u_id,))
        user = cursor.fetchone()
        if user:
            new_role = 0 if user[0] == 1 else 1
            cursor.execute("UPDATE Users SET is_admin = ? WHERE id = ?", (new_role, u_id))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'new_role': new_role})
        
        conn.close()
        return jsonify({'success': False, 'message': 'User not found'}), 404
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

# ---------------------------------------------------------
# 💬 ADMIN COMMENT MANAGEMENT ROUTES
# ---------------------------------------------------------

@app.route('/admin/comments')
def admin_comments():
    if 'user_id' not in session or not session.get('is_admin'):
        flash("Unauthorized access!", "danger")
        return redirect(url_for('index'))
    
    conn = sqlite3.connect(DATABASE, timeout=20)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # comment_text AS content ဟု ပေးထားသဖြင့် HTML တွင် c.content ဖြင့် ယူသုံးနိုင်ပါသည်
    cursor.execute("""
        SELECT 
            Comments.id,
            Comments.comment_text AS content,
            Comments.created_at,
            Users.username AS author_name,
            Resources.title AS resource_title,
            Resources.id AS resource_id
        FROM Comments
        JOIN Users ON Comments.user_id = Users.id
        JOIN Resources ON Comments.resource_id = Resources.id
        ORDER BY Comments.id DESC
    """)
    comments = cursor.fetchall()
    conn.close()

    return render_template('admin_comments.html', comments=comments)

@app.route('/admin/comment/delete/<int:c_id>', methods=['POST'])
def delete_comment_by_admin(c_id):
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM Comments WHERE id = ?", (c_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/toggle_ban/<int:user_id>', methods=['POST'])
def toggle_ban(user_id):
    # 🔐 Admin Auth Check
    if session.get('role') != 'admin' and not session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # လက်ရှိ Ban Status ကို ရယူခြင်း
    cursor.execute("SELECT is_banned FROM Users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    if user:
        # Status ပြောင်းလဲခြင်း (1 ဖြစ်ရင် 0 ၊ 0 ဖြစ်ရင် 1 ပြောင်းမည်)
        new_status = 0 if user[0] == 1 else 1
        cursor.execute("UPDATE Users SET is_banned = ? WHERE id = ?", (new_status, user_id))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'new_status': new_status})
    
    conn.close()
    return jsonify({'success': False, 'message': 'User not found'}), 404

@app.route('/admin/categories', methods=['GET', 'POST'])
def admin_categories():
    if 'user_id' not in session or (session.get('role') != 'admin' and not session.get('is_admin')):
        flash("Unauthorized access!", "danger")
        return redirect(url_for('index'))
    
    conn = sqlite3.connect(DATABASE, timeout=20)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if request.method == 'POST':
        category_name = request.form.get('category_name', '').strip()
        if category_name:
            try:
                cursor.execute("INSERT INTO Categories (name) VALUES (?)", (category_name,))
                conn.commit()
                flash("Category အသစ် ထည့်သွင်းပြီးပါပြီ။ 🟢", "success")
            except sqlite3.IntegrityError:
                flash("ဤ Category နာမည်မှာ ရှိပြီးသား ဖြစ်နေပါသည်။ ❌", "warning")
        return redirect(url_for('admin_categories'))

    cursor.execute("SELECT Categories.*, COUNT(Resources.id) as resource_count FROM Categories LEFT JOIN Resources ON Categories.name = Resources.category GROUP BY Categories.id")
    categories = cursor.fetchall()
    conn.close()
    
    return render_template('admin_categories.html', categories=categories)

@app.route('/admin/delete_category/<int:cat_id>', methods=['POST'])
def delete_category(cat_id):
    if 'user_id' not in session or (session.get('role') != 'admin' and not session.get('is_admin')):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    conn = sqlite3.connect(DATABASE, timeout=20)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM Categories WHERE id = ?", (cat_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

if __name__ == '__main__':
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("UPDATE Users SET is_admin = 1 WHERE email = 'nyeinnyeinei1705@gmail.com'")
        conn.commit()
        conn.close()
        print("Admin promotion check: Success! ✨")
    except Exception as e:
        print(f"Admin promotion note: {e}")

    app.run(debug=True)