# Mostrar el proyecto en Chrome con HTTPS

Chrome solo permite grabar audio desde un contexto seguro: HTTPS o `localhost`. La URL `http://192.168.x.x:8000` no es segura para el permiso del micrófono. [MDN: getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia.)

## Una sola vez

Instala `mkcert` siguiendo su guía oficial y reinicia Chrome si ya estaba abierto. El script ejecutará `mkcert -install` para que el equipo confíe en el certificado local y generará un certificado temporal para `localhost`. [Instalación oficial de mkcert](https://github.com/FiloSottile/mkcert#installation)

## Cada demostración

1. Desde la raíz del proyecto ejecuta `./scripts/run_https_demo.sh`.
2. Deja abierta esa terminal.
3. En Chrome abre `https://localhost:8443/`.
4. Entra como **Usuario** o **Atacante** y permite el micrófono cuando Chrome lo solicite.

El servidor HTTPS atiende solo en la computadora local. Para mostrarlo desde otro dispositivo o publicarlo en internet hace falta un dominio con certificado HTTPS confiable por ese dispositivo; un certificado local de `mkcert` no se confía automáticamente en otros equipos. `mkcert` está pensado para desarrollo local, no para publicar el sitio. [README de mkcert](https://github.com/FiloSottile/mkcert)
