# Despliegue en Railway y respaldo

Lista para hacerlo una vez, en orden. Los nombres de botones de Railway y GitHub pueden variar un poco.

## Antes de empezar

- [ ] `python manage.py test` pasa en tu máquina y todo está subido a GitHub (`git status` limpio).
- [ ] Decide el usuario del superadmin (tu cuenta de plataforma) y una clave temporal de 12 caracteres o más.
- [ ] Decide una frase larga (20 caracteres o más) para cifrar los respaldos y guárdala fuera de GitHub
      y de Railway. **Sin esa frase los respaldos no se pueden abrir.**

## 1. Crear el proyecto

- [ ] En Railway: nuevo proyecto desde el repositorio `darwinjoelap/arca`.
- [ ] En el mismo proyecto, agregar una base **PostgreSQL**.
- [ ] En el servicio web, generar un dominio público (Settings → Networking).

## 2. Variables del servicio web

| Variable | Valor |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.production` |
| `SECRET_KEY` | una clave nueva (ver abajo); no reutilices la de tu `.env` |
| `DATABASE_URL` | referencia a la base: `${{Postgres.DATABASE_URL}}` |
| `ALLOWED_HOSTS` | vacío si usas solo el dominio de Railway; tu dominio propio si lo tienes |
| `CSRF_TRUSTED_ORIGINS` | vacío, o `https://tu-dominio.com` si usas dominio propio |
| `ARCA_ADMIN_USUARIO` | el usuario de tu cuenta de plataforma |
| `ARCA_ADMIN_CLAVE` | la clave temporal (12 o más caracteres) |

Para generar la `SECRET_KEY`, en tu máquina:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(60))"
```

El dominio que da Railway se acepta solo (variable `RAILWAY_PUBLIC_DOMAIN`, que Railway define). Un dominio
propio hay que escribirlo en `ALLOWED_HOSTS` y en `CSRF_TRUSTED_ORIGINS`.

## 3. Primer arranque

`railway.json` ya dice cómo arrancar: migra, crea el superadmin si no existe ninguno, junta los estáticos y
levanta gunicorn. El health check es `/salud/`.

- [ ] Esperar a que el despliegue quede en verde. Si falla, mirar los logs del servicio.
- [ ] Abrir `https://<dominio>/cuentas/login/?plataforma` y entrar con `ARCA_ADMIN_USUARIO` y `ARCA_ADMIN_CLAVE`.
- [ ] Cambiar la clave cuando lo pida.
- [ ] **Borrar la variable `ARCA_ADMIN_CLAVE`** en Railway (ya no hace falta; el comando no vuelve a crear nada).
- [ ] En «Tasa de cambio», cargar la tasa de hoy: sin ninguna tasa no se puede registrar ningún movimiento.
- [ ] En «Organizaciones», crear la primera; copiar el enlace, el usuario y la clave temporal que muestra
      (solo se muestran una vez) y entregárselos al director.

## 4. Respaldo diario

El flujo corre todos los días a las 03:17 de Caracas: saca un volcado
completo, lo cifra con tu frase y lo guarda 30 días como artefacto en GitHub.

- [ ] Activar el flujo: copiar `despliegue/respaldo.yml` a `.github/workflows/respaldo.yml` y subirlo (una sola vez):

```powershell
New-Item -ItemType Directory -Force .github\workflows | Out-Null
Copy-Item despliegue\respaldo.yml .github\workflows\respaldo.yml
git add .github\workflows\respaldo.yml
git commit -m "Activa el respaldo diario"
git push
```

- [ ] En Railway, en la base PostgreSQL, copiar la URL **pública** (`DATABASE_PUBLIC_URL`).
- [ ] En GitHub → Settings → Secrets and variables → Actions, crear dos secretos:
  - `RESPALDO_DATABASE_URL`: esa URL pública.
  - `RESPALDO_FRASE`: la frase para cifrar.
- [ ] En GitHub → Actions → «Respaldo de la base» → «Run workflow», y comprobar que termina en verde y deja
      un artefacto `arca-AAAAMMDD-HHMM.dump`.
- [ ] Hacer **una restauración de prueba** (abajo). Un respaldo que nunca se ha restaurado no cuenta.

Si la versión de PostgreSQL de Railway es mayor que 18, cambia `PG_IMAGEN` en el flujo: la herramienta que
vuelca debe ser igual o más nueva que el servidor.

### Restaurar

Descarga el artefacto desde la corrida en GitHub Actions (viene en un `.zip` con el `.dump.gpg` dentro).
Hace falta GnuPG y las herramientas de PostgreSQL en tu máquina.

```powershell
# 1. Descifrar (pide la frase)
gpg --output arca.dump --decrypt arca-20261006-0717.dump.gpg

# 2. Restaurar en una base VACÍA (aquí, una local de prueba en tu puerto 5434)
createdb -h 127.0.0.1 -p 5434 -U postgres arca_restaurada
pg_restore -h 127.0.0.1 -p 5434 -U postgres -d arca_restaurada --no-owner --no-privileges arca.dump

# 3. Comprobar: apunta DATABASE_URL del .env a arca_restaurada y entra con runserver
```

Para restaurar sobre producción, crea una base PostgreSQL nueva en Railway, restaura ahí con su URL pública
y luego cambia `DATABASE_URL` del servicio web a la base nueva. No restaures encima de la base en uso.

## 5. Cada despliegue siguiente

Cada `git push` a `main` despliega solo. Antes de hacerlo:

- [ ] `python manage.py test` en verde.
- [ ] Si hay migraciones, leerlas: una que borre o cambie datos merece un respaldo manual antes
      (Actions → «Respaldo de la base» → «Run workflow»).
- [ ] Tras el despliegue, abrir el sitio y entrar a una organización.

## 6. Tasa BCV automática (servicio Cron)

Un segundo servicio en el mismo proyecto de Railway, que arranca, consulta el BCV y se apaga.

- [ ] En el proyecto: **New → GitHub Repo →** el mismo repositorio `arca`. Nómbralo `tareas`.
- [ ] En ese servicio, **Settings → Config-as-code → Railway Config File**: `railway.cron.json`.
      (Ese archivo le pone el comando `python manage.py tareas_programadas` y el horario.)
- [ ] **Variables** del servicio `tareas`: las mismas tres del web — `DATABASE_URL` (referencia a Postgres),
      `SECRET_KEY` y `DJANGO_SETTINGS_MODULE=config.settings.production`. No necesita dominio.
- [ ] Desplegar y abrir el log de la primera corrida. Debe decir `Tasa BCV nueva: …` (o `igual`).
- [ ] Entrar a `/cambio/tasas/` como plataforma y ver la tasa con «Automática» en «Cargada por».

Horario: 11:00, 21:00 y 23:00 UTC (7 a. m., 5 p. m. y 7 p. m. en Venezuela). El BCV publica en la tarde la
tasa del día hábil siguiente; la corrida de la mañana es por si la tarde falló. Railway no corre un cron más
de una vez cada 5 minutos ni garantiza el minuto exacto.

Si falla (el BCV caído o cambió su página): el log dice `Tasa BCV no actualizada: …`, Arca sigue usando la
última tasa y avisa en pantalla que no es la del día. Se puede forzar con el botón **Consultar BCV ahora** o
cargar la tasa a mano en `/cambio/tasas/`.

## Lo que este despliegue no cubre

- Correo: no hay SMTP configurado. No hace falta para nada hoy (las claves las genera el sistema).
- Monitoreo y alertas: solo los logs de Railway. Si el respaldo falla, GitHub avisa por correo al dueño del
  repositorio, nada más.
- Los respaldos viven 30 días en GitHub. Para guardar uno más tiempo (un cierre de año), descárgalo.
