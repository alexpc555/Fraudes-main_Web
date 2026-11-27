from django.db import migrations


def agregar_patrones(apps, schema_editor):
    Patron = apps.get_model('llamadas', 'PatronFraude')
    nuevos = [
        ('transferencias', 'Solicitud de transferencia o depósito', 'mueve tu dinero a una cuenta segura', 'CRITICA', 40),
        ('transferencias', 'Solicitud de transferencia o depósito', 'desvia tus fondos', 'CRITICA', 40),
        ('transferencias', 'Solicitud de transferencia o depósito', 'paga para liberar', 'ALTA', 30),
        ('acceso_remoto', 'Instalación o acceso remoto', 'comparte tu pantalla', 'CRITICA', 40),
        ('acceso_remoto', 'Instalación o acceso remoto', 'descarga esta aplicacion', 'ALTA', 30),
        ('acceso_remoto', 'Instalación o acceso remoto', 'permite el acceso remoto', 'CRITICA', 40),
        ('suplantacion', 'Suplantación de autoridad o empresa', 'operacion preventiva', 'MEDIA', 15),
        ('suplantacion', 'Suplantación de autoridad o empresa', 'validar tu identidad', 'MEDIA', 15),
    ]
    for codigo, nombre, patron, gravedad, puntuacion in nuevos:
        Patron.objects.update_or_create(patron=patron, defaults={
            'codigo': codigo, 'nombre': nombre, 'descripcion': nombre,
            'gravedad': gravedad, 'puntuacion': puntuacion, 'activo': True,
        })


class Migration(migrations.Migration):
    dependencies = [('llamadas', '0010_patronfraude')]
    operations = [migrations.RunPython(agregar_patrones, migrations.RunPython.noop)]
