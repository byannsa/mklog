import io
import csv
from flask import Flask, render_template, request, redirect, url_for, session, Response
import cv2
import time
import mysql.connector
import bcrypt
from fpdf import FPDF
import os
import datetime
from werkzeug.utils import secure_filename
import base64

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
    return render_template('siswa_dashboard.html', nama=session['username'], kelas=session.get('kelas'))

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

    nama = session['username']
    kelas = session.get('kelas')
    waktu = datetime.datetime.now().strftime('%H:%M:%S')
    tanggal = datetime.datetime.now().strftime('%Y-%m-%d')

    foto_data = request.form.get('foto')
    if not foto_data:
        return "<script>alert('Foto wajib diambil!');window.history.back();</script>"

    # Simpan foto base64 ke file
    header, encoded = foto_data.split(",", 1)
    img_bytes = base64.b64decode(encoded)
    filename = secure_filename(f"{nama}_{kelas}_{tanggal}_{waktu.replace(':','-')}.jpg")
    foto_path = f"bukti_absen/{filename}"  # <-- simpan ke bukti_absen
    save_path = os.path.join('static', foto_path)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "wb") as f:
        f.write(img_bytes)

    # Simpan ke database absensi
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO absensi (nama, kelas, tanggal, waktu, foto) VALUES (%s, %s, %s, %s, %s)",
        (nama, kelas, tanggal, waktu, foto_path)
    )
    conn.commit()
    cursor.close()
    conn.close()

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
    app.run(debug=True)
