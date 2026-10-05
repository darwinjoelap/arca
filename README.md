# Arca

SaaS de ingresos, egresos e inventario para organizaciones, centros culturales, familias y clubes.
Django 5.2 + PostgreSQL, desplegado en Railway. Nace de Edumia.

- Estado y próximos pasos: `docs/ESTADO.md`
- Decisiones de diseño: `docs/DECISIONES.md`

## Puesta en marcha (Windows, PowerShell)

```powershell
cd C:\proyectos\arca

# 1. Entorno virtual: crear, activar y VERIFICAR antes de instalar nada
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version          # debe decir 3.13.x
Get-Command python        # debe apuntar a C:\proyectos\arca\.venv\...

# 2. Dependencias
pip install -r requirements.txt

# 3. Variables de entorno
Copy-Item .env.example .env
# Editar .env: SECRET_KEY y DATABASE_URL (crear antes la base "arca" en PostgreSQL)

# 4. Base de datos y superadmin de la plataforma
python manage.py migrate
python manage.py createsuperuser

# 5. Primera organización, con su director (dueño)
python manage.py crear_organizacion "Nombre de la organización" --director usuario --clave "ClaveTemporal123" --nombre-director "Nombre Apellido"

# 6. Arrancar
python manage.py runserver
```

## Pruebas

```powershell
python manage.py test --settings=config.settings.test
```

## Quién entra a dónde

| Quién | Dónde | Qué hace |
|---|---|---|
| Superadmin (plataforma) | `/admin/` y `/cambio/tasas/` | Da de alta organizaciones, nombra o traspasa al director, decide si el director ve las cuentas personales, carga la tasa de cambio |
| Director (dueño) y administradores | `/organizacion/configuracion/` | Datos de la organización, tipos de miembro, miembros, ejercicios, bitácora |
| Miembros | `/` | Lo que su tipo de miembro permita |

## Railway

Variables: `DJANGO_SETTINGS_MODULE=config.settings.production`, `SECRET_KEY`, `ALLOWED_HOSTS`,
`CSRF_TRUSTED_ORIGINS` y `DATABASE_URL` (la entrega el plugin de PostgreSQL). El `Procfile` migra,
junta los estáticos y arranca gunicorn. Health check: `/salud/`.
