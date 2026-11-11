from flask import Flask, render_template, request, redirect, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
import os
import uuid

app = Flask(__name__)
app.secret_key = os.urandom(32)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def database():
    conn = sqlite3.connect('instagram.db')
    conn.row_factory = sqlite3.Row
    return conn

def create_database():
    conn = database()

    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,   password TEXT NOT NULL, profile_pic TEXT )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            UNIQUE(user_id, post_id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(post_id) REFERENCES posts(id)
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(post_id) REFERENCES posts(id)
        )
    ''')
    columns = [row['name'] for row in conn.execute('PRAGMA table_info(users)').fetchall()]

    if 'profile_pic' not in columns:
        conn.execute('ALTER TABLE users ADD COLUMN profile_pic TEXT')

    if 'email' not in columns:
        conn.execute('ALTER TABLE users ADD COLUMN email TEXT')

    conn.commit()
    conn.close()

create_database()
@app.route('/upload_profile_pic', methods=['POST'])
def upload_profile_pic():
    if 'username' not in session:
        return redirect('/login')

    photo = request.files.get('profile_pic')

    if photo and photo.filename:
        extension = os.path.splitext(
            secure_filename(photo.filename)
        )[1].lower()

        if extension not in ['.jpg', '.jpeg', '.png', '.webp']:
            return 'Please upload a JPG, PNG, or WEBP image.'

        filename = 'profile_' + uuid.uuid4().hex + extension

        photo.save(os.path.join(UPLOAD_FOLDER, filename))

        conn = database()
        conn.execute(
            'UPDATE users SET profile_pic = ? WHERE username = ?',
            (filename, session['username'])
        )
        conn.commit()
        conn.close()

    return redirect('/profile')
@app.route('/')
def home():
    conn = database()

    posts = conn.execute('''
        SELECT
            posts.id,
            posts.filename,
            users.username,
            (SELECT COUNT(*) FROM likes
             WHERE likes.post_id = posts.id) AS like_count,
            (SELECT COUNT(*) FROM comments
             WHERE comments.post_id = posts.id) AS comment_count
        FROM posts
        JOIN users ON posts.user_id = users.id
        ORDER BY posts.id DESC
    ''').fetchall()

    posts = [dict(post) for post in posts]

    for post in posts:
        post['comments'] = conn.execute('''
            SELECT users.username, comments.content
            FROM comments
            JOIN users ON comments.user_id = users.id
            WHERE comments.post_id = ?
            ORDER BY comments.id ASC
        ''', (post['id'],)).fetchall()

    user = None
    if session.get('username'):
        user = conn.execute(
            'SELECT profile_pic FROM users WHERE username = ?',
            (session.get('username'),)
        ).fetchone()

    profile_pic = user['profile_pic'] if user else None

    conn.close()

    return render_template(
        'index.html',
        posts=posts,
        username=session.get('username'),
        profile_pic=profile_pic
    )

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not username or len(username) > 30:
            return 'Invalid username.'

        if '@' not in email or '.' not in email.split('@')[-1]:
            return 'Please enter a valid email address.'

        if len(password) < 8:
            return 'Password must contain at least 8 characters.'

        conn = database()

        existing = conn.execute(
            'SELECT id FROM users WHERE username = ? OR email = ?',
            (username, email)
        ).fetchone()

        if existing:
            conn.close()
            return 'Username or email already exists.'

        conn.execute(
            'INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
            (username, email, generate_password_hash(password))
        )

        conn.commit()
        conn.close()

        return redirect('/login')

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        conn = database()

        user = conn.execute(
            'SELECT * FROM users WHERE username = ? OR email = ?',
            (identifier, identifier.lower())
        ).fetchone()

        conn.close()

        if user and check_password_hash(user['password'], password):
            session.clear()
            session['username'] = user['username']
            return redirect('/')

        return 'Incorrect username/email or password.'

    return render_template('login.html')
@app.route('/like/<int:post_id>', methods=['POST'])
def like_post(post_id):
    if 'username' not in session:
        return redirect('/login')

   

    conn = database()

    user = conn.execute(
        'SELECT id FROM users WHERE username = ?',
        (session['username'],)
    ).fetchone()

    if not user:
        conn.close()
        return redirect('/login')

    existing_like = conn.execute(
        'SELECT id FROM likes WHERE user_id = ? AND post_id = ?',
        (user['id'], post_id)
    ).fetchone()

    if existing_like:
        conn.execute(
            'DELETE FROM likes WHERE user_id = ? AND post_id = ?',
            (user['id'], post_id)
        )
    else:
        conn.execute(
            'INSERT INTO likes (user_id, post_id) VALUES (?, ?)',
            (user['id'], post_id)
        )

    conn.commit()
    conn.close()

    return redirect('/')
@app.route('/comment/<int:post_id>', methods=['POST'])
def add_comment(post_id):
    if 'username' not in session:
        return redirect('/login')

    content = request.form.get('content', '').strip()

    if not content:
        return redirect('/')

    if len(content) > 1000:
        return 'Comment is too long.'

    conn = database()

    user = conn.execute(
        'SELECT id FROM users WHERE username = ?',
        (session['username'],)
    ).fetchone()

    post = conn.execute(
        'SELECT id FROM posts WHERE id = ?',
        (post_id,)
    ).fetchone()

    if user and post:
        conn.execute(
            'INSERT INTO comments (user_id, post_id, content) VALUES (?, ?, ?)',
            (user['id'], post_id, content)
        )
        conn.commit()

    conn.close()
    return redirect('/')
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/upload', methods=['POST'])
def upload():
    if 'username' not in session:
        return redirect('/login')

    photo = request.files.get('photo')

    if photo and photo.filename:
        original_name = secure_filename(photo.filename)

        if original_name:
            extension = os.path.splitext(original_name)[1].lower()
            filename = str(uuid.uuid4()) + extension

            conn = database()
            user = conn.execute(
                'SELECT id FROM users WHERE username = ?',
                (session['username'],)
            ).fetchone()

            if user:
                photo.save(os.path.join(UPLOAD_FOLDER, filename))
                conn.execute(
                    'INSERT INTO posts (user_id, filename) VALUES (?, ?)',
                    (user['id'], filename)
                )
                conn.commit()

            conn.close()

    return redirect('/')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/profile')
def profile():
    if 'username' not in session:
        return redirect('/login')

    conn = database()

    user = conn.execute(
    'SELECT id, username, profile_pic FROM users WHERE username = ?',
    (session['username'],)
).fetchone()

    user_posts = conn.execute(
        'SELECT filename FROM posts WHERE user_id = ? ORDER BY id DESC',
        (user['id'],)
    ).fetchall()

    post_count = len(user_posts)

    conn.close()

    return render_template(
        'profile.html',
        profile_username=user['username'],
        profile_pic=user['profile_pic'],
        user_posts=user_posts,
        post_count=post_count
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
