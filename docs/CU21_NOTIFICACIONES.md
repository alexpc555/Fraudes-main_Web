# CU-21: notificaciones al contacto seguro

El Familiar autorizado configura un contacto activo de la agenda `ContactoConfianza`
del Adulto mayor. La selección se guarda como clave foránea en
`ConfiguracionNotificaciones`; una selección de otra agenda o un contacto
desactivado no se acepta.

Los eventos se registran en `EventoNotificacion` y tienen clave única por llamada,
tipo de evento y canal. Se genera un aviso al clasificar una llamada roja. Si una
llamada amarilla o roja se acepta, se genera además un evento de aceptación. El
mensaje usa motivo genérico y no copia la transcripción ni valores de contraseñas,
códigos o información bancaria.

Push Android queda en `PENDIENTE` mientras no haya adaptador FCM conectado. Se
puede extender `ADAPTADORES` en `llamadas/notificaciones.py`. El correo es opt-in:
además de registrar un correo en el contacto, hay que habilitar
`NOTIFICACIONES_EMAIL_ACTIVAS=true` y configurar el backend SMTP de Django. Sin
esa opción, los eventos de correo también quedan pendientes. Los fallos de los
adaptadores se guardan como `ERROR` y no interrumpen el análisis de riesgo.

Las llamadas nuevas se asocian al Adulto mayor seleccionado o al único perfil
autorizado de la sesión. Para integrar llamadas entrantes desde Android, la futura
app debe enviar el identificador del perfil autorizado al registrar la llamada.
