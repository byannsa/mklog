import io
import csv
from flask import Flask, render_template, request, redirect, url_for, session, Response, flash
import cv2
import time
import mysql.connector
import bcrypt
from fpdf import FPDF
import base64, json, uuid, os
from datetime import datetime
from werkzeug.utils import secure_filename
import base64
import numpy as np
from PIL import Image
from io import BytesIO
import face_recognition
import json  # tambahkan import ini



app = Flask(__name__)
app.secret_key = 'rahasia' 

# Konfigurasi database
db_config = {
"host": "localhost",
    "user": "root",
    "password": "",
    "database": "absensiadv_db"
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
        
        # Cek di tabel users (admin/superadmin saja)
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()

        cursor.close()
        conn.close()

        if user and bcrypt.checkpw(password, user['password'].encode('utf-8')):
            session['logged_in'] = True
            session['username'] = user['username']
            session['role'] = user['role']

            # Redirect sesuai role
            if user['role'] == 'superadmin':
                return redirect(url_for('superadmin_dashboard'))
            elif user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('home'))
        else:
            error = "Username atau password salah!"

    return render_template('login.html', error=error)


@app.route('/superadmin', methods=['GET', 'POST'])
def superadmin_dashboard():
    if not session.get('logged_in') or session.get('role') not in ['admin', 'superadmin']:
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
        return redirect(url_for('superadmin_dashboard'))

    # --- Hapus User ---
    delete_username = request.args.get('delete')
    if delete_username:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE username=%s", (delete_username,))
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('superadmin_dashboard'))

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

    return render_template('superadmin_dashboard.html', username=session['username'], users=users, edit_user=edit_user)

# Route untuk hapus user (opsional, agar url_for('delete_user', ...) bisa dipakai)
@app.route('/delete_user/<username>')
def delete_user(username):
    if not session.get('logged_in') or session.get('role') not in ['admin', 'superadmin']:
        return redirect(url_for('login'))
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE username=%s", (username,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('superdmin_dashboard'))





# filepath: [app.py](http://_vscodecontentref_/6)
@app.route('/data_absensi', methods=['GET', 'POST'])
def data_absensi():
    if session.get('role') != 'superadmin' and not session.get('absensi_verified'):
        flash("Silakan verifikasi password terlebih dahulu.", "warning")
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('login'))


    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # --- Proses Tambah/Edit ---
    if request.method == 'POST':
        old_id = int(request.form.get('old_id', 0))
        new_id = int(request.form.get('id', 0))
        nama = request.form.get('nama', '')
        jabatan = request.form.get('jabatan', '')
        divisi = request.form.get('divisi', '')
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
                "UPDATE absensi SET nama=%s, jabatan=%s, divisi=%s, tanggal=%s, waktu=%s, keterangan=%s, foto=%s WHERE id=%s",
                (nama, jabatan, divisi, tanggal, waktu, keterangan, fotoPath, old_id)
            )
            conn.commit()
        else:
            # Insert data baru (tanpa id, biar auto increment)
            cursor.execute(
                "INSERT INTO absensi (nama, jabatan, divisi, tanggal, waktu, keterangan, foto) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (nama, jabatan, divisi, tanggal, waktu, keterangan, fotoPath)
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
    filter_divisi = request.args.get('filter_divisi', '')
    filter_tanggal = request.args.get('filter_tanggal', '')

    where = []
    params = []
    if filter_divisi:
        where.append("divisi LIKE %s")
        params.append(f"%{filter_divisi}%")
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
        filter_divisi=filter_divisi,
        filter_tanggal=filter_tanggal
    )


@app.route('/verify_absensi_password', methods=['POST'])
def verify_absensi_password():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    # Ambil password yang diinput
    password_input = request.form['password'].encode('utf-8')
    username = session.get('username')

    # Ambil user dari database
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT password, role FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    # Jika user ditemukan dan password cocok
    if user and bcrypt.checkpw(password_input, user['password'].encode('utf-8')):
        session['absensi_verified'] = True
        return redirect(url_for('data_absensi'))

    # Jika user superadmin, lewati verifikasi
    if user and user['role'] == 'superadmin':
        return redirect(url_for('data_absensi'))

    # Jika gagal
    flash("Password salah atau akses ditolak.", "danger")

    # Kembali ke dashboard sesuai role
    if user and user['role'] == 'superadmin':
        return redirect(url_for('superadmin_dashboard'))
    else:
        return redirect(url_for('admin_dashboard'))




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
        old_nama = request.form.get('old_nama', '')
        nama = request.form.get('nama', '')
        jabatan = request.form.get('jabatan', '')
        divisi = request.form.get('divisi', '')
        foto_file = request.files.get('foto')

        if nama and jabatan and divisi:
            # Cek nama unik jika mengganti nama
            if nama != old_nama:
                cursor.execute("SELECT nama FROM pengguna WHERE nama=%s", (nama,))
                if cursor.fetchone():
                    cursor.close()
                    conn.close()
                    return "<script>alert('Nama sudah digunakan.');window.history.back();</script>"

            foto_filename = None
            encoding_json = None

            if foto_file and foto_file.filename != '':
                # Simpan file foto
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                filename_secure = secure_filename(foto_file.filename)
                foto_filename = f"{timestamp}_{filename_secure}"
                foto_path = os.path.join('static/foto_pengguna', foto_filename)
                foto_file.save(foto_path)

                # Deteksi dan encoding wajah
                image = face_recognition.load_image_file(foto_path)
                encodings = face_recognition.face_encodings(image)

                if encodings:
                    encoding_np = encodings[0]
                    encoding_json = json.dumps(encoding_np.tolist())  # simpan sebagai JSON string
                else:
                    os.remove(foto_path)
                    return "<script>alert('Wajah tidak terdeteksi pada foto.');window.history.back();</script>"

            if old_nama:
                # Ambil data lama jika tidak mengubah foto
                if not foto_filename or not encoding_json:
                    cursor.execute("SELECT foto, encoding_wajah FROM pengguna WHERE nama=%s", (old_nama,))
                    old_data = cursor.fetchone()
                    if old_data:
                        if not foto_filename:
                            foto_filename = old_data['foto']
                        if not encoding_json:
                            encoding_json = old_data['encoding_wajah']

                # Edit data
                cursor.execute(
                    "UPDATE pengguna SET nama=%s, jabatan=%s, divisi=%s, encoding_wajah=%s, foto=%s WHERE nama=%s",
                    (nama, jabatan, divisi, encoding_json, foto_filename, old_nama)
                )
            else:
                # Tambah data baru
                cursor.execute(
                    "INSERT INTO pengguna (nama, jabatan, divisi, encoding_wajah, foto) VALUES (%s, %s, %s, %s, %s)",
                    (nama, jabatan, divisi, encoding_json, foto_filename)
                )
            conn.commit()
        return redirect(url_for('data_pengguna'))

    # --- Proses Hapus ---
    delete_nama = request.args.get('delete')
    if delete_nama:
        # Hapus file foto jika ada
        cursor.execute("SELECT foto FROM pengguna WHERE nama=%s", (delete_nama,))
        row = cursor.fetchone()
        if row and row['foto']:
            foto_path = os.path.join('static/foto_pengguna', row['foto'])
            if os.path.exists(foto_path):
                os.remove(foto_path)

        cursor.execute("DELETE FROM pengguna WHERE nama=%s", (delete_nama,))
        conn.commit()
        return redirect(url_for('data_pengguna'))

    # --- Ambil data untuk edit ---
    edit_id = request.args.get('id')
    if edit_id:
        cursor.execute("SELECT * FROM pengguna WHERE id=%s", (edit_id,))
        editData = cursor.fetchone()

    cursor.execute("SELECT id, nama, jabatan, divisi, foto FROM pengguna ORDER BY nama ASC")
    users = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'data_pengguna.html',
        username=session['username'],
        users=users,
        editData=editData,
        pesan_sukses=pesan_sukses
    )



@app.route('/admin')
def admin_dashboard():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))
    return render_template('admin_dashboard.html', username=session['username'])

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
    if session.get('role') == 'superadmin':
        return redirect(url_for('superadmin_dashboard'))
    elif session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))
    else:
        return render_template('home.html', username=session['username'])

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/absen_karyawan', methods=['POST'])
def absen_karyawan():
    encoding_wajah = request.form.get('encoding_wajah_absen')


    if not encoding_wajah:
        return "<script>alert('Data wajah tidak ditemukan!');window.history.back();</script>"

    try:
        # Konversi base64 ke image
        if "," not in encoding_wajah:
            raise Exception("Format data wajah tidak valid")
        header, encoded = encoding_wajah.split(",", 1)
        img_bytes = base64.b64decode(encoded)
        img = Image.open(BytesIO(img_bytes)).convert("RGB")
        img_np = np.array(img)
        img_np = np.ascontiguousarray(img_np, dtype=np.uint8)

        # Ekstrak encoding wajah dari gambar absen
        encodings_absen = face_recognition.face_encodings(img_np)
        if not encodings_absen:
            raise Exception("Wajah tidak terdeteksi")
        vector_absen = encodings_absen[0]

        # Ambil semua encoding dari DB
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT nama, jabatan, divisi, encoding_wajah FROM pengguna WHERE encoding_wajah IS NOT NULL")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        match_found = False
        nama = jabatan = divisi = None

        for row in rows:
            try:
                vector_db = np.array(json.loads(row['encoding_wajah']))
                match = face_recognition.compare_faces([vector_db], vector_absen, tolerance=0.5)[0]
                if match:
                    nama = row['nama']
                    jabatan = row['jabatan']
                    divisi = row['divisi']
                    match_found = True
                    break
            except Exception:
                continue

        if not match_found:
            return "<script>alert('Wajah tidak dikenali!');window.history.back();</script>"

        # Simpan foto bukti
        tanggal = datetime.now().strftime("%Y-%m-%d")
        waktu = datetime.now().strftime("%H:%M:%S")
        foto_folder = os.path.join('static', 'bukti_absen_karyawan')
        os.makedirs(foto_folder, exist_ok=True)
        filename = f"{nama}_{tanggal}_{waktu.replace(':', '-')}.jpg".replace(' ', '_')
        foto_path = os.path.join(foto_folder, filename)
        img.save(foto_path)
        foto_db = os.path.join('bukti_absen_karyawan', filename).replace("\\", "/")

        # Ambil keterangan dari form
        keterangan = request.form.get('keterangan', 'Hadir')
        if keterangan not in ['Hadir', 'Sakit', 'Izin', 'Alfa']:
            keterangan = 'Hadir'

        # Simpan ke tabel absensi
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO absensi (nama, jabatan, divisi, tanggal, waktu, keterangan, foto)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (nama, jabatan, divisi, tanggal, waktu, keterangan, foto_db))

        conn.commit()
        cursor.close()
        conn.close()

        # Simpan ke session
        session['absen_nama'] = nama
        session['absen_jabatan'] = jabatan
        session['absen_divisi'] = divisi # jika ada kolom divisi
        session['absen_tanggal'] = tanggal
        session['absen_waktu'] = waktu


        # Redirect ke halaman sukses
        return redirect(url_for('absen_sukses'))

    except Exception as e:
        print("Error absen karyawan:", e)
        return "<script>alert('Gagal memproses absen: {}');window.history.back();</script>".format(
            str(e).replace("'", "\\'")
        )


@app.route('/absen_sukses')
def absen_sukses():
    nama = session.pop('absen_nama', '')
    jabatan = session.pop('absen_jabatan', '')
    divisi = session.pop('absen_divisi', '')
    tanggal = session.pop('absen_tanggal', '')
    waktu = session.pop('absen_waktu', '')
    return render_template('absen_sukses.html', nama=nama, jabatan=jabatan, divisi=divisi, tanggal=tanggal, waktu=waktu)

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


