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

- [x] Pruebas contra PostgreSQL: las 53 pasan (2026-10-05).
- [ ] Primer despliegue en Railway (no se ha hecho ninguno).
- [ ] `git init` y primer commit: la carpeta todavía no es un repositorio.

## Hecho — Fase 3, parte 1 (libro de caja)

- [x] App `finanzas`: `Caja`, `Cuenta`, `Concepto` (dos niveles) y `Movimiento`
- [x] Registro de ingresos y egresos, con concepto de la lista o libre, miembro o tercero, y referencia
- [x] Vale correlativo por caja y ejercicio; protección contra doble envío
- [x] Aprobación opcional de egresos y anulación con motivo
- [x] Panel: fondos disponibles con «Ver en USD / Ver en Bs.», ingresos y egresos del mes, saldo por cuenta y últimos movimientos
- [x] Lista de movimientos con filtros
- [x] Traslados entre cuentas (misma moneda o cambio de divisas), solo director y administradores
- [x] 93 pruebas en total, incluido el aislamiento del libro y de los traslados

Pendiente de verificar en tu máquina: correr las 93 pruebas contra PostgreSQL (aquí, SQLite).

## Lo que NO está todavía

- Captura offline de ingresos y egresos (Fase 3, parte 2). Hoy registrar exige conexión.
- Editar un movimiento: no existe a propósito (A-18).
- Exportar el libro a Excel o PDF y el resumen por concepto (Fase 6).
- Presupuestos, cuenta personal e inventario.
- Actualización automática de la tasa BCV (Fase 2).
- Fuentes Inter y Manrope servidas desde `static/` (hoy vienen de Google Fonts; sin conexión cae a la fuente del sistema).
- Agregar a una organización un usuario que ya existe en otra: solo desde `/admin/`.
- Respaldo automático de la base (el workflow de Neon de Edumia no se copió; hay que hacerlo para Railway).

## Siguiente — Fase 3, parte 2: captura offline

- [ ] Cola en IndexedDB y endpoints idempotentes en `sync` (patrón de la Fase 7 de Edumia)
- [ ] Precaché de los formularios y catálogos (cuentas, conceptos, última tasa)

## Pendiente — Fase 2 (moneda e identidad)

- [ ] Comando `actualizar_tasa_bcv` + cron de Railway; probar la fuente desde Railway antes de comprometerse
- [ ] Fuentes en `static/`
- [ ] Pantalla «Añadir a inicio» para iPhone
- [ ] Decidir: ¿la tasa la ve cualquier miembro en el panel, o solo quien maneja dinero?

## Luego

Fase 4 presupuestos · Fase 5 miembros y cuenta personal ·
Fase 6 reportes · Fase 7 inventario · Fase 8 cierre (arqueo, importador de Excel, alta de organizaciones).
