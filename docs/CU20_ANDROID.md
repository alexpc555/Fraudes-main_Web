# Integración Android para CU-20

Django solo guarda estados; la app Android debe consultar el sistema y reportar
lo que encontró. El endpoint autenticado es:

```http
POST /api/configurar/<adulto_id>/permisos/
Content-Type: application/json

{"codigo":"notificaciones","estado":"CONCEDIDO"}
```

Códigos registrados por el asistente:

- `notificaciones` — esencial.
- `identificacion_llamadas` — esencial; representa el permiso/rol que use la
  integración para identificar o administrar llamadas.
- `contactos_dispositivo` — opcional porque hoy los contactos se capturan en
  Django y no se importa la agenda del teléfono.

Estados válidos: `CONCEDIDO`, `DENEGADO`, `PENDIENTE` y `NO_DISPONIBLE`. El
endpoint marca el origen `ANDROID`; la interfaz web no puede reportar
`CONCEDIDO`. La configuración solo se completa cuando los permisos esenciales
están concedidos, hay un contacto de confianza activo y las notificaciones están
habilitadas.

La ruta requiere que la sesión autenticada pertenezca a un Familiar autorizado
para ese Adulto mayor. Antes de distribuir la app, integrar autenticación segura
para Android (sesión/CSRF o un mecanismo API con tokens), definir el contrato de
identificación de llamadas por versión del sistema y reportar `NO_DISPONIBLE`
cuando el dispositivo no ofrezca esa capacidad. Django no puede abrir diálogos
de permiso ni conceder roles del sistema operativo.
