import io
import csv
from flask import Flask, render_template, request, redirect, url_for, session, Response
import cv2
import time
import mysql.connector
import bcrypt
from fpdf import FPDF
import base64, json, uuid, os
import datetime
from werkzeug.utils import secure_filename
import base64
import numpy as np
from PIL import Image
from io import BytesIO
import face_recognition


app = Flask(__name__)
app.secret_key = 'rahasia' 

# Konfigurasi database
db_config = {
"host": "localhost",
    "user": "root",
    "password": "",
    "database": "absensi_db"
}

# Load Haar Cascade untuk deteksi wajah
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

# Variabel global untuk kontrol scan
scan_active = False
scan_start_time = 0
scan_duration = 10  # detik

def gen_frames():
    global scan_active, scan_start_time
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Error: Cannot open camera")
        return  # stop generator jika kamera gagal

    while True:
        success, frame = cap.read()
        if not success:
            print("Failed to grab frame")
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if scan_active:
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
            for (x, y, w, h) in faces:
                # Gambar kotak hijau untuk scan
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 3)

            elapsed = time.time() - scan_start_time
            if elapsed > scan_duration:
                scan_active = False

        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

    cap.release()

@app.route('/export_excel')
def export_excel():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM absensi ORDER BY tanggal DESC, waktu DESC")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output, delimiter='\t')
    writer.writerow(['ID', 'Nama', 'Tanggal', 'Waktu'])

    for row in rows:
        writer.writerow([row['id'], row['nama'], row['tanggal'], row['waktu']])

    response = Response(output.getvalue(), mimetype='text/tab-separated-values')
    response.headers['Content-Disposition'] = 'attachment; filename=data_absensi.xls'
    return response

@app.route('/export_pdf')
def export_pdf():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM absensi ORDER BY tanggal DESC, waktu DESC")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    # Logo
    logo_path = os.path.join('static', 'assets', 'log.png')
    if os.path.exists(logo_path):
        pdf.image(logo_path, x=10, y=8, w=25)
    pdf.cell(200, 10, txt="Laporan Data Absensi", ln=True, align='C')
    pdf.ln(10)

    # Table header
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(15, 10, "ID", 1)
    pdf.cell(40, 10, "Nama", 1)
    pdf.cell(30, 10, "Tanggal", 1)
    pdf.cell(25, 10, "Waktu", 1)
    pdf.ln()

    pdf.set_font("Arial", size=10)
    for row in rows:
        pdf.cell(15, 10, str(row['id'] or ''), 1)
        pdf.cell(40, 10, str(row['nama'] or ''), 1)
        pdf.cell(30, 10, str(row['tanggal'] or ''), 1)
        pdf.cell(25, 10, str(row['waktu'] or ''), 1)
        pdf.ln()

    response = Response(pdf.output(dest='S').encode('latin-1'), mimetype='application/pdf')
    response.headers['Content-Disposition'] = 'attachment; filename=data_absensi.pdf'
    return response
    
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = ''
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        # Cek di tabel users (admin/guru)
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()

        if user and bcrypt.checkpw(password, user['password'].encode('utf-8')):
            session['logged_in'] = True
            session['username'] = user['username']
            session['role'] = user['role']
            cursor.close()
            conn.close()
            # Redirect sesuai role
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user['role'] == 'guru':
                return redirect(url_for('guru_dashboard'))
            else:
                return redirect(url_for('home'))
        else:
            # Jika tidak ditemukan di users, cek di pengguna (siswa)
            cursor.execute("SELECT * FROM pengguna WHERE nama=%s", (username,))
            siswa = cursor.fetchone()
            cursor.close()
            conn.close()
            if siswa and bcrypt.checkpw(password, siswa['password'].encode('utf-8')):
                session['logged_in'] = True
                session['username'] = siswa['nama']
                session['role'] = 'siswa'
                session['kelas'] = siswa['kelas']
                session['id'] = siswa['id']
                return redirect(url_for('siswa_dashboard'))
            else:
                error = "Username/Nama atau password salah!"

    return render_template('login.html', error=error)

@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    if not session.get('logged_in') or session.get('role') not in ['guru', 'admin']:
        return redirect(url_for('login'))

    # --- Tambah/Edit User ---
    edit_user = None
    if request.method == 'POST':
        id = request.form.get('id')
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # Edit
        if id:
            cursor.execute("SELECT username, password FROM users WHERE id=%s", (id,))
            old = cursor.fetchone()
            # Cek username unik
            if username != old['username']:
                cursor.execute("SELECT username FROM users WHERE username=%s", (username,))
                if cursor.fetchone():
                    cursor.close()
                    conn.close()
                    return "<script>alert('Username sudah digunakan.');window.history.back();</script>"
            # Password baru jika diisi
            if password:
                hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode()
            else:
                hashed = old['password']
            cursor.execute("UPDATE users SET username=%s, password=%s, role=%s WHERE id=%s", (username, hashed, role, id))
            conn.commit()
        else:
            # Tambah user baru
            cursor.execute("SELECT username FROM users WHERE username=%s", (username,))
            if cursor.fetchone():
                cursor.close()
                conn.close()
                return "<script>alert('Username sudah digunakan.');window.history.back();</script>"
            hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode()
            cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", (username, hashed, role))
            conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('admin_dashboard'))

    # --- Hapus User ---
    delete_username = request.args.get('delete')
    if delete_username:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE username=%s", (delete_username,))
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('admin_dashboard'))

    # --- Edit Data User (ambil data untuk form) ---
    edit_id = request.args.get('id')
    if edit_id:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id=%s", (edit_id,))
        edit_user = cursor.fetchone()
        cursor.close()
        conn.close()

    # --- Ambil Semua User ---
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users ORDER BY username ASC")
    users = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('admin_dashboard.html', username=session['username'], users=users, edit_user=edit_user)

# Route untuk hapus user (opsional, agar url_for('delete_user', ...) bisa dipakai)
@app.route('/delete_user/<username>')
def delete_user(username):
    if not session.get('logged_in') or session.get('role') not in ['guru', 'admin']:
        return redirect(url_for('login'))
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE username=%s", (username,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('admin_dashboard'))


@app.route('/daftar_wajah', methods=['POST'])
def daftar_wajah():
    if not session.get('logged_in') or session.get('role') != 'siswa':
        return redirect(url_for('login'))

    import uuid
    encoding_wajah = request.form.get('encoding_wajah')
    nama = session.get('username')
    kelas = session.get('kelas')

    if not encoding_wajah:
        return "<script>alert('Data wajah tidak ditemukan!');window.history.back();</script>"

    print("encoding_wajah (awal):", encoding_wajah[:100])

    try:
        # Decode base64
        header, encoded = encoding_wajah.split(",", 1)
        img_bytes = base64.b64decode(encoded)

        # Load image dengan PIL dan pastikan dalam RGB
        from PIL import Image
        import io
        img = Image.open(BytesIO(img_bytes)).convert("RGB")
        img_np = np.array(img)
        img_np = np.ascontiguousarray(img_np, dtype=np.uint8)

        # Debug info
        print("img_np.shape:", img_np.shape)
        print("img_np.dtype:", img_np.dtype)
        print("img_np.flags['C_CONTIGUOUS']:", img_np.flags['C_CONTIGUOUS'])

        # Pastikan format benar (tinggi, lebar, 3 channel)
        if len(img_np.shape) != 3 or img_np.shape[2] != 3:
            raise Exception(f"Channel gambar bukan 3 (RGB), tapi {img_np.shape[2]}")

        # Pastikan format numpy array dalam bentuk C-contiguous (opsional tapi aman)
        img_np = np.ascontiguousarray(img_np)

        # Panggil face_recognition (format sudah RGB)
        face_locations = face_recognition.face_locations(img_np)
        print("face_locations:", face_locations)
        encodings = face_recognition.face_encodings(img_np, face_locations)

        if not encodings:
            raise Exception("Tidak ada wajah terdeteksi!")

        vector = encodings[0]
        vector_str = json.dumps(vector.tolist())

    except Exception as e:
        print("Error daftar wajah:", e)
        return "<script>alert('Gagal memproses wajah! Pastikan hanya satu wajah terlihat.');window.history.back();</script>"

    # Simpan ke database
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE pengguna SET encoding_wajah=%s WHERE nama=%s AND kelas=%s",
            (vector_str, nama, kelas)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as db_err:
        print("Database error:", db_err)
        return "<script>alert('Gagal menyimpan ke database!');window.history.back();</script>"

    return "<script>alert('Wajah berhasil didaftarkan/diupdate!');window.location.href='" + url_for('siswa_dashboard') + "';</script>"




# filepath: [app.py](http://_vscodecontentref_/6)
@app.route('/data_absensi', methods=['GET', 'POST'])
def data_absensi():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # --- Proses Tambah/Edit ---
    if request.method == 'POST':
        old_id = int(request.form.get('old_id', 0))
        new_id = int(request.form.get('id', 0))
        nama = request.form.get('nama', '')
        kelas = request.form.get('kelas', '')
        tanggal = request.form.get('tanggal', '')
        waktu = request.form.get('waktu', '')
        keterangan = request.form.get('keterangan', '')

        # Ambil path foto jika ada
        fotoPath = ''
        if new_id > 0:
            cursor.execute("SELECT foto FROM absensi WHERE id=%s", (new_id,))
            fotoRow = cursor.fetchone()
            if fotoRow:
                fotoPath = fotoRow['foto']

        if old_id > 0:
            # Update data
            cursor.execute(
                "UPDATE absensi SET nama=%s, kelas=%s, tanggal=%s, waktu=%s, keterangan=%s, foto=%s WHERE id=%s",
                (nama, kelas, tanggal, waktu, keterangan, fotoPath, old_id)
            )
            conn.commit()
        else:
            # Insert data baru (tanpa id, biar auto increment)
            cursor.execute(
                "INSERT INTO absensi (nama, kelas, tanggal, waktu, keterangan, foto) VALUES (%s, %s, %s, %s, %s, %s)",
                (nama, kelas, tanggal, waktu, keterangan, fotoPath)
            )
            conn.commit()
        return redirect(url_for('data_absensi'))

    # --- Proses Hapus ---
    delete_id = request.args.get('delete')
    if delete_id:
        cursor.execute("DELETE FROM absensi WHERE id=%s", (delete_id,))
        conn.commit()
        return redirect(url_for('data_absensi'))

    # --- Ambil data untuk edit ---
    editData = None
    edit_id = request.args.get('edit')
    if edit_id:
        cursor.execute("SELECT * FROM absensi WHERE id=%s", (edit_id,))
        editData = cursor.fetchone()

    # --- Filter ---
    filter_kelas = request.args.get('filter_kelas', '')
    filter_tanggal = request.args.get('filter_tanggal', '')

    where = []
    params = []
    if filter_kelas:
        where.append("kelas LIKE %s")
        params.append(f"%{filter_kelas}%")
    if filter_tanggal:
        where.append("tanggal = %s")
        params.append(filter_tanggal)

    sql = "SELECT * FROM absensi"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY tanggal DESC, waktu DESC"
    cursor.execute(sql, params)
    absensi_list = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'data_absensi.html',
        username=session['username'],
        absensi=absensi_list,
        editData=editData,
        filter_kelas=filter_kelas,
        filter_tanggal=filter_tanggal
    )

@app.route('/data_pengguna', methods=['GET', 'POST'])
def data_pengguna():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    pesan_sukses = None
    editData = None

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # --- Proses Tambah/Edit ---
    if request.method == 'POST':
        if 'bulk_update' in request.form:
            # Update massal kelas
            from_kelas = request.form.get('from_kelas', '')
            to_kelas = request.form.get('to_kelas', '')
            if from_kelas and to_kelas:
                cursor.execute("UPDATE pengguna SET kelas=%s WHERE kelas=%s", (to_kelas, from_kelas))
                conn.commit()
                pesan_sukses = f"Berhasil mengubah semua siswa dari kelas <strong>{from_kelas}</strong> ke <strong>{to_kelas}</strong>."
        else:
            old_nama = request.form.get('old_nama', '')
            nama = request.form.get('nama', '')
            kelas = request.form.get('kelas', '')
            password = request.form.get('password', '')

            if nama and kelas:
                # Cek nama unik jika ganti nama
                if nama != old_nama:
                    cursor.execute("SELECT nama FROM pengguna WHERE nama=%s", (nama,))
                    if cursor.fetchone():
                        cursor.close()
                        conn.close()
                        return "<script>alert('Nama sudah digunakan.');window.history.back();</script>"

                if old_nama:
                    # Edit data
                    cursor.execute("SELECT * FROM pengguna WHERE nama=%s", (old_nama,))
                    oldData = cursor.fetchone()
                    oldKelas = oldData['kelas'] if oldData else ''
                    finalKelas = kelas if kelas != oldKelas else oldKelas

                    if password:
                        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode()
                        cursor.execute("UPDATE pengguna SET nama=%s, kelas=%s, password=%s WHERE nama=%s",
                                       (nama, finalKelas, hashed, old_nama))
                    else:
                        cursor.execute("UPDATE pengguna SET nama=%s, kelas=%s WHERE nama=%s",
                                       (nama, finalKelas, old_nama))
                    conn.commit()
                else:
                    # Tambah data baru
                    if not password:
                        cursor.close()
                        conn.close()
                        return "<script>alert('Password wajib diisi.');window.history.back();</script>"
                    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode()
                    cursor.execute("INSERT INTO pengguna (nama, kelas, password) VALUES (%s, %s, %s)",
                                   (nama, kelas, hashed))
                    conn.commit()
            return redirect(url_for('data_pengguna'))

    # --- Proses Hapus ---
    delete_nama = request.args.get('delete')
    if delete_nama:
        cursor.execute("DELETE FROM pengguna WHERE nama=%s", (delete_nama,))
        conn.commit()
        return redirect(url_for('data_pengguna'))

    # --- Ambil data untuk edit ---
    edit_id = request.args.get('id')
    if edit_id:
        cursor.execute("SELECT * FROM pengguna WHERE id=%s", (edit_id,))
        editData = cursor.fetchone()
        
    filter_kelas = request.args.get('filter_kelas', '')
    if filter_kelas:
        cursor.execute("SELECT id, nama, kelas FROM pengguna WHERE kelas LIKE %s ORDER BY nama ASC", (f"%{filter_kelas}%",))
    else:
        cursor.execute("SELECT id, nama, kelas FROM pengguna ORDER BY nama ASC")
    users = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'data_pengguna.html',
        username=session['username'],
        users=users,
        editData=editData,
        pesan_sukses=pesan_sukses,
        filter_kelas=filter_kelas
    )

@app.route('/guru')
def guru_dashboard():
    if not session.get('logged_in') or session.get('role') != 'guru':
        return redirect(url_for('login'))
    return render_template('guru_dashboard.html', username=session['username'])

@app.route('/siswa')
def siswa_dashboard():
    if not session.get('logged_in') or session.get('role') != 'siswa':
        return redirect(url_for('login'))
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT encoding_wajah FROM pengguna WHERE nama=%s AND kelas=%s", (session['username'], session.get('kelas')))
    data = cursor.fetchone()
    cursor.close()
    conn.close()
    wajah_terdaftar = bool(data and data['encoding_wajah'])
    return render_template('siswa_dashboard.html', nama=session['username'], kelas=session.get('kelas'), wajah_terdaftar=wajah_terdaftar)

@app.route('/')
def home():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif session.get('role') == 'guru':
        return redirect(url_for('guru_dashboard'))
    elif session.get('role') == 'siswa':
        return redirect(url_for('siswa_dashboard'))
    else:
        return render_template('home.html', username=session['username'])

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/absen_siswa', methods=['POST'])
def absen_siswa():
    if not session.get('logged_in') or session.get('role') != 'siswa':
        return redirect(url_for('login'))

    from datetime import datetime

    encoding_wajah_absen = request.form.get('encoding_wajah_absen')
    nama = session['username']
    kelas = session.get('kelas')

    # Ambil tanggal & waktu sekarang (untuk konsistensi file dan database)
    tanggal = datetime.now().strftime("%Y-%m-%d")
    waktu = datetime.now().strftime("%H:%M:%S")

    # Simpan data ke session untuk halaman sukses
    session['absen_nama'] = nama
    session['absen_kelas'] = kelas
    session['absen_tanggal'] = tanggal
    session['absen_waktu'] = waktu

    if not encoding_wajah_absen:
        return "<script>alert('Data wajah absen tidak ditemukan!');window.history.back();</script>"

    # Ambil encoding vector dari database
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT encoding_wajah FROM pengguna WHERE nama=%s AND kelas=%s", (nama, kelas))
    data = cursor.fetchone()
    cursor.close()
    conn.close()

    if not data or not data['encoding_wajah']:
        return "<script>alert('Wajah belum terdaftar!');window.history.back();</script>"

    try:
        # Ambil vector dari database
        vector_db = np.array(json.loads(data['encoding_wajah']))

        # Ambil vector dari gambar absen
        if "," not in encoding_wajah_absen:
            raise Exception("Format data wajah absen tidak valid")
        header, encoded = encoding_wajah_absen.split(",", 1)
        img_bytes = base64.b64decode(encoded)
        img = Image.open(BytesIO(img_bytes)).convert("RGB")
        img_np = np.array(img)
        img_np = np.ascontiguousarray(img_np, dtype=np.uint8)
        encodings_absen = face_recognition.face_encodings(img_np)
        if not encodings_absen:
            raise Exception("Wajah absen tidak terdeteksi")
        vector_absen = encodings_absen[0]

        # Bandingkan vector
        match = face_recognition.compare_faces([vector_db], vector_absen, tolerance=0.5)[0]
    except Exception as e:
        print("Error absen:", e)
        return "<script>alert('Gagal memproses wajah: {}');window.history.back();</script>".format(str(e).replace("'", "\\'"))

    if not match:
        return "<script>alert('Wajah tidak cocok!');window.history.back();</script>"

    # Simpan file foto bukti absen
    foto_folder = os.path.join('static', 'bukti_absen')
    os.makedirs(foto_folder, exist_ok=True)
    filename = f"{nama}_{kelas}_{tanggal}_{waktu.replace(':', '-')}.jpg".replace(' ', '_')
    foto_path = os.path.join(foto_folder, filename)
    img.save(foto_path)

    # Simpan path relatif ke database (agar bisa diakses dari /static/bukti_absen/...)
    foto_db = os.path.join('bukti_absen', filename).replace("\\", "/")

    # Simpan data absen ke database
    keterangan = request.form.get('keterangan', 'Hadir')
    if not keterangan:
        keterangan = 'Hadir'
    if keterangan not in ['Hadir', 'Sakit', 'Izin', 'Alfa']:
        return "<script>alert('Keterangan tidak valid!');window.history.back();</script>"
    if not nama or not kelas or not tanggal or not waktu:
        return "<script>alert('Data absen tidak lengkap!');window.history.back();</script>"

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO absensi (nama, kelas, tanggal, waktu, keterangan, foto) VALUES (%s, %s, %s, %s, %s, %s)",
        (nama, kelas, tanggal, waktu, keterangan, foto_db)
    )
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('absen_sukses'))

@app.route('/absen_sukses')
def absen_sukses():
    nama = session.pop('absen_nama', '')
    kelas = session.pop('absen_kelas', '')
    tanggal = session.pop('absen_tanggal', '')
    waktu = session.pop('absen_waktu', '')
    return render_template('absen_sukses.html', nama=nama, kelas=kelas, tanggal=tanggal, waktu=waktu)

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_scan')
def start_scan():
    global scan_active, scan_start_time
    scan_active = True
    scan_start_time = time.time()
    print("Scan started at", scan_start_time)
    return "Scan started"

if __name__ == '__main__':
    app.run(debug=False)


