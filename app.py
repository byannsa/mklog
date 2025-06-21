import io
import csv
from flask import Flask, render_template, request, redirect, url_for, session, Response, flash, send_file
import xlsxwriter
import tempfile
import cv2
import time
import psycopg2  # GANTI dari mysql.connector ke psycopg2
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
import json  # sudah ada, tetap
import psycopg2.extras
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = 'rahasia'

load_dotenv()

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        cursor_factory=psycopg2.extras.RealDictCursor
    )


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
    
@app.route('/rekap_absensi')
def rekap_absensi():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    username = session.get('username', 'Pengguna')
    role = session.get('role', 'user')

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT nama FROM pengguna ORDER BY nama")
    daftar_pengguna = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template(
        'rekap_absensi.html',
        daftar_pengguna=daftar_pengguna,
        username=username,
        role=role
    )






@app.route('/export_karyawan')
def export_karyawan():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    nama_karyawan = request.args.get('nama')
    bulan = request.args.get('bulan')
    if not nama_karyawan or not bulan:
        return "<script>alert('Parameter nama dan bulan wajib diisi!');window.history.back();</script>"

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT * FROM absensi 
        WHERE nama = %s AND TO_CHAR(tanggal, 'YYYY-MM') = %s
        ORDER BY tanggal, waktu
    """, (nama_karyawan, bulan))
    data = cursor.fetchall()
    cursor.close()
    conn.close()

    # Rekap
    total_hadir = sum(1 for row in data if row['keterangan'].lower() == 'hadir')
    total_izin = sum(1 for row in data if row['keterangan'].lower() == 'izin')
    total_sakit = sum(1 for row in data if row['keterangan'].lower() == 'sakit')
    total_terlambat = sum(row.get('terlambat', 0) or 0 for row in data)

    total_menit_kerja = 0
    for row in data:
        masuk = row.get('waktu')
        pulang = row.get('waktu_pulang')
        if masuk and pulang:
            try:
                fmt = "%H:%M:%S" if len(masuk) > 5 else "%H:%M"
                jam_masuk = datetime.strptime(str(masuk), fmt)
                jam_pulang = datetime.strptime(str(pulang), fmt)
                selisih = (jam_pulang - jam_masuk).total_seconds() / 60
                if selisih > 0:
                    total_menit_kerja += selisih
            except:
                pass
    jam_total = int(total_menit_kerja // 60)
    menit_total = int(total_menit_kerja % 60)

    # Buat file Excel
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
    workbook = xlsxwriter.Workbook(temp_file.name)
    worksheet = workbook.add_worksheet("Rekap Absensi")

    header_format = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1})
    headers = ['Foto', 'Nama', 'Jabatan', 'Divisi', 'Tanggal', 'Masuk', 'Pulang', 'Keterangan', 'Terlambat']
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)

    worksheet.set_column(0, 0, 18)
    worksheet.set_column(1, 1, 25)
    worksheet.set_column(2, 2, 20)
    worksheet.set_column(3, 3, 20)
    worksheet.set_column(4, 4, 12)
    worksheet.set_column(5, 6, 12)
    worksheet.set_column(7, 7, 14)
    worksheet.set_column(8, 8, 16)

    for i, row in enumerate(data, start=1):
        worksheet.write(i, 1, row['nama'])
        worksheet.write(i, 2, row['jabatan'])
        worksheet.write(i, 3, row['divisi'])
        worksheet.write(i, 4, str(row['tanggal']))
        worksheet.write(i, 5, str(row.get('waktu') or '-'))
        worksheet.write(i, 6, str(row.get('waktu_pulang') or '-'))
        worksheet.write(i, 7, row['keterangan'])
        worksheet.write(i, 8, row.get('terlambat', 0) or 0)

        if row['foto']:
            img_path = os.path.join('static', row['foto'])
            if os.path.exists(img_path):
                worksheet.set_row(i, 80)
                worksheet.insert_image(i, 0, img_path, {
                    'x_scale': 0.2,
                    'y_scale': 0.2,
                    'x_offset': 6,
                    'y_offset': 6
                })

    # Ringkasan
    start_row = len(data) + 2
    worksheet.write(start_row, 0, "Rekapitulasi:", workbook.add_format({'bold': True}))
    worksheet.write(start_row + 1, 1, "Total Hadir")
    worksheet.write(start_row + 1, 2, total_hadir)
    worksheet.write(start_row + 2, 1, "Total Izin")
    worksheet.write(start_row + 2, 2, total_izin)
    worksheet.write(start_row + 3, 1, "Total Sakit")
    worksheet.write(start_row + 3, 2, total_sakit)
    worksheet.write(start_row + 4, 1, "Total Terlambat (menit)")
    worksheet.write(start_row + 4, 2, total_terlambat)
    worksheet.write(start_row + 5, 1, "Total Jam Kerja")
    worksheet.write(start_row + 5, 2, f"{jam_total} jam {menit_total} menit")

    workbook.close()

    return send_file(
        temp_file.name,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        download_name=f"rekap_{nama_karyawan}_{bulan}.xlsx",
        as_attachment=True
    )



@app.route('/export_pdf')
def export_pdf():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    nama_karyawan = request.args.get('nama')
    bulan = request.args.get('bulan')
    if not nama_karyawan or not bulan:
        return "<script>alert('Parameter nama dan bulan wajib diisi!');window.history.back();</script>"

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT * FROM absensi 
        WHERE nama = %s AND TO_CHAR(tanggal, 'YYYY-MM') = %s
        ORDER BY tanggal, waktu
    """, (nama_karyawan, bulan))
    data = cursor.fetchall()
    cursor.close()
    conn.close()

    total_hadir = sum(1 for row in data if row['keterangan'].lower() == 'hadir')
    total_izin = sum(1 for row in data if row['keterangan'].lower() == 'izin')
    total_sakit = sum(1 for row in data if row['keterangan'].lower() == 'sakit')
    total_terlambat = sum(row.get('terlambat', 0) or 0 for row in data)

    total_menit_kerja = 0
    for row in data:
        waktu = row.get('waktu')
        waktu_pulang = row.get('waktu_pulang')
        if waktu and waktu_pulang:
            try:
                fmt = "%H:%M:%S" if len(waktu) > 5 else "%H:%M"
                start = datetime.strptime(str(waktu), fmt)
                end = datetime.strptime(str(waktu_pulang), fmt)
                selisih = (end - start).total_seconds() / 60
                if selisih > 0:
                    total_menit_kerja += selisih
            except Exception:
                pass

    jam = int(total_menit_kerja // 60)
    menit = int(total_menit_kerja % 60)

    class PDF(FPDF):
        def header(self):
            logo_path = os.path.join('static', 'assets', 'log.png')
            if os.path.exists(logo_path):
                self.image(logo_path, 10, 8, 25)
            self.set_font('Arial', 'B', 14)
            self.cell(0, 10, f"Laporan Absensi Bulan {bulan} - {nama_karyawan}", ln=True, align='C')
            self.ln(10)
            # Header tabel
            self.set_font("Arial", 'B', 10)
            headers = ["Foto", "Nama", "Jabatan", "Divisi", "Tanggal", "Masuk", "Pulang", "Keterangan", "Terlambat"]
            col_widths = [30, 50, 25, 25, 25, 20, 20, 30, 25]
            for i, h in enumerate(headers):
                self.cell(col_widths[i], 10, h, 1, align='C')
            self.ln()

    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)
    pdf.set_font("Arial", size=9)
    col_widths = [30, 50, 25, 25, 25, 20, 20, 30, 25]
    row_height = 30

    for row in data:
        if pdf.get_y() + row_height > 200:
            pdf.add_page()

        y = pdf.get_y()
        x = pdf.get_x()

        # Foto
        if row['foto']:
            img_path = os.path.join('static', row['foto'])
            if os.path.exists(img_path):
                pdf.cell(col_widths[0], row_height, "", 1)
                pdf.image(img_path, x=x+1, y=y+1, w=col_widths[0]-2, h=row_height-2)
            else:
                pdf.cell(col_widths[0], row_height, "Foto\nTidak Ada", 1)
        else:
            pdf.cell(col_widths[0], row_height, "Foto\nTidak Ada", 1)

        pdf.set_xy(x + col_widths[0], y)
        pdf.cell(col_widths[1], row_height, str(row['nama'])[:40], 1)
        pdf.cell(col_widths[2], row_height, str(row['jabatan'])[:20], 1)
        pdf.cell(col_widths[3], row_height, str(row['divisi'])[:20], 1)
        pdf.cell(col_widths[4], row_height, str(row['tanggal']), 1)
        pdf.cell(col_widths[5], row_height, str(row['waktu'] or '-'), 1)
        pdf.cell(col_widths[6], row_height, str(row['waktu_pulang'] or '-'), 1)
        pdf.cell(col_widths[7], row_height, str(row['keterangan']), 1)
        pdf.cell(col_widths[8], row_height, str(row.get('terlambat', 0) or 0), 1)
        pdf.ln(row_height)

    # Ringkasan
    if pdf.get_y() + 40 > 200:
        pdf.add_page()

    pdf.ln(5)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(0, 10, "Rekapitulasi Bulanan:", ln=True)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 8, f"Total Hadir: {total_hadir}", ln=True)
    pdf.cell(0, 8, f"Total Izin: {total_izin}", ln=True)
    pdf.cell(0, 8, f"Total Sakit: {total_sakit}", ln=True)
    pdf.cell(0, 8, f"Total Terlambat (menit): {total_terlambat}", ln=True)
    pdf.cell(0, 8, f"Total Jam Kerja: {jam} jam {menit} menit", ln=True)

    response = Response(pdf.output(dest='S').encode('latin-1'), mimetype='application/pdf')
    filename = f"rekap_{nama_karyawan}_{bulan}.pdf"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

    
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = ''
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)  # tambahkan RealDictCursor agar key 'password' bisa dibaca

        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()

        print("User dari DB:", user)

        cursor.close()
        conn.close()

        if user:
            stored_hash = user['password']
            print("Hash dari DB:", stored_hash)

            if bcrypt.checkpw(password, stored_hash.encode('utf-8')):
                print("Password cocok, login berhasil")
                session['logged_in'] = True
                session['username'] = user['username']
                session['role'] = user['role']

                if user['role'] == 'superadmin':
                    return redirect(url_for('superadmin_dashboard'))
                elif user['role'] == 'admin':
                    return redirect(url_for('admin_dashboard'))
                else:
                    return redirect(url_for('home'))
            else:
                print("Password TIDAK cocok")
        else:
            print("User tidak ditemukan")

        error = "Username atau password salah!"

    return render_template('login.html', error=error)




@app.route('/superadmin', methods=['GET', 'POST'])
def superadmin_dashboard():
    if not session.get('logged_in') or session.get('role') not in ['admin', 'superadmin']:
        return redirect(url_for('login'))

    edit_user = None
    if request.method == 'POST':
        id = request.form.get('id')
        username = request.form['username']
        password = request.form['password']
        role = request.form['role'].lower()  # ✅ pastikan huruf kecil

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if id:
            cursor.execute("SELECT username, password FROM users WHERE id=%s", (id,))
            old = cursor.fetchone()

            if username != old['username']:
                cursor.execute("SELECT username FROM users WHERE username=%s", (username,))
                if cursor.fetchone():
                    cursor.close()
                    conn.close()
                    return "<script>alert('Username sudah digunakan.');window.history.back();</script>"

            if password:
                hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode()
            else:
                hashed = old['password']

            cursor.execute(
                "UPDATE users SET username=%s, password=%s, role=%s WHERE id=%s",
                (username, hashed, role, id)
            )
        else:
            cursor.execute("SELECT username FROM users WHERE username=%s", (username,))
            if cursor.fetchone():
                cursor.close()
                conn.close()
                return "<script>alert('Username sudah digunakan.');window.history.back();</script>"

            hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode()
            cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                (username, hashed, role)
            )

        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('superadmin_dashboard'))

    delete_username = request.args.get('delete')
    if delete_username:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE username=%s", (delete_username,))
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('superadmin_dashboard'))

    edit_id = request.args.get('id')
    if edit_id:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE id=%s", (edit_id,))
        edit_user = cursor.fetchone()
        cursor.close()
        conn.close()

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT * FROM users ORDER BY username ASC")
    users = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('superadmin_dashboard.html', username=session['username'], users=users, edit_user=edit_user)



@app.route('/delete_user/<username>')
def delete_user(username):
    if not session.get('logged_in') or session.get('role') not in ['admin', 'superadmin']:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE username=%s", (username,))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('superadmin_dashboard'))






@app.route('/data_absensi', methods=['GET', 'POST'])
def data_absensi():
    if session.get('role') != 'superadmin' and not session.get('absensi_verified'):
        flash("Silakan verifikasi password terlebih dahulu.", "warning")
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # --- Proses Tambah/Edit ---
    if request.method == 'POST':
        old_id = int(request.form.get('old_id', 0))
        new_id = int(request.form.get('id', 0))
        nama = request.form.get('nama', '')
        jabatan = request.form.get('jabatan', '')
        divisi = request.form.get('divisi', '')
        tanggal = request.form.get('tanggal', '')
        waktu = request.form.get('waktu') or None  # Boleh kosong
        waktu_pulang = request.form.get('waktu_pulang') or None  # Boleh kosong
        keterangan = request.form.get('keterangan', '')

        fotoPath = ''
        if new_id > 0:
            cursor.execute("SELECT foto FROM absensi WHERE id=%s", (new_id,))
            fotoRow = cursor.fetchone()
            if fotoRow:
                fotoPath = fotoRow['foto']

        if old_id > 0:
            cursor.execute(
                """
                UPDATE absensi 
                SET nama=%s, jabatan=%s, divisi=%s, 
                    tanggal=%s, waktu=%s, waktu_pulang=%s, keterangan=%s, foto=%s 
                WHERE id=%s
                """,
                (nama, jabatan, divisi, tanggal, waktu, waktu_pulang, keterangan, fotoPath, old_id)
            )
        else:
            cursor.execute(
                """
                INSERT INTO absensi 
                    (nama, jabatan, divisi, tanggal, waktu, waktu_pulang, keterangan, foto) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (nama, jabatan, divisi, tanggal, waktu, waktu_pulang, keterangan, fotoPath)
            )
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('data_absensi'))

    # --- Proses Hapus ---
    delete_id = request.args.get('delete')
    if delete_id:
        cursor.execute("DELETE FROM absensi WHERE id=%s", (delete_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('data_absensi'))

    # --- Ambil data untuk edit ---
    editData = None
    edit_id = request.args.get('edit')
    if edit_id:
        cursor.execute("SELECT * FROM absensi WHERE id=%s", (edit_id,))
        editData = cursor.fetchone()

    # --- Filter ---
    filter_divisi = request.args.get('filter_divisi', '')
    filter_nama = request.args.get('filter_nama', '')
    filter_bulan = request.args.get('filter_bulan', '')  # format: YYYY-MM

    where = []
    params = []

    if filter_divisi:
        where.append("divisi ILIKE %s")
        params.append(f"%{filter_divisi}%")
    if filter_nama:
        where.append("nama ILIKE %s")
        params.append(f"%{filter_nama}%")
    if filter_bulan:
        where.append("TO_CHAR(tanggal, 'YYYY-MM') = %s")
        params.append(filter_bulan)

    sql = "SELECT * FROM absensi"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY tanggal DESC, waktu DESC"

    cursor.execute(sql, params)
    absensi_list = cursor.fetchall()

    # Ambil daftar pengguna untuk form dinamis
    cursor.execute("SELECT nama, jabatan, divisi FROM pengguna ORDER BY nama")
    pengguna_list = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'data_absensi.html',
        username=session['username'],
        absensi=absensi_list,
        editData=editData,
        filter_divisi=filter_divisi,
        filter_nama=filter_nama,
        filter_bulan=filter_bulan,
        pengguna_list=pengguna_list
    )




@app.route('/verify_absensi_password', methods=['POST'])
def verify_absensi_password():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    # Ambil password yang diinput
    password_input = request.form['password'].encode('utf-8')
    username = session.get('username')

    # Ambil user dari database PostgreSQL
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # --- Proses Tambah/Edit ---
    if request.method == 'POST':
        old_nama = request.form.get('old_nama', '')
        nama = request.form.get('nama', '')
        jabatan = request.form.get('jabatan', '')
        divisi = request.form.get('divisi', '')
        foto_file = request.files.get('foto')

        if nama and jabatan and divisi:
            if nama != old_nama:
                cursor.execute("SELECT nama FROM pengguna WHERE nama=%s", (nama,))
                if cursor.fetchone():
                    cursor.close()
                    conn.close()
                    return "<script>alert('Nama sudah digunakan.');window.history.back();</script>"

            foto_filename = None
            encoding_json = None

            if foto_file and foto_file.filename != '':
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                filename_secure = secure_filename(foto_file.filename)
                foto_filename = f"{timestamp}_{filename_secure}"
                foto_path = os.path.join('static/foto_pengguna', foto_filename)
                foto_file.save(foto_path)

                image = face_recognition.load_image_file(foto_path)
                encodings = face_recognition.face_encodings(image)

                if encodings:
                    encoding_np = encodings[0]
                    encoding_json = json.dumps(encoding_np.tolist())
                else:
                    os.remove(foto_path)
                    return "<script>alert('Wajah tidak terdeteksi pada foto.');window.history.back();</script>"

            if old_nama:
                if not foto_filename or not encoding_json:
                    cursor.execute("SELECT foto, encoding_wajah FROM pengguna WHERE nama=%s", (old_nama,))
                    old_data = cursor.fetchone()
                    if old_data:
                        if not foto_filename:
                            foto_filename = old_data['foto']
                        if not encoding_json:
                            encoding_json = old_data['encoding_wajah']

                cursor.execute(
                    "UPDATE pengguna SET nama=%s, jabatan=%s, divisi=%s, encoding_wajah=%s, foto=%s WHERE nama=%s",
                    (nama, jabatan, divisi, encoding_json, foto_filename, old_nama)
                )
            else:
                cursor.execute(
                    "INSERT INTO pengguna (nama, jabatan, divisi, encoding_wajah, foto) VALUES (%s, %s, %s, %s, %s)",
                    (nama, jabatan, divisi, encoding_json, foto_filename)
                )
            conn.commit()
        return redirect(url_for('data_pengguna'))

    # --- Proses Hapus ---
    delete_nama = request.args.get('delete')
    if delete_nama:
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

    # --- Filter Nama ---
    filter_nama = request.args.get('filter_nama', '')
    if filter_nama:
        cursor.execute("""
            SELECT id, nama, jabatan, divisi, foto 
            FROM pengguna 
            WHERE nama ILIKE %s 
            ORDER BY nama ASC
        """, (f"%{filter_nama}%",))
    else:
        cursor.execute("SELECT id, nama, jabatan, divisi, foto FROM pengguna ORDER BY nama ASC")
    users = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'data_pengguna.html',
        username=session['username'],
        users=users,
        editData=editData,
        pesan_sukses=pesan_sukses,
        filter_nama=filter_nama  # <--- penting untuk dikirim ke template
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

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cursor.execute(
        "SELECT encoding_wajah FROM pengguna WHERE nama=%s AND kelas=%s",
        (session['username'], session.get('kelas'))
    )
    data = cursor.fetchone()

    cursor.close()
    conn.close()

    wajah_terdaftar = bool(data and data['encoding_wajah'])

    return render_template(
        'siswa_dashboard.html',
        nama=session['username'],
        kelas=session.get('kelas'),
        wajah_terdaftar=wajah_terdaftar
    )


@app.route('/')
@app.route('/index')
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

        # Ekstrak encoding wajah
        encodings_absen = face_recognition.face_encodings(img_np)
        if not encodings_absen:
            raise Exception("Wajah tidak terdeteksi")
        vector_absen = encodings_absen[0]

        # Ambil data dari DB
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT nama, jabatan, divisi, encoding_wajah FROM pengguna WHERE encoding_wajah IS NOT NULL")
        rows = cursor.fetchall()

        match_found = False
        nama = jabatan = divisi = None

        for row in rows:
            vector_db = np.array(json.loads(row['encoding_wajah']))
            if face_recognition.compare_faces([vector_db], vector_absen, tolerance=0.5)[0]:
                nama, jabatan, divisi = row['nama'], row['jabatan'], row['divisi']
                match_found = True
                break

        if not match_found:
            return "<script>alert('Wajah tidak dikenali!');window.history.back();</script>"

        # Cek apakah sudah absen hari ini
        tanggal = datetime.now().strftime("%Y-%m-%d")
        waktu = datetime.now().strftime("%H:%M:%S")
        cursor.execute("SELECT * FROM absensi WHERE nama = %s AND tanggal = %s", (nama, tanggal))
        absen_hari_ini = cursor.fetchone()

        if absen_hari_ini:
            return "<script>alert('Kamu sudah absen masuk hari ini!');window.history.back();</script>"

        # Simpan foto
        foto_folder = os.path.join('static', 'bukti_absen_karyawan')
        os.makedirs(foto_folder, exist_ok=True)
        filename = f"{nama}_{tanggal}_{waktu.replace(':', '-')}.jpg".replace(' ', '_')
        foto_path = os.path.join(foto_folder, filename)
        img.save(foto_path)
        foto_db = os.path.join('bukti_absen_karyawan', filename).replace("\\", "/")

        # Simpan absen masuk
        jam_masuk = datetime.strptime("08:00:00", "%H:%M:%S")
        waktu_absen = datetime.strptime(waktu, "%H:%M:%S")
        selisih = (waktu_absen - jam_masuk).total_seconds() / 60
        terlambat = max(int(selisih - 30), 0)

        keterangan_input = request.form.get('keterangan', 'Hadir').strip().capitalize()
        if keterangan_input not in ['Hadir', 'Sakit', 'Izin', 'Alpha']:
            keterangan_input = 'Hadir'

        cursor.execute("""
            INSERT INTO absensi (nama, jabatan, divisi, tanggal, waktu, keterangan, foto, terlambat)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (nama, jabatan, divisi, tanggal, waktu, keterangan_input, foto_db, terlambat))

        conn.commit()
        cursor.close()
        conn.close()

        session['absen_nama'] = nama
        session['absen_jabatan'] = jabatan
        session['absen_divisi'] = divisi
        session['absen_tanggal'] = tanggal
        session['absen_waktu'] = waktu
        session['absen_terlambat'] = terlambat

        return redirect(url_for('absen_sukses'))

    except Exception as e:
        print("Error absen karyawan:", e)
        return "<script>alert('Gagal memproses absen: {}');window.history.back();</script>".format(str(e))


@app.route("/absen_pulang", methods=["POST"])
def absen_pulang():
    encoding_wajah = request.form.get("encoding_wajah_absen")
    if not encoding_wajah:
        return "<script>alert('Data wajah tidak ditemukan!');window.history.back();</script>"

    try:
        header, encoded = encoding_wajah.split(",", 1)
        img_bytes = base64.b64decode(encoded)
        img = Image.open(BytesIO(img_bytes)).convert("RGB")
        img_np = np.array(img)
        img_np = np.ascontiguousarray(img_np, dtype=np.uint8)

        encodings_absen = face_recognition.face_encodings(img_np)
        if not encodings_absen:
            raise Exception("Wajah tidak terdeteksi")
        vector_absen = encodings_absen[0]

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT nama, encoding_wajah FROM pengguna WHERE encoding_wajah IS NOT NULL")
        users = cursor.fetchall()

        nama = None
        for user in users:
            vector_db = np.array(json.loads(user["encoding_wajah"]))
            if face_recognition.compare_faces([vector_db], vector_absen, tolerance=0.5)[0]:
                nama = user["nama"]
                break

        if not nama:
            return "<script>alert('Wajah tidak dikenali!');window.history.back();</script>"

        tanggal = datetime.now().strftime("%Y-%m-%d")
        waktu_pulang = datetime.now().strftime("%H:%M:%S")

        # Cek apakah sudah absen masuk
        cursor.execute("SELECT * FROM absensi WHERE nama = %s AND tanggal = %s", (nama, tanggal))
        absen = cursor.fetchone()

        if not absen:
            return "<script>alert('Kamu belum absen masuk hari ini!');window.history.back();</script>"

        if absen['waktu_pulang']:
            return "<script>alert('Kamu sudah absen pulang hari ini!');window.history.back();</script>"

        # Simpan waktu pulang
        cursor.execute("""
            UPDATE absensi SET waktu_pulang = %s WHERE nama = %s AND tanggal = %s
        """, (waktu_pulang, nama, tanggal))

        conn.commit()
        cursor.close()
        conn.close()

        flash("Absensi pulang berhasil!", "success")
        return redirect(url_for("home"))

    except Exception as e:
        print("Error absen pulang:", e)
        return "<script>alert('Gagal memproses absen pulang: {}');window.history.back();</script>".format(str(e))




@app.route('/absen_sukses')
def absen_sukses():
    nama = session.pop('absen_nama', '')
    jabatan = session.pop('absen_jabatan', '')
    divisi = session.pop('absen_divisi', '')
    tanggal = session.pop('absen_tanggal', '')
    waktu = session.pop('absen_waktu', '')
    terlambat = session.pop('absen_terlambat', 0)  # ← tambahkan ini

    return render_template(
        'absen_sukses.html',
        nama=nama,
        jabatan=jabatan,
        divisi=divisi,
        tanggal=tanggal,
        waktu=waktu,
        terlambat=terlambat
    )


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


