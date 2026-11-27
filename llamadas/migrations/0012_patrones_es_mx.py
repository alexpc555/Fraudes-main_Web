from django.db import migrations


PATRONES = [
    # Solicitud de credenciales, datos y códigos
    ('solicitud_nip', 'Solicitud de NIP', 'nip', 'ALTA', 35),
    ('solicitud_nip', 'Solicitud de NIP', 'tu nip', 'ALTA', 35),
    ('solicitud_nip', 'Solicitud de NIP', 'numero de nip', 'ALTA', 35),
    ('solicitud_contrasenas', 'Solicitud de contraseñas', 'tu contraseña', 'ALTA', 35),
    ('solicitud_contrasenas', 'Solicitud de contraseñas', 'tu clave', 'ALTA', 35),
    ('solicitud_contrasenas', 'Solicitud de contraseñas', 'clave de tu banca', 'ALTA', 35),
    ('solicitud_codigos_verificacion', 'Solicitud de códigos de verificación', 'codigo que te llego por sms', 'ALTA', 35),
    ('solicitud_codigos_verificacion', 'Solicitud de códigos de verificación', 'codigo que te acaba de llegar', 'ALTA', 35),
    ('solicitud_codigos_verificacion', 'Solicitud de códigos de verificación', 'token bancario', 'ALTA', 35),
    ('solicitud_codigos_verificacion', 'Solicitud de códigos de verificación', 'codigo de un solo uso', 'ALTA', 35),
    ('solicitud_cvv', 'Solicitud de CVV', 'cvv', 'ALTA', 35),
    ('solicitud_cvv', 'Solicitud de CVV', 'codigo de seguridad de tu tarjeta', 'ALTA', 35),
    ('solicitud_datos_bancarios', 'Solicitud de datos bancarios', 'clabe interbancaria', 'ALTA', 30),
    ('solicitud_datos_bancarios', 'Solicitud de datos bancarios', 'numero de tarjeta', 'ALTA', 30),
    ('solicitud_datos_bancarios', 'Solicitud de datos bancarios', 'datos de tu tarjeta', 'ALTA', 30),
    ('solicitud_datos_bancarios', 'Solicitud de datos bancarios', 'datos de tu cuenta', 'ALTA', 30),
    # Acciones que suelen acompañar la ingeniería social
    ('transferencias', 'Solicitud de transferencia o depósito', 'haz una transferencia', 'CRITICA', 40),
    ('transferencias', 'Solicitud de transferencia o depósito', 'transfiere a una cuenta segura', 'CRITICA', 40),
    ('transferencias', 'Solicitud de transferencia o depósito', 'deposita para liberar', 'ALTA', 30),
    ('transferencias', 'Solicitud de transferencia o depósito', 'paga para desbloquear', 'ALTA', 30),
    ('acceso_remoto', 'Instalación o acceso remoto', 'descarga esta app', 'ALTA', 30),
    ('acceso_remoto', 'Instalación o acceso remoto', 'instala esta aplicacion', 'ALTA', 30),
    ('acceso_remoto', 'Instalación o acceso remoto', 'comparte tu pantalla', 'CRITICA', 40),
    ('acceso_remoto', 'Instalación o acceso remoto', 'activa el acceso remoto', 'CRITICA', 40),
    ('acceso_remoto', 'Instalación o acceso remoto', 'abre el enlace', 'ALTA', 25),
    # Suplantación y urgencia: señales de apoyo, no condenas por sí solas
    ('suplantacion', 'Suplantación de autoridad o empresa', 'hablo del banco', 'MEDIA', 10),
    ('suplantacion', 'Suplantación de autoridad o empresa', 'soy del area de seguridad', 'MEDIA', 10),
    ('suplantacion', 'Suplantación de autoridad o empresa', 'llamo del sat', 'MEDIA', 10),
    ('suplantacion', 'Suplantación de autoridad o empresa', 'soy de la fiscalia', 'MEDIA', 10),
    ('urgencia', 'Presión para actuar de inmediato', 'ahorita mismo', 'MEDIA', 8),
    ('urgencia', 'Presión para actuar de inmediato', 'antes de que termine el dia', 'MEDIA', 8),
]


def agregar_patrones(apps, schema_editor):
    Patron = apps.get_model('llamadas', 'PatronFraude')
    for codigo, nombre, patron, gravedad, puntuacion in PATRONES:
        Patron.objects.update_or_create(
            patron=patron,
            defaults={
                'codigo': codigo,
                'nombre': nombre,
                'descripcion': nombre,
                'gravedad': gravedad,
                'puntuacion': puntuacion,
                'activo': True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [('llamadas', '0011_patrones_lenguaje_variado')]
    operations = [migrations.RunPython(agregar_patrones, migrations.RunPython.noop)]
