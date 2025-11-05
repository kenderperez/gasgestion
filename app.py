from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_mysqldb import MySQL
from config import Config
from functools import wraps
import MySQLdb.cursors
import qrcode
import os
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
app = Flask(__name__)
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = '856212'  # o tu contraseña de root
app.config['MYSQL_DB'] = 'combustible_db'
app.config['MYSQL_PORT'] = 3307
app.secret_key = 'clave_secreta'
mysql = MySQL(app)

def crear_pdf_ficha(pdf_path, qr_image_path, ficha_data):
    """
    Crea un PDF de 5x10 cm con los datos de una ficha y su código QR.

    :param pdf_path: Ruta completa donde se guardará el nuevo PDF.
    :param qr_image_path: Ruta completa a la imagen del QR que se va a incrustar.
    :param ficha_data: Un diccionario con los datos de texto para el PDF.
    """
    # 1. Definir las dimensiones del PDF en centímetros
    pdf_width = 5 * cm
    pdf_height = 10 * cm

    # 2. Crear el objeto Canvas (el "lienzo" del PDF)
    c = canvas.Canvas(pdf_path, pagesize=(pdf_width, pdf_height))

    # --- Coordenadas en reportlab: (0,0) es la esquina INFERIOR izquierda ---

    # 3. Dibujar el Título
    c.setFont("Helvetica-Bold", 6)
    # Usamos drawCentredString para centrar el título fácilmente
    c.drawCentredString(pdf_width / 2, 9 * cm, "SISTEMA DE GESTION DE COMBUSTIBLE")

    # 4. Dibujar el Código QR
    try:
        print(qr_image_path)
        qr = ImageReader(qr_image_path)
        qr_size = 4 * cm # El QR tendrá 4x4 cm
        # Centramos el QR horizontalmente y lo posicionamos verticalmente
        c.drawImage(qr, (pdf_width - qr_size) / 2, 4.5 * cm, width=qr_size, height=qr_size, preserveAspectRatio=True)
    except Exception as e:
        print(f"Error al cargar la imagen del QR: {e}")


    # 5. Dibujar los datos de la ficha debajo del QR
    c.setFont("Helvetica", 8)
    text_y_start = 3.5 * cm
    line_height = 0.6 * cm
    left_margin = 0.5 * cm

    # Lista de datos a imprimir
    datos = ficha_data
    print(datos)

    # Escribir cada línea en el PDF
    current_y = text_y_start
    for clave, valor in datos.items():
        # Construimos la línea completa para escribir en el PDF
        linea_a_escribir = f"{clave}: {valor}"
        
        c.drawString(left_margin, current_y, linea_a_escribir)
        current_y -= line_height # Moverse hacia abajo para la siguiente línea
    # 6. Guardar el archivo PDF
    c.save()
    print(f"PDF guardado exitosamente en: {pdf_path}")



def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'loggedin' not in session:
            flash('Debes iniciar sesión primero')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        # Es crucial usar SHA2(password, 256) si así está almacenado en tu DB
        cur.execute("SELECT * FROM usuarios WHERE username=%s AND password=SHA2(%s,256)", (username, password))
        user = cur.fetchone()
        if user:
            session['loggedin'] = True
            session['username'] = user['username']
            flash('Bienvenido, ' + user['username'])
            return redirect(url_for('dashboard'))
        else:
            flash('Usuario o contraseña incorrectos')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada correctamente')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # 1. Resumen general: total de fichas y total de litros
    cur.execute("""
        SELECT
            COUNT(*) AS total_fichas,
            COALESCE(SUM(litros),0) AS total_litros
        FROM fichas
    """)
    resumen = cur.fetchone() or {'total_fichas': 0, 'total_litros': 0}

    # 2. Litros por tipo de vehículo
    cur.execute("""
        SELECT v.tipo AS vehiculo, COALESCE(SUM(f.litros),0) AS total_litros
        FROM fichas f
        JOIN vehiculos v ON f.vehiculo_id = v.id
        GROUP BY v.tipo
    """)
    litros_por_vehiculo = cur.fetchall() or []

    # 3. Fichas atendidas vs. Fichas por atender
    cur.execute("""
        SELECT
            SUM(CASE WHEN activo = FALSE THEN 1 ELSE 0 END) AS fichas_atendidas,
            SUM(CASE WHEN activo = TRUE THEN 1 ELSE 0 END) AS fichas_por_atender
        FROM fichas
    """)
    datos_grafico_fichas = cur.fetchone() or {'fichas_atendidas': 0, 'fichas_por_atender': 0}

    # NUEVA CONSULTA: Conteo de fichas por Tipo de Combustible
    cur.execute("""
        SELECT tipo_combustible, COUNT(*) AS conteo
        FROM fichas
        GROUP BY tipo_combustible
        ORDER BY conteo DESC
    """)
    tipos_combustible = cur.fetchall() or []

    # NUEVA CONSULTA: Conteo de fichas por Estación
    cur.execute("""
        SELECT estacion AS nombre_estacion, COUNT(*) AS conteo
        FROM fichas
        GROUP BY estacion
        ORDER BY conteo DESC
    """)
    estaciones = cur.fetchall() or []

    cur.close()

    return render_template(
        'dashboard.html',
        resumen=resumen,
        litros_por_vehiculo=litros_por_vehiculo,
        datos_grafico_fichas=datos_grafico_fichas,
        tipos_combustible=tipos_combustible,  # Pasamos los nuevos datos al template
        estaciones=estaciones             # Pasamos los nuevos datos al template
    )


@app.route('/')
@login_required
def index():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Obtener todas las fichas con información del vehículo y beneficiario
    cur.execute("""
        SELECT
            f.id,
            f.fecha,
            f.litros,
            f.activo,
            v.tipo AS tipo_vehiculo,
            v.marca_modelo AS marca_modelo,
            v.color AS color,
            v.placa AS placa,
            b.nombre AS nombre_beneficiario,
            b.tipo AS tipo_beneficiario,
            b.cedula AS cedula,
            b.telefono AS telefono,
            f.autoriza
        FROM fichas f
        JOIN vehiculos v ON f.vehiculo_id = v.id
        JOIN beneficiarios b ON f.beneficiario_id = b.id
        ORDER BY f.fecha DESC
    """)

    fichas = cur.fetchall() or []
    cur.close()
    return render_template('index.html', fichas=fichas)

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_ficha():
    if request.method == 'POST':
        # Datos de la ficha
        fecha = request.form['fecha']
        estacion = request.form['estacion']
        tipo_combustible = request.form['combustible']
        litros = request.form['litros']
        autoriza = request.form['autoriza']

        # Datos del beneficiario
        ben_nombre = request.form['beneficiario_nombre']
        ben_tipo = request.form['beneficiario_tipo']
        ben_cedula = request.form['beneficiario_cedula']
        ben_telefono = request.form['beneficiario_telefono']

        # Datos del vehículo
        veh_tipo = request.form['vehiculo_tipo']
        veh_marca_modelo = request.form['vehiculo_marca_modelo']
        veh_color = request.form['vehiculo_color']
        veh_placa = request.form['vehiculo_placa']

        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)


        # Insertar beneficiario si no existe
        cur.execute("""
            INSERT INTO beneficiarios (nombre, tipo, cedula, telefono)
            SELECT %s, %s, %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM beneficiarios WHERE cedula=%s
            )
        """, (ben_nombre, ben_tipo, ben_cedula, ben_telefono, ben_cedula))
        mysql.connection.commit()

        # Obtener id del beneficiario
        cur.execute("SELECT id FROM beneficiarios WHERE cedula=%s", (ben_cedula,))
        beneficiario_id = cur.fetchone()['id']

        # Insertar vehículo si no existe
        cur.execute("""
            INSERT INTO vehiculos (tipo, marca_modelo, color, placa)
            SELECT %s, %s, %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM vehiculos WHERE placa=%s
            )
        """, (veh_tipo, veh_marca_modelo, veh_color, veh_placa, veh_placa))
        mysql.connection.commit()

        # Obtener id del vehículo
        cur.execute("SELECT id FROM vehiculos WHERE placa=%s", (veh_placa,))
        vehiculo_id = cur.fetchone()['id']

        # Insertar ficha
        cur.execute("""
            INSERT INTO fichas (fecha, estacion, tipo_combustible, litros, autoriza, beneficiario_id, vehiculo_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (fecha, estacion, tipo_combustible, litros, autoriza, beneficiario_id, vehiculo_id))

        mysql.connection.commit()
        ficha_id_valor = cur.lastrowid
        cur.close()

       # --- INICIO DE LA LÓGICA DEL CÓDIGO QR ---

        # 1. Obtener el ID de la ficha que ACABAMOS de insertar.
        #    'lastrowid' es una propiedad del cursor que contiene el último ID autoincremental insertado.
        

        # 2. Construir la URL que contendrá el código QR.
        #    (En producción, cambia 'localhost:5000' por tu dominio público)
        url_para_qr = f"http://10.0.0.249:5000/buscarqr?ficha_id={ficha_id_valor}"
        # 3. Generar la imagen del QR. El método .make() es el más simple.
        qr_img = qrcode.make(url_para_qr)

        # 4. Guardar la imagen en el servidor con un nombre de archivo único.
        QR_CODE_DIR = os.path.join(app.root_path, 'qrcodes')
        qr_filename = f"ficha_{ficha_id_valor}.png"
        ruta_guardado = os.path.join(QR_CODE_DIR, qr_filename)
        qr_img.save(ruta_guardado)
        

          # --- Creación del PDF ---
        PDF_DIR = os.path.join(app.root_path, 'fichas_pdf')
        # 2. Preparar los datos para la función del PDF
        datos_para_pdf = {
            'FECHA': fecha,
            'BENEFICIARIO': ben_nombre,
            'CEDULA CI': ben_cedula,
            'NUM PLACA': veh_placa,
            'MARCA/MODELO': veh_marca_modelo,
            'COLOR': veh_color
        }
        qr_imagen_para_pdf = f"{QR_CODE_DIR}\{qr_filename}"
        # 3. Definir el nombre y la ruta de guardado del PDF
        pdf_filename = f"ficha_combustible_{ficha_id_valor}.pdf"
        pdf_ruta_guardado = os.path.join(PDF_DIR, pdf_filename)

        # 4. Llamar a la función que crea el PDF
        crear_pdf_ficha(pdf_ruta_guardado, qr_imagen_para_pdf, datos_para_pdf)

        # --- FIN DE LA LÓGICA DE GENERACIÓN DE ARCHIVOS ---


        flash('Ficha de combustible agregada correctamente')
        return redirect(url_for('index'))

    # Si llega por GET o después de un POST fallido, puede tener datos precargados
    # para el formulario.
    beneficiario_precargado = {
        'nombre': request.args.get('nombre', ''),
        'tipo': request.args.get('tipo', ''),
        'cedula': request.args.get('cedula', ''),
        'telefono': request.args.get('telefono', '')
    }
    return render_template('add.html', beneficiario_precargado=beneficiario_precargado)

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_ficha(id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Obtener la ficha por id
    cur.execute("SELECT * FROM fichas WHERE id=%s", (id,))
    ficha = cur.fetchone()

    # Obtener listas de beneficiarios y vehículos para el formulario
    cur.execute("SELECT * FROM beneficiarios")
    beneficiarios = cur.fetchall()
    cur.execute("SELECT * FROM vehiculos")
    vehiculos = cur.fetchall()

    if request.method == 'POST':
        fecha = request.form['fecha']
        estacion = request.form['estacion']
        tipo_combustible = request.form['tipo_combustible']
        beneficiario_id = request.form['beneficiario_id']
        vehiculo_id = request.form['vehiculo_id']
        litros = request.form['litros']
        autoriza = request.form['autoriza']

        cur.execute("""
            UPDATE fichas
            SET fecha=%s, estacion=%s, tipo_combustible=%s,
                beneficiario_id=%s, vehiculo_id=%s, litros=%s, autoriza=%s
            WHERE id=%s
        """, (fecha, estacion, tipo_combustible, beneficiario_id, vehiculo_id, litros, autoriza, id))

        mysql.connection.commit()
        cur.close()
        flash('Ficha actualizada correctamente')
        return redirect(url_for('index'))

    cur.close()
    return render_template('edit_ficha.html', ficha=ficha, beneficiarios=beneficiarios, vehiculos=vehiculos)

@app.route('/buscar', methods=['GET', 'POST'])
@login_required
def buscar_por_placa():
    resultados = []
    busqueda = ''
    if request.method == 'POST':
        busqueda = request.form['placa']
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cur.execute("""
            SELECT f.*, v.tipo AS tipo_vehiculo, v.marca_modelo, v.color, v.placa,
                   b.nombre AS nombre_beneficiario, b.tipo AS tipo_beneficiario,
                   b.cedula, b.telefono
            FROM fichas f
            JOIN vehiculos v ON f.vehiculo_id = v.id
            JOIN beneficiarios b ON f.beneficiario_id = b.id
            WHERE v.placa LIKE %s
            ORDER BY f.fecha DESC
        """, ('%' + busqueda + '%',))
        resultados = cur.fetchall()
        cur.close()
    return render_template('buscar_placa.html', resultados=resultados, busqueda=busqueda)

@app.route('/buscarqr', methods=['GET','POST'])
def buscar_por_ficha_id():
    ficha_id_str = request.args.get('ficha_id', '')
    resultados = []

    if ficha_id_str:
        try:
            ficha_id = int(ficha_id_str)
        except ValueError:
            flash('El ID de la ficha debe ser un número entero válido.', 'danger')
            return render_template('resultados_busqueda.html', resultados=resultados)

        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        # 1. Obtener los detalles de la ficha (tal como lo hacíamos antes)
        cur.execute("""
            SELECT
                f.*,
                f.activo,
                v.tipo AS tipo_vehiculo,
                v.marca_modelo,
                v.color,
                v.placa,
                b.nombre AS nombre_beneficiario,
                b.tipo AS tipo_beneficiario,
                b.cedula,
                b.telefono
            FROM fichas f
            JOIN vehiculos v ON f.vehiculo_id = v.id
            JOIN beneficiarios b ON f.beneficiario_id = b.id
            WHERE f.id = %s
            ORDER BY f.fecha DESC
        """, (ficha_id,))
        resultados = cur.fetchall()

        # 2. Si se encontró la ficha, actualizar su estado 'activo' a FALSE
        if resultados: # Si la lista de resultados no está vacía
            # Solo actualizamos si la ficha está actualmente activa
            if resultados[0]['activo'] == True: # asumimos que es una sola ficha por ID
                try:
                    cur.execute("""
                        UPDATE fichas
                        SET activo = FALSE
                        WHERE id = %s
                    """, (ficha_id,))
                    mysql.connection.commit() # ¡Importante! Confirmar la transacción
                    flash(f'El estado de la ficha ID {ficha_id} ha sido actualizado a inactivo.', 'success')

                    # Opcional: Si quieres que el resultado mostrado ya refleje el cambio,
                    # puedes modificar el diccionario de resultados directamente
                    #resultados[0]['activo'] = False

                except MySQLdb.Error as e:
                    mysql.connection.rollback() # Si hay un error, revertir
                    flash(f'Error al actualizar la ficha ID {ficha_id}: {e}', 'danger')
            else:
                flash(f'La ficha ID {ficha_id} ya está inactiva.', 'info')
        else:
            flash(f'No se encontró ninguna ficha con el ID {ficha_id}.', 'warning')

        cur.close()

    return render_template('buscar.html', resultados=resultados, busqueda=ficha_id_str)

# --- Nueva ruta para buscar por cédula ---
@app.route('/buscar_cedula', methods=['GET', 'POST'])
@login_required
def buscar_cedula():
    beneficiario = None
    fichas_beneficiario = []
    cedula_buscada = ''

    if request.method == 'POST':
        cedula_buscada = request.form['cedula']
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        # Buscar el beneficiario
        cur.execute("SELECT * FROM beneficiarios WHERE cedula = %s", (cedula_buscada,))
        beneficiario = cur.fetchone()

        if beneficiario:
            # Si el beneficiario existe, buscar todas sus fichas
            cur.execute("""
                SELECT
                    f.id,
                    f.fecha,
                    f.litros,
                    f.activo,
                    v.tipo AS tipo_vehiculo,
                    v.marca_modelo AS marca_modelo,
                    v.color AS color,
                    v.placa AS placa,
                    f.autoriza
                FROM fichas f
                JOIN vehiculos v ON f.vehiculo_id = v.id
                WHERE f.beneficiario_id = %s
                ORDER BY f.fecha DESC
            """, (beneficiario['id'],))
            fichas_beneficiario = cur.fetchall()
            flash(f"Fichas encontradas para {beneficiario['nombre']} (C.I. {beneficiario['cedula']})", 'success')
        else:
            flash(f"No se encontró ningún beneficiario con la cédula {cedula_buscada}.", 'warning')

        cur.close()

    return render_template('buscar_cedula.html',
                           beneficiario=beneficiario,
                           fichas_beneficiario=fichas_beneficiario,
                           cedula_buscada=cedula_buscada)
# --- Fin nueva ruta ---


# Hay una ruta edit/<id> duplicada, la he comentado para evitar conflictos
# La ruta edit_ficha/<int:id> es la que parece estar en uso para editar fichas.
# @app.route('/edit/<id>', methods=['GET', 'POST'])
# @login_required
# def edit_registro(id):
#     cur = mysql.connection.cursor()
#     if request.method == 'POST':
#         vehiculo = request.form['vehiculo']
#         conductor = request.form['conductor']
#         litros = request.form['litros']
#         precio = request.form['precio']
#         fecha = request.form['fecha']
#         cur.execute("""UPDATE registros SET vehiculo=%s, conductor=%s, litros=%s, precio=%s, fecha=%s WHERE id=%s""",
#                     (vehiculo, conductor, litros, precio, fecha, id))
#         mysql.connection.commit()
#         flash('Registro actualizado correctamente')
#         return redirect(url_for('index'))
#     cur.execute("SELECT * FROM registros WHERE id=%s", (id,))
#     data = cur.fetchone()
#     cur.close()
#     return render_template('edit.html', registro=data)

@app.route('/delete_ficha/<int:id>', methods=['POST'])
@login_required
def delete_ficha(id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM fichas WHERE id=%s", (id,))
    mysql.connection.commit()
    cur.close()
    flash('Ficha eliminada correctamente')
    return redirect(url_for('index'))  # Cambia por la ruta que muestra todas las fichas


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)