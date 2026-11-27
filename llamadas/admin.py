from django.contrib import admin

from .models import (
    AnalisisLlamada, ClasificacionRiesgo, ConfiguracionNotificaciones, ContactoConfianza, EventoNotificacion, IndicadorFraude,
    ConfiguracionAplicacion, EstadoPermiso, IntervencionAgente, Llamada, NumeroReportado, PatronFraude,
    PreguntaAsistente, RespuestaLlamada, ResultadoConsultaNumero,
    RelacionFamiliarAdultoMayor, ResumenLlamada, SesionConversacion, TranscripcionLlamada,
)


class EstadoPermisoInline(admin.TabularInline):
    model = EstadoPermiso
    extra = 0
    readonly_fields = ('actualizado_en',)


@admin.register(RelacionFamiliarAdultoMayor)
class RelacionFamiliarAdultoMayorAdmin(admin.ModelAdmin):
    list_display = ('familiar', 'adulto_mayor', 'autorizado', 'fecha_registro')
    list_filter = ('autorizado',)
    search_fields = ('familiar__username', 'adulto_mayor__username')


@admin.register(ConfiguracionAplicacion)
class ConfiguracionAplicacionAdmin(admin.ModelAdmin):
    list_display = ('adulto_mayor', 'paso_actual', 'notificaciones_habilitadas', 'actualizado_por', 'actualizado_en', 'completado_en')
    list_filter = ('paso_actual', 'notificaciones_habilitadas')
    readonly_fields = ('actualizado_en', 'completado_en')
    inlines = (EstadoPermisoInline,)


@admin.register(EstadoPermiso)
class EstadoPermisoAdmin(admin.ModelAdmin):
    list_display = ('configuracion', 'codigo', 'nombre', 'estado', 'esencial', 'origen', 'actualizado_en')
    list_filter = ('estado', 'esencial', 'origen')


@admin.register(ConfiguracionNotificaciones)
class ConfiguracionNotificacionesAdmin(admin.ModelAdmin):
    list_display = ('adulto_mayor', 'familiar_responsable', 'contacto_confianza', 'activo', 'actualizado_en')
    list_filter = ('activo',)
    search_fields = ('adulto_mayor__username', 'familiar_responsable__username', 'contacto_confianza__nombre')


@admin.register(EventoNotificacion)
class EventoNotificacionAdmin(admin.ModelAdmin):
    list_display = ('llamada', 'tipo', 'canal', 'nivel_riesgo', 'estado', 'fecha_creacion', 'fecha_envio')
    list_filter = ('tipo', 'canal', 'estado', 'nivel_riesgo')
    search_fields = ('llamada__identificador', 'destinatario_nombre', 'destinatario_telefono')
    readonly_fields = ('fecha_creacion', 'fecha_ultimo_intento', 'fecha_envio', 'mensaje', 'error_detalle', 'detalle_envio')


@admin.register(PatronFraude)
class PatronFraudeAdmin(admin.ModelAdmin):
    list_display = ('patron', 'nombre', 'codigo', 'gravedad', 'puntuacion', 'activo')
    list_filter = ('codigo', 'gravedad', 'activo')
    search_fields = ('patron', 'nombre', 'descripcion')


@admin.register(Llamada)
class LlamadaAdmin(admin.ModelAdmin):
    list_display = ('identificador', 'numero_telefonico', 'fecha_hora_recepcion', 'estado')
    list_filter = ('estado',)
    search_fields = ('numero_telefonico', 'identificador')


@admin.register(NumeroReportado)
class NumeroReportadoAdmin(admin.ModelAdmin):
    list_display = ('numero_telefonico', 'identidad_reportada', 'tipo_incidente', 'cantidad_reportes', 'estado')
    list_filter = ('estado', 'tipo_incidente')
    search_fields = ('numero_telefonico', 'identidad_reportada', 'descripcion')


@admin.register(ResultadoConsultaNumero)
class ResultadoConsultaNumeroAdmin(admin.ModelAdmin):
    list_display = ('numero_telefonico', 'estado', 'cantidad_reportes', 'fecha_consulta')
    list_filter = ('estado',)
    search_fields = ('numero_telefonico', 'descripcion', 'error_detalle')


@admin.register(ContactoConfianza)
class ContactoConfianzaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'numero_telefonico', 'correo_electronico', 'relacion', 'activo', 'fecha_registro')
    list_filter = ('activo', 'relacion')
    search_fields = ('nombre', 'numero_telefonico', 'descripcion')


@admin.register(TranscripcionLlamada)
class TranscripcionLlamadaAdmin(admin.ModelAdmin):
    list_display = ('llamada', 'estado', 'fecha_procesamiento', 'duracion_audio')
    list_filter = ('estado', 'fecha_procesamiento')
    search_fields = ('llamada__numero_telefonico', 'texto_transcrito')


@admin.register(PreguntaAsistente)
class PreguntaAsistenteAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'texto', 'orden', 'activa')
    list_filter = ('activa',)
    search_fields = ('codigo', 'texto')


@admin.register(RespuestaLlamada)
class RespuestaLlamadaAdmin(admin.ModelAdmin):
    list_display = ('llamada', 'pregunta', 'fecha_respuesta')
    search_fields = ('llamada__numero_telefonico', 'pregunta__codigo', 'texto_respuesta')


@admin.register(SesionConversacion)
class SesionConversacionAdmin(admin.ModelAdmin):
    list_display = ('llamada', 'estado', 'pregunta_actual', 'fecha_inicio', 'fecha_finalizacion')
    list_filter = ('estado',)
    search_fields = ('llamada__numero_telefonico',)


@admin.register(IntervencionAgente)
class IntervencionAgenteAdmin(admin.ModelAdmin):
    list_display = ('sesion', 'orden', 'tipo', 'estado', 'fecha_creacion')
    list_filter = ('tipo', 'estado')
    search_fields = ('texto', 'respuesta_recibida')


@admin.register(IndicadorFraude)
class IndicadorFraudeAdmin(admin.ModelAdmin):
    list_display = ('llamada', 'nombre', 'gravedad', 'activo', 'fecha_detectado')
    list_filter = ('gravedad', 'activo')
    search_fields = ('nombre', 'codigo', 'patron', 'llamada__numero_telefonico')


@admin.register(ClasificacionRiesgo)
class ClasificacionRiesgoAdmin(admin.ModelAdmin):
    list_display = ('llamada', 'nivel', 'puntuacion', 'es_actual', 'fecha_clasificacion')
    list_filter = ('nivel', 'es_actual')
    search_fields = ('llamada__numero_telefonico', 'señales', 'motivo')


@admin.register(AnalisisLlamada)
class AnalisisLlamadaAdmin(admin.ModelAdmin):
    list_display = ('llamada', 'clasificacion', 'nivel_confianza', 'decision_adulto_mayor', 'fecha_analisis')
    list_filter = ('clasificacion', 'decision_adulto_mayor')
    search_fields = ('llamada__numero_telefonico', 'explicacion', 'indicadores_detectados')


@admin.register(ResumenLlamada)
class ResumenLlamadaAdmin(admin.ModelAdmin):
    list_display = ('llamada', 'clasificacion', 'nivel_riesgo', 'fecha_generacion')
    list_filter = ('clasificacion', 'nivel_riesgo')
    search_fields = ('llamada__numero_telefonico', 'motivo', 'texto_resumen')
