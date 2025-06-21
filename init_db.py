import psycopg2
import psycopg2.errors
import bcrypt

# Konfigurasi koneksi awal (ke DB postgres default)
db_config = {
    "host": "localhost",
    "user": "postgres",
    "password": "fabian",  # ganti sesuai password PostgreSQL-mu
    "dbname": "postgres"
}

# Nama database yang ingin dibuat
target_db = "absensiadv_db"

try:
    # Koneksi ke default database
    conn = psycopg2.connect(**db_config)
    conn.autocommit = True
    cursor = conn.cursor()

    # Cek apakah database target sudah ada
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
    exists = cursor.fetchone()

    # Jika belum ada, buat database-nya
    if not exists:
        cursor.execute(f"CREATE DATABASE {target_db}")
        print(f"Database '{target_db}' berhasil dibuat.")
    else:
        print(f"Database '{target_db}' sudah ada.")

    cursor.close()
    conn.close()

    # Sekarang koneksi ke database absensiadv_db
    conn = psycopg2.connect(
        host="localhost",
        user="postgres",
        password="fabian",
        dbname=target_db
    )
    cursor = conn.cursor()

    # Buat tabel users (admin)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(50) NOT NULL UNIQUE,
        password VARCHAR(255) NOT NULL,
        role VARCHAR(20) CHECK (role IN ('superadmin', 'admin')) NOT NULL
    )
    """)

    # Buat tabel pengguna
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pengguna (
        id SERIAL PRIMARY KEY,
        nama VARCHAR(100) NOT NULL UNIQUE,
        jabatan VARCHAR(50) NOT NULL,
        divisi VARCHAR(50) NOT NULL,
        foto VARCHAR(255) NOT NULL,
        encoding_wajah TEXT
    )
    """)

    # Buat tabel absensi
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS absensi (
    id SERIAL PRIMARY KEY,
    nama VARCHAR(100) NOT NULL,
    jabatan VARCHAR(50) NOT NULL,
    divisi VARCHAR(50) NOT NULL,
    tanggal DATE NOT NULL,
    waktu TIME NOT NULL,
    keterangan VARCHAR(10) CHECK (keterangan IN ('hadir', 'izin', 'sakit', 'alpha')) NOT NULL,
    foto VARCHAR(255),
    terlambat INTEGER),
    waktu_pulang TIME NOT NULL
    """)


    # Fungsi untuk menambahkan user default
    def insert_default_user(username, password, role):
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        if not cursor.fetchone():
            hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                (username, hashed.decode('utf-8'), role)
            )

    insert_default_user("superadmin", "123", "superadmin")
    insert_default_user("admin", "123", "admin")

    conn.commit()

    print("Tabel berhasil dibuat dan user default ditambahkan.")
    print("Login default: superadmin/123 dan admin/123")

    cursor.close()
    conn.close()

except Exception as e:
    print("Terjadi kesalahan:", e)
