import mysql.connector
import bcrypt

# Konfigurasi koneksi MySQL
db_config = {
    "host": "localhost",
    "user": "root",
    "password": "",  # ganti jika password root MySQL kamu berbeda
}

# Koneksi ke MySQL
conn = mysql.connector.connect(**db_config)
cursor = conn.cursor()

# Buat database jika belum ada
cursor.execute("CREATE DATABASE IF NOT EXISTS absensi_db")
cursor.execute("USE absensi_db")

# Buat tabel users (admin & guru)
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role ENUM('admin','guru') NOT NULL
)
""")

# Buat tabel pengguna (siswa)
cursor.execute("""
CREATE TABLE IF NOT EXISTS pengguna (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nama VARCHAR(100) NOT NULL UNIQUE,
    kelas VARCHAR(50) NOT NULL,
    password VARCHAR(255) NOT NULL
)
""")

# Buat tabel absensi
cursor.execute("""
CREATE TABLE IF NOT EXISTS absensi (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nama VARCHAR(100) NOT NULL,
    kelas VARCHAR(50) NOT NULL,
    tanggal DATE NOT NULL,
    waktu TIME NOT NULL,
    foto VARCHAR(255)
)
""")

# Tambahkan user admin dan guru default jika belum ada
def insert_default_user(username, password, role):
    cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
    if not cursor.fetchone():
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        cursor.execute(
            "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
            (username, hashed.decode('utf-8'), role)
        )

insert_default_user("admin", "123", "admin")
insert_default_user("guru", "123", "guru")
conn.commit()

print("Database dan tabel berhasil dibuat!")
print("User default: admin/123 dan guru/123")

cursor.close()
conn.close()