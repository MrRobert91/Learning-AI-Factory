# Conectar YouTube (subida directa)

La subida a YouTube usa OAuth de Google. Necesitas unas credenciales propias
(gratis, ~10 minutos). Sin ellas, la plataforma funciona igual: el Publicador
genera el paquete (título, descripción, capítulos, tags, miniatura) y lo
descargas para publicar a mano.

## 1. Crear el proyecto y habilitar la API

1. Ve a [Google Cloud Console](https://console.cloud.google.com/) y crea un
   proyecto (p. ej. `ai-learning-factory`).
2. En **APIs y servicios → Biblioteca**, busca **YouTube Data API v3** y
   pulsa *Habilitar*.

## 2. Configurar la pantalla de consentimiento

1. **APIs y servicios → Pantalla de consentimiento OAuth**.
2. Tipo de usuario: **Externo** → crea la pantalla con nombre y tu email.
3. En *Usuarios de prueba*, añade tu propia cuenta de Google (la del canal).
   Mientras la app esté "en pruebas" solo esa cuenta puede autorizar, que es
   exactamente lo que queremos.

## 3. Crear las credenciales OAuth

1. **APIs y servicios → Credenciales → Crear credenciales → ID de cliente OAuth**.
2. Tipo: **Aplicación web**.
3. En *URIs de redireccionamiento autorizados* añade:
   `http://localhost:3000/api/youtube/callback`
4. Copia el **ID de cliente** y el **secreto** a tu `.env`:

```bash
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxx
```

5. Reinicia el backend (`docker compose up` de nuevo o `make dev-api`).

## 4. Conectar y publicar

1. Abre un artefacto de tipo **Publicación** y pulsa *Conectar con YouTube*.
2. Autoriza con la cuenta del canal → volverás a la app ya conectado.
3. Elige la privacidad (privado por defecto) y pulsa *Subir vídeo a YouTube*.
   La subida **nunca** es automática: siempre pasa por esta confirmación.

## Límites conocidos

- La cuota por defecto de la API son 10.000 unidades/día y cada subida cuesta
  1.600 → ~6 subidas al día.
- Hasta que Google verifique tu app OAuth, los vídeos subidos por API quedan
  **bloqueados en privado** (no se pueden hacer públicos desde YouTube Studio
  si los subiste como privados vía API sin verificación). Para un canal en
  producción, solicita la verificación de la app o usa la subida manual con
  el paquete de publicación.
