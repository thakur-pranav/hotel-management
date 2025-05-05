from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_mysqldb import MySQL
from functools import wraps
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
from config import DB_CONFIG, SECRET_KEY, UPLOAD_FOLDER, ALLOWED_EXTENSIONS
import MySQLdb.cursors

app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = SECRET_KEY
app.config['MYSQL_HOST'] = DB_CONFIG['host']
app.config['MYSQL_USER'] = DB_CONFIG['user']
app.config['MYSQL_PASSWORD'] = DB_CONFIG['password']
app.config['MYSQL_DB'] = DB_CONFIG['db']
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['ALLOWED_EXTENSIONS'] = ALLOWED_EXTENSIONS

mysql = MySQL(app)

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def login_required(role="ANY"):
    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            if not session.get('logged_in'):
                return redirect(url_for('login'))
            if role != "ANY" and session.get('user_type') != role:
                flash("You don't have permission to access this page")
                return redirect(url_for('index'))
            return fn(*args, **kwargs)
        return decorated_view
    return wrapper

def is_room_available(room_id, check_in, check_out):
    """Check if a room is available for the given dates."""
    cur = mysql.connection.cursor()
    cur.execute('''
        SELECT * FROM bookings 
        WHERE room_id = %s 
        AND status = 'Confirmed'
        AND (%s < check_out_date AND %s > check_in_date)
    ''', (room_id, check_in, check_out))
    conflicting_booking = cur.fetchone()
    cur.close()
    return not conflicting_booking

# Routes
@app.route('/')
def index():
    cur = mysql.connection.cursor()
    cur.execute('''
        SELECT h.*, AVG(r.rating) as avg_rating 
        FROM hotels h 
        LEFT JOIN reviews r ON h.hotel_id = r.hotel_id 
        GROUP BY h.hotel_id 
        ORDER BY avg_rating DESC LIMIT 5
    ''')
    hotels = cur.fetchall()
    cur.close()
    return render_template('index.html', hotels=hotels)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        phone = request.form['phone']
        
        hashed_password = generate_password_hash(password)
        
        cur = mysql.connection.cursor()
        try:
            cur.execute("INSERT INTO users (username, email, password, phone_number) VALUES (%s, %s, %s, %s)", 
                       (username, email, hashed_password, phone))
            mysql.connection.commit()
            flash('Registration successful! You can now login.')
            return redirect(url_for('login'))
        except:
            flash('Username or email already exists')
        finally:
            cur.close()
    
    return render_template('auth/register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        
        if user and check_password_hash(user['password'], password):
            session['logged_in'] = True
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            session['user_type'] = user['user_type']
            flash('Login successful!')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password')
    
    return render_template('auth/login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out')
    return redirect(url_for('index'))

@app.route('/hotels')
def hotels():
    cur = mysql.connection.cursor()
    cur.execute('''
        SELECT h.*, AVG(r.rating) as avg_rating 
        FROM hotels h 
        LEFT JOIN reviews r ON h.hotel_id = r.hotel_id 
        GROUP BY h.hotel_id
    ''')
    hotels = cur.fetchall()
    cur.close()
    return render_template('hotels/index.html', hotels=hotels)

@app.route('/hotels/<int:hotel_id>')
def hotel_detail(hotel_id):
    check_in = request.args.get('check_in')
    check_out = request.args.get('check_out')
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM hotels WHERE hotel_id = %s", (hotel_id,))
    hotel = cur.fetchone()
    
    query = "SELECT * FROM rooms WHERE hotel_id = %s"
    params = [hotel_id]
    
    if check_in and check_out:
        query += '''
            AND room_id NOT IN (
                SELECT b.room_id FROM bookings b 
                WHERE b.status = 'Confirmed'
                AND (%s < b.check_out_date AND %s > b.check_in_date)
            )
        '''
        params.extend([check_in, check_out])
    
    cur.execute(query, params)
    rooms = cur.fetchall()
    
    cur.execute('''
        SELECT r.*, u.username 
        FROM reviews r 
        JOIN users u ON r.user_id = u.user_id 
        WHERE r.hotel_id = %s
        ORDER BY r.review_date DESC
    ''', (hotel_id,))
    reviews = cur.fetchall()
    cur.close()
    
    return render_template('hotels/detail.html', hotel=hotel, rooms=rooms, reviews=reviews, check_in=check_in, check_out=check_out)

@app.route('/hotels/<int:hotel_id>/check_availability', methods=['GET'])
def check_availability(hotel_id):
    check_in = request.args.get('check_in')
    check_out = request.args.get('check_out')
    guests = request.args.get('guests', type=int)
    
    cur = mysql.connection.cursor()
    cur.execute('''
        SELECT r.* FROM rooms r 
        WHERE r.hotel_id = %s 
        AND r.capacity >= %s
        AND r.room_id NOT IN (
            SELECT b.room_id FROM bookings b 
            WHERE b.status = 'Confirmed'
            AND (%s < b.check_out_date AND %s > b.check_in_date)
        )
    ''', (hotel_id, guests, check_in, check_out))
    rooms = cur.fetchall()
    
    cur.execute("SELECT * FROM hotels WHERE hotel_id = %s", (hotel_id,))
    hotel = cur.fetchone()
    cur.close()
    
    return render_template('hotels/detail.html', hotel=hotel, rooms=rooms, reviews=[], check_in=check_in, check_out=check_out)

@app.route('/rooms/<int:room_id>/book', methods=['GET', 'POST'])
@login_required()
def book_room(room_id):
    cur = mysql.connection.cursor()
    cur.execute('''
        SELECT r.*, h.hotel_name, h.location 
        FROM rooms r 
        JOIN hotels h ON r.hotel_id = h.hotel_id 
        WHERE r.room_id = %s
    ''', (room_id,))
    room = cur.fetchone()
    cur.close()
    
    if not room:
        flash('Room not found')
        return redirect(url_for('hotels'))
    
    if request.method == 'POST':
        check_in_date = request.form['check_in_date']
        check_out_date = request.form['check_out_date']
        number_of_guests = int(request.form['number_of_guests'])
        payment_method = request.form['payment_method']
        
        # Validate date overlap
        cur = mysql.connection.cursor()
        cur.execute('''
            SELECT * FROM bookings 
            WHERE room_id = %s 
            AND status = 'Confirmed'
            AND (%s < check_out_date AND %s > check_in_date)
        ''', (room_id, check_in_date, check_out_date))
        conflicting_booking = cur.fetchone()
        
        if conflicting_booking:
            cur.close()
            flash('Room is already booked for the selected dates.')
            return render_template('bookings/book.html', room=room, hotel=room)
        
        check_in = datetime.datetime.strptime(check_in_date, '%Y-%m-%d')
        check_out = datetime.datetime.strptime(check_out_date, '%Y-%m-%d')
        nights = (check_out - check_in).days
        total_amount = room['price_per_night'] * nights
        
        try:
            cur.execute('''
                INSERT INTO bookings (user_id, room_id, check_in_date, check_out_date, number_of_guests, total_amount)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (session['user_id'], room_id, check_in_date, check_out_date, number_of_guests, total_amount))
            
            booking_id = cur.lastrowid
            
            cur.execute('''
                INSERT INTO payments (booking_id, amount, payment_method, status, transaction_id)
                VALUES (%s, %s, %s, %s, %s)
            ''', (booking_id, total_amount, payment_method, 'Completed', f'TXN-{booking_id}'))
            
            mysql.connection.commit()
            flash('Booking successful!')
            return redirect(url_for('user_bookings'))
        except Exception as e:
            mysql.connection.rollback()
            flash('Booking failed. Please try again.')
        finally:
            cur.close()
    
    return render_template('bookings/book.html', room=room, hotel=room)

@app.route('/submit_review/<int:hotel_id>', methods=['POST'])
@login_required()
def submit_review(hotel_id):
    rating = int(request.form['rating'])
    comment = request.form['comment']
    
    cur = mysql.connection.cursor()
    cur.execute('''
        INSERT INTO reviews (user_id, hotel_id, rating, comment)
        VALUES (%s, %s, %s, %s)
    ''', (session['user_id'], hotel_id, rating, comment))
    mysql.connection.commit()
    cur.close()
    
    flash('Review submitted successfully')
    return redirect(url_for('hotel_detail', hotel_id=hotel_id))

@app.route('/bookings')
@login_required()
def user_bookings():
    cur = mysql.connection.cursor()
    cur.execute('''
        SELECT b.*, h.hotel_name, r.room_type 
        FROM bookings b 
        JOIN rooms r ON b.room_id = r.room_id 
        JOIN hotels h ON r.hotel_id = h.hotel_id 
        WHERE b.user_id = %s 
        ORDER BY b.booking_date DESC
    ''', (session['user_id'],))
    bookings = cur.fetchall()
    cur.close()
    return render_template('bookings/index.html', bookings=bookings)

@app.route('/admin/dashboard')
@login_required(role="Admin")
def admin_dashboard():
    cur = mysql.connection.cursor()
    cur.execute("SELECT COUNT(*) as hotel_count FROM hotels")
    hotel_count = cur.fetchone()['hotel_count']
    cur.execute("SELECT COUNT(*) as room_count FROM rooms")
    room_count = cur.fetchone()['room_count']
    cur.execute("SELECT COUNT(*) as booking_count FROM bookings WHERE status = 'Confirmed'")
    booking_count = cur.fetchone()['booking_count']
    cur.execute("SELECT COUNT(*) as user_count FROM users WHERE user_type = 'Customer'")
    user_count = cur.fetchone()['user_count']
    cur.close()
    return render_template('admin/dashboard.html', 
                         hotel_count=hotel_count,
                         room_count=room_count,
                         booking_count=booking_count,
                         user_count=user_count)

@app.route('/admin/hotels', methods=['GET', 'POST'])
@login_required(role="Admin")
def admin_hotels():
    if request.method == 'POST':
        hotel_name = request.form['hotel_name']
        location = request.form['location']
        description = request.form['description']
        star_rating = request.form['star_rating']
        contact_info = request.form['contact_info']
        amenities = request.form['amenities']
        
        image_path = None
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'hotels', filename))
                image_path = 'images/hotels/' + filename
        
        cur = mysql.connection.cursor()
        cur.execute('''
            INSERT INTO hotels (hotel_name, location, description, star_rating, image_path, contact_info, amenities)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (hotel_name, location, description, star_rating, image_path, contact_info, amenities))
        mysql.connection.commit()
        cur.close()
        flash('Hotel added successfully')
        return redirect(url_for('admin_hotels'))
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM hotels")
    hotels = cur.fetchall()
    cur.close()
    return render_template('admin/hotels.html', hotels=hotels)

@app.route('/rooms')
def rooms():
    hotel_id = request.args.get('hotel_id')
    room_type = request.args.get('room_type')
    check_in = request.args.get('check_in')
    check_out = request.args.get('check_out')
    
    query = '''
        SELECT r.*, h.hotel_name 
        FROM rooms r 
        JOIN hotels h ON r.hotel_id = h.hotel_id
        WHERE 1=1
    '''
    params = []
    
    if hotel_id:
        query += ' AND r.hotel_id = %s'
        params.append(hotel_id)
    if room_type:
        query += ' AND r.room_type LIKE %s'
        params.append(f'%{room_type}%')
    if check_in and check_out:
        query += '''
            AND r.room_id NOT IN (
                SELECT b.room_id FROM bookings b 
                WHERE b.status = 'Confirmed'
                AND (%s < b.check_out_date AND %s > b.check_in_date)
            )
        '''
        params.extend([check_in, check_out])
    
    cur = mysql.connection.cursor()
    cur.execute(query, params)
    rooms = cur.fetchall()
    
    cur.execute("SELECT * FROM hotels")
    hotels = cur.fetchall()
    cur.close()
    
    return render_template('rooms/index.html', rooms=rooms, hotels=hotels)

@app.route('/admin/rooms', methods=['GET', 'POST'])
@login_required(role="Admin")
def admin_rooms():
    if request.method == 'POST':
        hotel_id = request.form['hotel_id']
        room_type = request.form['room_type']
        price_per_night = request.form['price_per_night']
        capacity = request.form['capacity']
        features = request.form['features']
        
        image_path = None
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'rooms', filename))
                image_path = 'images/rooms/' + filename
        
        cur = mysql.connection.cursor()
        cur.execute('''
            INSERT INTO rooms (hotel_id, room_type, price_per_night, capacity, features, image_path)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (hotel_id, room_type, price_per_night, capacity, features, image_path))
        mysql.connection.commit()
        cur.close()
        flash('Room added successfully')
        return redirect(url_for('admin_rooms'))
    
    cur = mysql.connection.cursor()
    cur.execute('''
        SELECT r.*, h.hotel_name 
        FROM rooms r 
        JOIN hotels h ON r.hotel_id = h.hotel_id
    ''')
    rooms = cur.fetchall()
    
    # Add dynamic availability status for admin view
    current_date = datetime.datetime.now().strftime('%Y-%m-%d')
    for room in rooms:
        room['dynamic_availability'] = is_room_available(room['room_id'], current_date, current_date)
    
    cur.execute("SELECT * FROM hotels")
    hotels = cur.fetchall()
    cur.close()
    
    return render_template('admin/rooms.html', rooms=rooms, hotels=hotels)

@app.route('/admin/rooms/<int:room_id>/edit', methods=['GET', 'POST'])
@login_required(role="Admin")
def admin_edit_room(room_id):
    cur = mysql.connection.cursor()
    cur.execute('''
        SELECT r.*, h.hotel_name 
        FROM rooms r 
        JOIN hotels h ON r.hotel_id = h.hotel_id 
        WHERE r.room_id = %s
    ''', (room_id,))
    room = cur.fetchone()
    
    if not room:
        cur.close()
        flash('Room not found')
        return redirect(url_for('admin_rooms'))
    
    if request.method == 'POST':
        hotel_id = request.form['hotel_id']
        room_type = request.form['room_type']
        price_per_night = request.form['price_per_night']
        capacity = request.form['capacity']
        features = request.form['features']
        availability_status = 'availability_status' in request.form
        
        image_path = room['image_path']
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'rooms', filename))
                image_path = 'images/rooms/' + filename
        
        cur = mysql.connection.cursor()
        cur.execute('''
            UPDATE rooms 
            SET hotel_id = %s, room_type = %s, price_per_night = %s, capacity = %s, 
                features = %s, image_path = %s, availability_status = %s
            WHERE room_id = %s
        ''', (hotel_id, room_type, price_per_night, capacity, features, image_path, availability_status, room_id))
        mysql.connection.commit()
        cur.close()
        flash('Room updated successfully')
        return redirect(url_for('admin_rooms'))
    
    cur.execute("SELECT * FROM hotels")
    hotels = cur.fetchall()
    cur.close()
    
    return render_template('admin/rooms.html', rooms=[room], hotels=hotels, edit_mode=True)

@app.route('/admin/rooms/<int:room_id>/delete', methods=['GET'])
@login_required(role="Admin")
def admin_delete_room(room_id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM rooms WHERE room_id = %s", (room_id,))
    mysql.connection.commit()
    cur.close()
    flash('Room deleted successfully')
    return redirect(url_for('admin_rooms'))

if __name__ == '__main__':
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'hotels'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'rooms'), exist_ok=True)
    app.run(debug=True)