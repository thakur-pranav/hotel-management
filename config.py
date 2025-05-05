
# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',  # Replace with your MySQL username
    'password': '1234',  # Replace with your MySQL password
    'db': 'hotel_management',
    'charset': 'utf8mb4'
}

# App configuration
SECRET_KEY = 'abc'  # Change to a random string
UPLOAD_FOLDER = 'static/images'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
