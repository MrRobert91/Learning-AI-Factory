# Despliegue seguro y migración de credenciales

## Producción

Genera valores independientes para `APP_PASSWORD`, `SECRET_KEY` y
`CREDENTIAL_ENCRYPTION_KEYS`. La primera clave del key ring cifra escrituras
nuevas; las siguientes permiten leer y rotar valores antiguos.

```bash
python -c "import base64,secrets; print('2026-08:'+base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
docker compose -f docker-compose.yml -f docker-compose.production.yml config
docker compose -f docker-compose.yml -f docker-compose.production.yml up --build
```

Configura `PUBLIC_APP_ORIGIN` como un origen HTTPS exacto, sin ruta, y
`GOOGLE_REDIRECT_URI` como su callback `/api/youtube/callback`. Añade a
`TRUSTED_PROXY_IPS` solo las IP/CIDR reales del proxy que termina TLS. El
backend no se publica al host en el override de producción.

## Migrar una instalación existente

1. Detén ambos contenedores y crea una copia offline de `data/db/factory.sqlite`
   en un almacenamiento cifrado y con acceso restringido.
2. Conserva la clave anterior al rotar: `nueva:<key>,anterior:<key>`.
3. Arranca la nueva versión. Antes del worker, cada `oauth_tokens.token_json`
   legacy se cifra y se verifica dentro de una transacción; SQLite activa
   `secure_delete`, trunca WAL y ejecuta `VACUUM` tras migrar.
4. Comprueba `/api/youtube/status` y realiza una publicación privada de prueba.
5. Elimina de forma segura la copia legacy cuando termine el periodo de rollback.

Las cookies anteriores se invalidan una vez porque las sesiones pasan a ser
revocables y persistidas. Esto no obliga a reconectar YouTube si la migración
de credenciales finaliza correctamente.

## Rotación y rollback

Para rotar, antepone la nueva clave y conserva la anterior. Las credenciales se
reescriben con la activa en la primera lectura verificada. Cuando ya no queden
valores con el identificador anterior, retíralo.

Si el arranque falla, no borres la base ni las claves: detén la aplicación,
restaura la copia offline y vuelve a la imagen anterior. Si la migración ya se
confirmó, la versión anterior no podrá leer el sobre cifrado; para rollback de
código restaura también la copia previa. Nunca copies tokens OAuth a logs o
variables de entorno para recuperarlos.
