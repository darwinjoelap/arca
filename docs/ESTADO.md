# Estado del proyecto

Se trabaja por fases, como en Edumia: una fase se cierra aquí antes de abrir la siguiente.

## Hecho — Fase 0 (infraestructura) y Fase 1 (organizaciones y acceso)

- [x] Proyecto Django 5.2 con settings `base` / `local` / `production` / `test` y `Procfile` para Railway
- [x] Usuario propio (`core.Usuario`) desde la primera migración
- [x] App `organizaciones`: `Organizacion`, `TipoMiembro`, `Membresia`, `Ejercicio` y el abstracto `ModeloDeOrganizacion`
- [x] Organización activa por petición (`core/middleware.py`) y control de acceso por permiso (`core/mixins.py`)
- [x] Director = dueño (`Membresia.es_dueno`), uno solo por organización; administradores nombrados por él
- [x] Interruptor `director_ve_cuentas_personales`, solo en el panel de plataforma, con registro en bitácora
- [x] Pantallas del director: datos, tipos de miembro, miembros, ejercicios, bitácora
- [x] Clave temporal obligatoria de cambiar al primer ingreso
- [x] App `cambio` (tasa global, la carga el superadmin) con sus pruebas de Edumia
- [x] Paleta carbón / latón / marfil, logo e iconos de PWA; Bootstrap, iconos y htmx servidos desde `static/vendor/`
- [x] 53 pruebas, incluidas las de aislamiento entre organizaciones

## Pendiente de verificar en tu máquina

- [ ] Correr las pruebas contra PostgreSQL. Aquí se corrieron contra SQLite; las restricciones condicionales
      (un solo dueño, un solo ejercicio activo) existen en ambos, pero hay que confirmarlo en Postgres.
- [ ] Primer despliegue en Railway (no se ha hecho ninguno).
- [ ] `git init` y primer commit: la carpeta todavía no es un repositorio.

## Lo que NO está todavía

- Ningún movimiento de dinero: ni ingresos, ni egresos, ni saldos, ni presupuestos, ni cuenta personal, ni inventario.
  El interruptor de visibilidad ya se guarda y se audita, pero aún no hay cuentas personales que mostrar u ocultar.
- Captura offline: el service worker solo cachea el "shell". La cola en IndexedDB de Edumia entra en la Fase 3.
- Actualización automática de la tasa BCV (Fase 2).
- Fuentes Inter y Manrope servidas desde `static/` (hoy vienen de Google Fonts; sin conexión cae a la fuente del sistema).
- Agregar a una organización un usuario que ya existe en otra: solo desde `/admin/`.
- Respaldo automático de la base (el workflow de Neon de Edumia no se copió; hay que hacerlo para Railway).

## Siguiente — Fase 2 (moneda e identidad)

- [ ] Comando `actualizar_tasa_bcv` + cron de Railway; probar la fuente desde Railway antes de comprometerse
- [ ] Fuentes en `static/`
- [ ] Pantalla «Añadir a inicio» para iPhone
- [ ] Decidir: ¿la tasa la ve cualquier miembro en el panel, o solo quien maneja dinero?

## Luego

Fase 3 libro de caja (con captura offline) · Fase 4 presupuestos · Fase 5 miembros y cuenta personal ·
Fase 6 reportes · Fase 7 inventario · Fase 8 cierre (arqueo, importador de Excel, alta de organizaciones).
