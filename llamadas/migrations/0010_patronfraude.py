from django.db import migrations, models


PATRONES = [
    ('credenciales', 'Solicitud de NIP o PIN', 'nip', 'ALTA', 35),
    ('credenciales', 'Solicitud de NIP o PIN', 'pin', 'ALTA', 35),
    ('credenciales', 'Solicitud de contraseña', 'contraseña', 'ALTA', 35),
    ('credenciales', 'Solicitud de contraseña', 'clave de acceso', 'ALTA', 35),
    ('credenciales', 'Solicitud de contraseña', 'password', 'ALTA', 35),
    ('codigos', 'Solicitud de código de verificación', 'codigo de verificacion', 'CRITICA', 40),
    ('codigos', 'Solicitud de código de verificación', 'codigo que te llego por sms', 'CRITICA', 40),
    ('codigos', 'Solicitud de código de verificación', 'token', 'CRITICA', 40),
    ('codigos', 'Solicitud de código de verificación', 'otp', 'CRITICA', 40),
    ('codigos', 'Solicitud de código de verificación', 'código de seguridad', 'CRITICA', 40),
    ('tarjeta', 'Solicitud de CVV o datos de tarjeta', 'cvv', 'ALTA', 35),
    ('tarjeta', 'Solicitud de CVV o datos de tarjeta', 'numero de tarjeta', 'ALTA', 35),
    ('datos_bancarios', 'Solicitud de datos bancarios', 'clabe', 'ALTA', 30),
    ('datos_bancarios', 'Solicitud de datos bancarios', 'numero de cuenta', 'ALTA', 30),
    ('datos_bancarios', 'Solicitud de datos bancarios', 'datos bancarios', 'ALTA', 30),
    ('transferencias', 'Solicitud de transferencia o depósito', 'transferencia', 'ALTA', 30),
    ('transferencias', 'Solicitud de transferencia o depósito', 'transfiere el dinero', 'ALTA', 35),
    ('transferencias', 'Solicitud de transferencia o depósito', 'haz un deposito', 'ALTA', 30),
    ('transferencias', 'Solicitud de transferencia o depósito', 'pago inmediato', 'ALTA', 30),
    ('transferencias', 'Solicitud de transferencia o depósito', 'compra tarjetas de regalo', 'ALTA', 35),
    ('transferencias', 'Solicitud de transferencia o depósito', 'mueve tu dinero a una cuenta segura', 'CRITICA', 40),
    ('transferencias', 'Solicitud de transferencia o depósito', 'desvia tus fondos', 'CRITICA', 40),
    ('transferencias', 'Solicitud de transferencia o depósito', 'paga para liberar', 'ALTA', 30),
    ('amenaza', 'Amenaza de bloqueo o consecuencia', 'se bloqueara tu cuenta', 'CRITICA', 40),
    ('amenaza', 'Amenaza de bloqueo o consecuencia', 'seras detenido', 'CRITICA', 40),
    ('amenaza', 'Amenaza de bloqueo o consecuencia', 'orden de aprehension', 'CRITICA', 40),
    ('amenaza', 'Amenaza de bloqueo o consecuencia', 'si no pagas', 'CRITICA', 40),
    ('urgencia', 'Presión para actuar de inmediato', 'ahora mismo', 'ALTA', 25),
    ('urgencia', 'Presión para actuar de inmediato', 'de inmediato', 'ALTA', 25),
    ('urgencia', 'Presión para actuar de inmediato', 'hoy mismo', 'ALTA', 25),
    ('secreto', 'Petición de secreto o aislamiento', 'no le digas a nadie', 'CRITICA', 35),
    ('secreto', 'Petición de secreto o aislamiento', 'mantenga esto en secreto', 'CRITICA', 35),
    ('secreto', 'Petición de secreto o aislamiento', 'no cuelgues', 'ALTA', 25),
    ('acceso_remoto', 'Instalación o acceso remoto', 'anydesk', 'CRITICA', 40),
    ('acceso_remoto', 'Instalación o acceso remoto', 'teamviewer', 'CRITICA', 40),
    ('acceso_remoto', 'Instalación o acceso remoto', 'instala esta aplicacion', 'CRITICA', 40),
    ('acceso_remoto', 'Instalación o acceso remoto', 'comparte tu pantalla', 'CRITICA', 40),
    ('acceso_remoto', 'Instalación o acceso remoto', 'descarga esta aplicacion', 'ALTA', 30),
    ('acceso_remoto', 'Instalación o acceso remoto', 'permite el acceso remoto', 'CRITICA', 40),
    ('enlaces', 'Enlace o sitio de captura', 'abre este enlace', 'ALTA', 30),
    ('enlaces', 'Enlace o sitio de captura', 'ingresa a este link', 'ALTA', 30),
    ('suplantacion', 'Suplantación de autoridad o empresa', 'somos del banco', 'MEDIA', 15),
    ('suplantacion', 'Suplantación de autoridad o empresa', 'somos de la fiscalia', 'ALTA', 25),
    ('suplantacion', 'Suplantación de autoridad o empresa', 'somos del sat', 'ALTA', 25),
    ('suplantacion', 'Suplantación de autoridad o empresa', 'operacion preventiva', 'MEDIA', 15),
    ('suplantacion', 'Suplantación de autoridad o empresa', 'validar tu identidad', 'MEDIA', 15),
    ('entrega', 'Fraude de paquete o entrega', 'paga el costo de envio', 'ALTA', 25),
]


def cargar_catalogo(apps, schema_editor):
    Patron = apps.get_model('llamadas', 'PatronFraude')
    for codigo, nombre, patron, gravedad, puntuacion in PATRONES:
        Patron.objects.update_or_create(
            patron=patron,
            defaults={'codigo': codigo, 'nombre': nombre, 'descripcion': nombre, 'gravedad': gravedad, 'puntuacion': puntuacion, 'activo': True},
        )
    Pregunta = apps.get_model('llamadas', 'PreguntaAsistente')
    guion = {
        'nombre': '¿Cuál es su nombre completo, área de trabajo y un número oficial al que podamos devolverle la llamada?',
        'institucion': '¿De qué institución se comunica y cómo podemos verificarlo llamando a su número oficial, sin usar el número desde el que nos llama?',
        'motivo': '¿Cuál es el motivo concreto de la llamada? Indique el trámite, folio o evento que podamos verificar por un canal independiente.',
        'solicita_datos_personales': '¿Qué información o acción está pidiendo exactamente? ¿Solicita datos personales, cuenta, NIP, contraseña, token o código SMS?',
        'solicita_pago': '¿Pide transferir, depositar, pagar, abrir un enlace, instalar una aplicación o mantener esto en secreto o hacerlo de inmediato? ¿A quién beneficia?',
    }
    for codigo, texto in guion.items():
        Pregunta.objects.filter(codigo=codigo).update(texto=texto)


class Migration(migrations.Migration):
    dependencies = [('llamadas', '0009_contactoconfianza_relacion')]
    operations = [
        migrations.CreateModel(
            name='PatronFraude',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo', models.CharField(db_index=True, max_length=80)),
                ('nombre', models.CharField(max_length=200)),
                ('patron', models.CharField(max_length=200, unique=True)),
                ('descripcion', models.TextField(blank=True, default='')),
                ('gravedad', models.CharField(choices=[('BAJA', 'Baja'), ('MEDIA', 'Media'), ('ALTA', 'Alta'), ('CRITICA', 'Crítica')], default='MEDIA', max_length=20)),
                ('puntuacion', models.PositiveSmallIntegerField(default=10)),
                ('activo', models.BooleanField(default=True)),
            ],
            options={'verbose_name': 'Patrón de fraude', 'verbose_name_plural': 'Patrones de fraude', 'ordering': ['codigo', 'patron']},
        ),
        migrations.RunPython(cargar_catalogo, migrations.RunPython.noop),
    ]
