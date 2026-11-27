import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def generar_identificador():
    return f"LL-{uuid.uuid4().hex[:10].upper()}"


def normalizar_numero_telefonico(numero_telefonico):
    numero = (numero_telefonico or '').strip()
    if not numero:
        return ''
    numero = numero.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    numero = numero.replace('+', '')
    if numero.lower() in {'oculto', 'anonimo', 'private', 'unknown', 'sin numero'}:
        return ''
    numero = re.sub(r'\D', '', numero)
    if len(numero) >= 12 and numero.startswith('52'):
        numero = numero[2:]
    elif len(numero) >= 11 and numero.startswith('1'):
        numero = numero[1:]
    return numero


def es_numero_oculto(numero_telefonico):
    numero = normalizar_numero_telefonico(numero_telefonico)
    if not numero:
        return True
    return len(numero) < 10 or len(set(numero)) == 1


class EstadoLlamada(models.TextChoices):
    PENDIENTE_DE_EVALUACION = 'PENDIENTE_DE_EVALUACION', 'Pendiente de evaluación'
    PERMITIDA = 'PERMITIDA', 'Permitida'
    RECHAZADA = 'RECHAZADA', 'Rechazada'
    EN_EVALUACION = 'EN_EVALUACION', 'En evaluación'
    FINALIZADA = 'FINALIZADA', 'Finalizada'


class Llamada(models.Model):
    identificador = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        default=generar_identificador,
    )
    usuario_protegido = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='llamadas_protegidas',
    )
    numero_telefonico = models.CharField(
        max_length=16,
        help_text='Número telefónico de origen.',
    )
    fecha_hora_recepcion = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(
        max_length=32,
        choices=EstadoLlamada.choices,
        default=EstadoLlamada.PENDIENTE_DE_EVALUACION,
    )
    resultado_evaluacion = models.CharField(
        max_length=255,
        blank=True,
        default='',
    )
    fecha_finalizacion = models.DateTimeField(null=True, blank=True)
    preparada_para_asistente_voz = models.BooleanField(default=False)

    class Meta:
        ordering = ['-fecha_hora_recepcion']
        verbose_name = 'Llamada'
        verbose_name_plural = 'Llamadas'

    def clean(self):
        numero = (self.numero_telefonico or '').strip()
        if not re.fullmatch(r'^\+?[0-9]{10,15}$', numero):
            raise ValidationError({'numero_telefonico': 'Ingrese un número telefónico válido.'})
        self.numero_telefonico = numero

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.estado == EstadoLlamada.FINALIZADA and not self.fecha_finalizacion:
            self.fecha_finalizacion = timezone.now()
        elif self.estado != EstadoLlamada.FINALIZADA:
            self.fecha_finalizacion = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.identificador} - {self.numero_telefonico}'


class ContactoConfianza(models.Model):
    usuario_protegido = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='contactos_confianza',
        null=True,
        blank=True,
    )
    nombre = models.CharField(max_length=150)
    numero_telefonico = models.CharField(max_length=18)
    correo_electronico = models.EmailField(blank=True, default='')
    relacion = models.CharField(max_length=120, blank=True, default='')
    descripcion = models.CharField(max_length=255, blank=True, default='')
    fecha_registro = models.DateTimeField(auto_now_add=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Contacto de confianza'
        verbose_name_plural = 'Contactos de confianza'

    def clean(self):
        numero = (self.numero_telefonico or '').strip()
        if not re.fullmatch(r'^\+?[0-9\s\-()]{10,18}$', numero):
            raise ValidationError({'numero_telefonico': 'Ingrese un número telefónico válido.'})
        if es_numero_oculto(numero):
            raise ValidationError({'numero_telefonico': 'Los números ocultos no pueden registrarse como contactos de confianza.'})
        self.numero_telefonico = numero

        if self.usuario_protegido_id:
            numero_normalizado = normalizar_numero_telefonico(self.numero_telefonico)
            for contacto in ContactoConfianza.objects.filter(usuario_protegido=self.usuario_protegido).exclude(pk=self.pk):
                if normalizar_numero_telefonico(contacto.numero_telefonico) == numero_normalizado:
                    raise ValidationError({'numero_telefonico': 'Este contacto ya está registrado para el usuario protegido.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def numero_normalizado(self):
        return normalizar_numero_telefonico(self.numero_telefonico)

    def __str__(self):
        return f'{self.nombre} - {self.numero_telefonico}'


class RelacionFamiliarAdultoMayor(models.Model):
    """Autoriza explícitamente a un Familiar para configurar el perfil protegido."""
    familiar = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='relaciones_adulto_mayor',
    )
    adulto_mayor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='relaciones_familiares_autorizadas',
    )
    autorizado = models.BooleanField(default=False)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='relaciones_familiares_registradas',
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['familiar', 'adulto_mayor'], name='relacion_familiar_adulto_unica'),
            models.UniqueConstraint(fields=['adulto_mayor'], condition=models.Q(autorizado=True), name='un_familiar_autorizado_por_adulto'),
            models.CheckConstraint(condition=~models.Q(familiar=models.F('adulto_mayor')), name='familiar_no_es_adulto_mayor'),
        ]
        verbose_name = 'Relación Familiar y Adulto mayor'
        verbose_name_plural = 'Relaciones Familiar y Adulto mayor'

    def __str__(self):
        return f'{self.familiar} → {self.adulto_mayor} ({"autorizado" if self.autorizado else "sin autorización"})'


class ConfiguracionAplicacion(models.Model):
    class Paso(models.TextChoices):
        BIENVENIDA = 'bienvenida', 'Bienvenida'
        PERMISOS = 'permisos', 'Permisos'
        CONTACTOS = 'contactos', 'Contactos de confianza'
        NOTIFICACIONES = 'notificaciones', 'Notificaciones'
        CONFIRMACION = 'confirmacion', 'Confirmación'

    adulto_mayor = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='configuracion_antifraude',
    )
    paso_actual = models.CharField(max_length=24, choices=Paso.choices, default=Paso.BIENVENIDA)
    notificaciones_habilitadas = models.BooleanField(default=False)
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='configuraciones_antifraude_actualizadas',
    )
    actualizado_en = models.DateTimeField(auto_now=True)
    completado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='configuraciones_antifraude_completadas',
    )
    completado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Configuración de aplicación'
        verbose_name_plural = 'Configuraciones de aplicación'

    def __str__(self):
        return f'Configuración de {self.adulto_mayor}'


class EstadoPermiso(models.Model):
    class Estado(models.TextChoices):
        CONCEDIDO = 'CONCEDIDO', 'Concedido'
        DENEGADO = 'DENEGADO', 'Denegado'
        PENDIENTE = 'PENDIENTE', 'Pendiente de solicitar'
        NO_DISPONIBLE = 'NO_DISPONIBLE', 'No disponible en el dispositivo'

    class Origen(models.TextChoices):
        CONFIGURACION_WEB = 'WEB', 'Configuración web'
        DISPOSITIVO_ANDROID = 'ANDROID', 'Dispositivo Android'

    configuracion = models.ForeignKey(
        ConfiguracionAplicacion,
        on_delete=models.CASCADE,
        related_name='permisos',
    )
    codigo = models.CharField(max_length=40)
    nombre = models.CharField(max_length=120)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE)
    esencial = models.BooleanField(default=True)
    origen = models.CharField(max_length=10, choices=Origen.choices, default=Origen.CONFIGURACION_WEB)
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='estados_permisos_actualizados',
    )
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['configuracion', 'codigo'], name='permiso_configuracion_unico'),
        ]
        ordering = ['esencial', 'nombre']
        verbose_name = 'Estado de permiso'
        verbose_name_plural = 'Estados de permisos'

    def __str__(self):
        return f'{self.nombre}: {self.get_estado_display()}'


class ConfiguracionNotificaciones(models.Model):
    adulto_mayor = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='configuracion_notificaciones',
    )
    familiar_responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notificaciones_configuradas',
    )
    contacto_confianza = models.ForeignKey(
        ContactoConfianza,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='configuraciones_notificacion',
    )
    activo = models.BooleanField(default=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración de notificaciones'
        verbose_name_plural = 'Configuraciones de notificaciones'

    def clean(self):
        if self.contacto_confianza_id and self.adulto_mayor_id:
            if self.contacto_confianza.usuario_protegido_id != self.adulto_mayor_id:
                raise ValidationError({'contacto_confianza': 'El contacto debe pertenecer al Adulto mayor configurado.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def contacto_valido(self):
        return bool(
            self.activo
            and self.contacto_confianza_id
            and self.contacto_confianza.activo
            and self.contacto_confianza.usuario_protegido_id == self.adulto_mayor_id
        )

    def __str__(self):
        return f'Notificaciones para {self.adulto_mayor}'


class EventoNotificacion(models.Model):
    class Tipo(models.TextChoices):
        RIESGO_ALTO = 'RIESGO_ALTO', 'Llamada de riesgo alto'
        LLAMADA_ACEPTADA = 'LLAMADA_ACEPTADA', 'Llamada de riesgo aceptada'

    class Canal(models.TextChoices):
        ANDROID_PUSH = 'ANDROID_PUSH', 'Notificación push Android'
        CORREO = 'CORREO', 'Correo electrónico'
        OTRO = 'OTRO', 'Otro canal'

    class Estado(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        ENVIADA = 'ENVIADA', 'Enviada'
        ERROR = 'ERROR', 'Error'

    llamada = models.ForeignKey(Llamada, on_delete=models.CASCADE, related_name='eventos_notificacion')
    configuracion = models.ForeignKey(
        ConfiguracionNotificaciones,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='eventos',
    )
    contacto_confianza = models.ForeignKey(
        ContactoConfianza,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='eventos_notificacion',
    )
    tipo = models.CharField(max_length=24, choices=Tipo.choices)
    canal = models.CharField(max_length=24, choices=Canal.choices, default=Canal.ANDROID_PUSH)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PENDIENTE)
    destinatario_nombre = models.CharField(max_length=150, blank=True, default='')
    destinatario_telefono = models.CharField(max_length=18, blank=True, default='')
    destinatario_correo = models.EmailField(blank=True, default='')
    numero_origen = models.CharField(max_length=18, blank=True, default='')
    nivel_riesgo = models.CharField(max_length=20)
    mensaje = models.TextField()
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_ultimo_intento = models.DateTimeField(null=True, blank=True)
    fecha_envio = models.DateTimeField(null=True, blank=True)
    detalle_envio = models.TextField(blank=True, default='')
    error_detalle = models.TextField(blank=True, default='')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['llamada', 'tipo', 'canal'], name='evento_notificacion_unico_por_llamada'),
        ]
        ordering = ['-fecha_creacion']
        verbose_name = 'Evento de notificación'
        verbose_name_plural = 'Eventos de notificación'

    def __str__(self):
        return f'{self.llamada.identificador} - {self.get_tipo_display()} ({self.get_estado_display()})'


class EstadoRegistroReporte(models.TextChoices):
    ACTIVO = 'ACTIVO', 'Activo'
    INACTIVO = 'INACTIVO', 'Inactivo'
    RESUELTO = 'RESUELTO', 'Resuelto'
    CERRADO = 'CERRADO', 'Cerrado'


class NumeroReportado(models.Model):
    numero_telefonico = models.CharField(max_length=18, unique=True)
    identidad_reportada = models.CharField(max_length=200, blank=True, default='')
    descripcion = models.TextField(blank=True, default='')
    tipo_incidente = models.CharField(max_length=80, blank=True, default='')
    cantidad_reportes = models.PositiveIntegerField(default=1)
    fecha_primer_reporte = models.DateTimeField(auto_now_add=True)
    fecha_ultimo_reporte = models.DateTimeField(auto_now=True)
    estado = models.CharField(
        max_length=32,
        choices=EstadoRegistroReporte.choices,
        default=EstadoRegistroReporte.ACTIVO,
    )

    class Meta:
        ordering = ['-fecha_ultimo_reporte']
        verbose_name = 'Número reportado'
        verbose_name_plural = 'Números reportados'

    def clean(self):
        numero = (self.numero_telefonico or '').strip()
        if not re.fullmatch(r'^\+?[0-9\s\-()]{10,18}$', numero):
            raise ValidationError({'numero_telefonico': 'Ingrese un número telefónico válido.'})
        if es_numero_oculto(numero):
            raise ValidationError({'numero_telefonico': 'Los números ocultos no pueden registrarse como reportados.'})
        self.numero_telefonico = numero

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def numero_normalizado(self):
        return normalizar_numero_telefonico(self.numero_telefonico)

    def __str__(self):
        return f'{self.numero_telefonico} ({self.cantidad_reportes} reportes)'


class EstadoConsultaNumero(models.TextChoices):
    REPORTADO = 'REPORTADO', 'Reportado'
    SIN_ANTECEDENTES = 'SIN_ANTECEDENTES', 'Sin antecedentes'
    ERROR = 'ERROR', 'Error de consulta'
    OCULTO = 'OCULTO', 'Número oculto'


class ResultadoConsultaNumero(models.Model):
    llamada = models.ForeignKey(
        Llamada,
        on_delete=models.CASCADE,
        related_name='consultas_numero',
        null=True,
        blank=True,
    )
    numero_telefonico = models.CharField(max_length=18)
    numero_reportado = models.ForeignKey(
        NumeroReportado,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='consultas_realizadas',
    )
    identidad_reportada = models.CharField(max_length=200, blank=True, default='')
    descripcion = models.TextField(blank=True, default='')
    tipo_incidente = models.CharField(max_length=80, blank=True, default='')
    cantidad_reportes = models.PositiveIntegerField(default=0)
    estado = models.CharField(
        max_length=32,
        choices=EstadoConsultaNumero.choices,
        default=EstadoConsultaNumero.SIN_ANTECEDENTES,
    )
    error_detalle = models.TextField(blank=True, default='')
    fecha_consulta = models.DateTimeField(auto_now_add=True)
    registrado_en_bd = models.BooleanField(default=False)

    class Meta:
        ordering = ['-fecha_consulta']
        verbose_name = 'Resultado de consulta de número'
        verbose_name_plural = 'Resultados de consulta de números'

    @property
    def numero_normalizado(self):
        return normalizar_numero_telefonico(self.numero_telefonico)

    def __str__(self):
        return f'{self.numero_telefonico} - {self.estado}'


class EstadoTranscripcion(models.TextChoices):
    PENDIENTE = 'PENDIENTE', 'Pendiente'
    PROCESANDO = 'PROCESANDO', 'Procesando'
    COMPLETADO = 'COMPLETADO', 'Completado'
    ERROR = 'ERROR', 'Error'
    AUDIO_NO_INTELIGIBLE = 'AUDIO_NO_INTELIGIBLE', 'Audio no inteligible'


class TranscripcionLlamada(models.Model):
    llamada = models.ForeignKey(
        Llamada,
        on_delete=models.CASCADE,
        related_name='transcripciones',
    )
    audio = models.FileField(upload_to='audios_llamadas/', blank=True, null=True)
    texto_transcrito = models.TextField(blank=True, default='')
    fecha_procesamiento = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(
        max_length=40,
        choices=EstadoTranscripcion.choices,
        default=EstadoTranscripcion.PENDIENTE,
    )
    duracion_audio = models.FloatField(default=0.0)
    confianza = models.FloatField(default=0.0, null=True, blank=True)
    orden = models.PositiveIntegerField(default=0)
    pregunta_asociada = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['orden', 'fecha_procesamiento']
        verbose_name = 'Transcripción de llamada'
        verbose_name_plural = 'Transcripciones de llamadas'

    def __str__(self):
        return f'{self.llamada.identificador} - {self.estado}'


class PreguntaAsistente(models.Model):
    codigo = models.CharField(max_length=80, unique=True)
    texto = models.CharField(max_length=255)
    orden = models.PositiveIntegerField(default=0)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ['orden', 'codigo']
        verbose_name = 'Pregunta del asistente'
        verbose_name_plural = 'Preguntas del asistente'

    def __str__(self):
        return f'{self.orden}. {self.texto}'


class RespuestaLlamada(models.Model):
    llamada = models.ForeignKey(
        Llamada,
        on_delete=models.CASCADE,
        related_name='respuestas_llamada',
    )
    pregunta = models.ForeignKey(
        PreguntaAsistente,
        on_delete=models.PROTECT,
        related_name='respuestas',
    )
    texto_respuesta = models.TextField(blank=True, default='')
    fecha_respuesta = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['pregunta__orden', 'fecha_respuesta']
        verbose_name = 'Respuesta de llamada'
        verbose_name_plural = 'Respuestas de llamadas'

    def __str__(self):
        return f'{self.llamada.identificador} - {self.pregunta.codigo}'


class EstadoConversacion(models.TextChoices):
    INICIADA = 'INICIADA', 'Iniciada'
    ESPERANDO_RESPUESTA = 'ESPERANDO_RESPUESTA', 'Esperando respuesta'
    PROCESANDO_AUDIO = 'PROCESANDO_AUDIO', 'Procesando audio'
    ANALIZANDO_RESPUESTA = 'ANALIZANDO_RESPUESTA', 'Analizando respuesta'
    FINALIZADA = 'FINALIZADA', 'Finalizada'
    INTERRUMPIDA = 'INTERRUMPIDA', 'Interrumpida'
    ERROR = 'ERROR', 'Error'


class SesionConversacion(models.Model):
    llamada = models.ForeignKey(
        Llamada,
        on_delete=models.CASCADE,
        related_name='sesiones_conversacion',
    )
    estado = models.CharField(
        max_length=30,
        choices=EstadoConversacion.choices,
        default=EstadoConversacion.INICIADA,
    )
    pregunta_actual = models.PositiveIntegerField(default=1)
    mensaje_actual = models.TextField(blank=True, default='')
    fecha_inicio = models.DateTimeField(auto_now_add=True)
    fecha_finalizacion = models.DateTimeField(null=True, blank=True)
    timeout_segundos = models.PositiveIntegerField(default=30)
    ultima_actividad = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha_inicio']
        verbose_name = 'Sesión de conversación'
        verbose_name_plural = 'Sesiones de conversación'

    def __str__(self):
        return f'{self.llamada.identificador} - {self.estado}'


class TipoIntervencionAgente(models.TextChoices):
    PREGUNTA = 'PREGUNTA', 'Pregunta'
    RESPUESTA = 'RESPUESTA', 'Respuesta'
    ANALISIS = 'ANALISIS', 'Análisis'
    FINALIZACION = 'FINALIZACION', 'Finalización'
    ERROR = 'ERROR', 'Error'
    AUDIO = 'AUDIO', 'Audio'


class IntervencionAgente(models.Model):
    sesion = models.ForeignKey(
        SesionConversacion,
        on_delete=models.CASCADE,
        related_name='intervenciones',
    )
    orden = models.PositiveIntegerField(default=0)
    tipo = models.CharField(
        max_length=20,
        choices=TipoIntervencionAgente.choices,
        default=TipoIntervencionAgente.PREGUNTA,
    )
    texto = models.TextField(blank=True, default='')
    audio = models.FileField(upload_to='tts_agente/', blank=True, null=True)
    pregunta = models.ForeignKey(
        PreguntaAsistente,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='intervenciones_agentales',
    )
    respuesta_recibida = models.TextField(blank=True, default='')
    estado = models.CharField(max_length=20, blank=True, default='OK')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sesion', 'orden', 'fecha_creacion']
        verbose_name = 'Intervención del agente'
        verbose_name_plural = 'Intervenciones del agente'

    def __str__(self):
        return f'{self.sesion.llamada.identificador} - {self.tipo} #{self.orden}'


class ClasificacionAnalisis(models.TextChoices):
    SEGURO = 'SEGURO', 'Seguro'
    INTERMEDIO = 'INTERMEDIO', 'Intermedio'
    ALERTA = 'ALERTA', 'Alerta'
    INFORMACION_INSUFICIENTE = 'INFORMACION_INSUFICIENTE', 'Información insuficiente'


class DecisionAdultoMayor(models.TextChoices):
    PENDIENTE = 'PENDIENTE', 'Pendiente'
    ACEPTAR = 'ACEPTAR', 'Aceptar llamada'
    RECHAZAR = 'RECHAZAR', 'Rechazar llamada'


class GravedadIndicador(models.TextChoices):
    BAJA = 'BAJA', 'Baja'
    MEDIA = 'MEDIA', 'Media'
    ALTA = 'ALTA', 'Alta'
    CRITICA = 'CRITICA', 'Crítica'


class NivelRiesgoResumen(models.TextChoices):
    BAJO = 'BAJO', 'Bajo'
    MEDIO = 'MEDIO', 'Medio'
    ALTO = 'ALTO', 'Alto'
    SIN_EVALUAR = 'SIN_EVALUAR', 'Sin evaluar'


class IndicadorFraude(models.Model):
    llamada = models.ForeignKey(
        Llamada,
        on_delete=models.CASCADE,
        related_name='indicadores_fraude',
    )
    transcripcion = models.ForeignKey(
        TranscripcionLlamada,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='indicadores_fraude',
    )
    codigo = models.CharField(max_length=80, db_index=True)
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, default='')
    fragmento = models.TextField(blank=True, default='')
    gravedad = models.CharField(
        max_length=20,
        choices=GravedadIndicador.choices,
        default=GravedadIndicador.MEDIA,
    )
    patron = models.CharField(max_length=200, blank=True, default='')
    activo = models.BooleanField(default=True)
    fecha_detectado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_detectado', 'codigo']
        verbose_name = 'Indicador de fraude'
        verbose_name_plural = 'Indicadores de fraude'

    def __str__(self):
        return f'{self.llamada.identificador} - {self.nombre}'


class PatronFraude(models.Model):
    """Catálogo editable de expresiones que aportan señales de fraude."""
    codigo = models.CharField(max_length=80, db_index=True)
    nombre = models.CharField(max_length=200)
    patron = models.CharField(max_length=200, unique=True)
    descripcion = models.TextField(blank=True, default='')
    gravedad = models.CharField(max_length=20, choices=GravedadIndicador.choices, default=GravedadIndicador.MEDIA)
    puntuacion = models.PositiveSmallIntegerField(default=10)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['codigo', 'patron']
        verbose_name = 'Patrón de fraude'
        verbose_name_plural = 'Patrones de fraude'

    def __str__(self):
        return f'{self.nombre}: {self.patron}'


class ClasificacionRiesgo(models.Model):
    llamada = models.ForeignKey(
        Llamada,
        on_delete=models.CASCADE,
        related_name='clasificaciones_riesgo',
    )
    nivel = models.CharField(
        max_length=20,
        choices=[('VERDE', 'Verde'), ('AMARILLO', 'Amarillo'), ('ROJO', 'Rojo')],
        default='VERDE',
    )
    puntuacion = models.PositiveIntegerField(default=0)
    motivo = models.TextField(blank=True, default='')
    señales = models.TextField(blank=True, default='')
    fecha_clasificacion = models.DateTimeField(auto_now_add=True)
    es_actual = models.BooleanField(default=True)

    class Meta:
        ordering = ['-fecha_clasificacion']
        verbose_name = 'Clasificación de riesgo'
        verbose_name_plural = 'Clasificaciones de riesgo'

    def __str__(self):
        return f'{self.llamada.identificador} - {self.nivel}'


class AnalisisLlamada(models.Model):
    llamada = models.OneToOneField(
        Llamada,
        on_delete=models.CASCADE,
        related_name='analisis_llamada',
    )
    identidad_declarada = models.CharField(max_length=200, blank=True, default='')
    institucion = models.CharField(max_length=200, blank=True, default='')
    motivo = models.CharField(max_length=255, blank=True, default='')
    solicitud_datos_personales = models.BooleanField(default=False)
    solicitud_contrasenas = models.BooleanField(default=False)
    solicitud_codigos_bancarios = models.BooleanField(default=False)
    solicitud_transferencias = models.BooleanField(default=False)
    amenazas_o_intimidacion = models.BooleanField(default=False)
    presion_para_actuar_inmediatamente = models.BooleanField(default=False)
    inconsistencias = models.BooleanField(default=False)
    evasiva_de_preguntas = models.BooleanField(default=False)
    indicadores_detectados = models.TextField(blank=True, default='')
    clasificacion = models.CharField(
        max_length=40,
        choices=ClasificacionAnalisis.choices,
        default=ClasificacionAnalisis.INFORMACION_INSUFICIENTE,
    )
    nivel_confianza = models.FloatField(default=0.0, blank=True, null=True)
    explicacion = models.TextField(blank=True, default='')
    fecha_analisis = models.DateTimeField(auto_now_add=True)
    antecedentes_consultados = models.TextField(blank=True, default='')
    transcripciones_consultadas = models.TextField(blank=True, default='')
    decision_adulto_mayor = models.CharField(
        max_length=20,
        choices=DecisionAdultoMayor.choices,
        default=DecisionAdultoMayor.PENDIENTE,
    )

    class Meta:
        ordering = ['-fecha_analisis']
        verbose_name = 'Análisis de llamada'
        verbose_name_plural = 'Análisis de llamadas'

    def __str__(self):
        return f'{self.llamada.identificador} - {self.clasificacion}'


class ResumenLlamada(models.Model):
    llamada = models.OneToOneField(
        Llamada,
        on_delete=models.CASCADE,
        related_name='resumen_llamada',
    )
    identidad_declarada = models.CharField(max_length=200, blank=True, default='No identificado')
    institucion = models.CharField(max_length=200, blank=True, default='No identificada')
    motivo = models.CharField(max_length=255, blank=True, default='No se pudo determinar el motivo de la llamada')
    indicadores_detectados = models.TextField(blank=True, default='')
    clasificacion = models.CharField(
        max_length=40,
        choices=ClasificacionAnalisis.choices,
        default=ClasificacionAnalisis.INFORMACION_INSUFICIENTE,
    )
    nivel_riesgo = models.CharField(
        max_length=20,
        choices=NivelRiesgoResumen.choices,
        default=NivelRiesgoResumen.SIN_EVALUAR,
    )
    explicacion = models.TextField(blank=True, default='')
    texto_resumen = models.TextField(blank=True, default='')
    fecha_generacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_generacion']
        verbose_name = 'Resumen de llamada'
        verbose_name_plural = 'Resumen de llamadas'

    def __str__(self):
        return f'{self.llamada.identificador} - {self.nivel_riesgo}'
