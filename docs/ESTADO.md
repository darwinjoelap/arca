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

## Hecho — Fase 3, parte 2 (captura offline)

- [x] Ingresos y egresos se pueden registrar sin conexión con la app ya abierta (como Edumia)
- [x] Banda fija de «Sin conexión» y aviso en el formulario cada vez que algo queda guardado en el teléfono
- [x] Envío automático al volver la señal, al reabrir la app y, en Android, en segundo plano (Background Sync)
- [x] Contador de pendientes en la barra superior, con panel para revisar, reintentar o descartar
- [x] Un pendiente que el servidor rechaza queda marcado con su motivo: no se pierde ni se reintenta en bucle
- [x] Sesión cerrada, otro usuario u otra organización en el mismo teléfono: el pendiente se conserva
- [x] 102 pruebas en total; el flujo completo se probó además en un navegador real (cortar y devolver la red)

Pendiente de verificar en tu máquina: las 102 pruebas contra PostgreSQL, y el flujo en un teléfono de verdad
(Android y iPhone). Aquí se probó con Chromium simulando un teléfono, sin service worker.

## Hecho — Fase 4 (presupuestos) y Fase 6 (reportes)

- [x] Presupuesto por caja y ejercicio, con monto mensual por concepto, en una moneda
- [x] Una sola pantalla para cargar todos los montos, con totales al mes y al año mientras se escribe
- [x] Aprobar (bloquea), reabrir (queda en bitácora) y eliminar borradores
- [x] Ejecución: presupuestado contra real del mes y acumulado, variación y barra de ejecución por partida
- [x] Reportes: estado de ingresos y egresos, variación contra el período anterior, flujo mensual, por miembro,
      libro de caja o banco con saldo corrido, libro diario y presupuesto contra real
- [x] Cada reporte en pantalla, Excel (con números de verdad) y PDF (encabezado, pie con página y líneas de firma)
- [x] Comprobante de ingreso o egreso en PDF, desde el detalle del movimiento
- [x] Panel de análisis: indicadores, gráfico mensual, en qué se va el dinero, de dónde viene y quién aporta
- [x] Cada archivo emitido queda en la bitácora
- [x] 126 pruebas en total

Pendiente de verificar en tu máquina: las 126 pruebas contra PostgreSQL.

## Lo que NO está todavía

- Abrir la app desde cero sin señal: no se puede. Hay que tenerla abierta en «Registrar ingreso» o
  «Registrar egreso» antes de perder la conexión (decisión A-20). Navegar a otra pantalla sin señal muestra
  el aviso de «Sin conexión» y lo ya guardado en el teléfono no se pierde.
- Traslados sin conexión: solo en línea.
- Editar un movimiento: no existe a propósito (A-18).
- Presupuesto anual con montos distintos por mes: hoy es un monto mensual fijo (el anual es por doce).
- El flujo de solicitud de las partidas «se solicita con antelación»: por ahora es solo una marca.
- Reportes de traslados y de la diferencia por cambio de divisas como línea propia.
- Balance de saldos por cuenta a una fecha pasada, como reporte (el libro de cada cuenta sí lo da).
- Gráficos dentro de los PDF: los PDF llevan solo tablas.
- Cuenta personal e inventario.
- Actualización automática de la tasa BCV (Fase 2).
- Fuentes Inter y Manrope servidas desde `static/` (hoy vienen de Google Fonts; sin conexión cae a la fuente del sistema).
- Agregar a una organización un usuario que ya existe en otra: solo desde `/admin/`.
- Respaldo automático de la base (el workflow de Neon de Edumia no se copió; hay que hacerlo para Railway).

## Siguiente — por decidir

Fase 5 (cuotas, asignaciones y cuenta personal) o Fase 2 (tasa BCV automática, fuentes locales, instalación en iPhone).

## Pendiente — Fase 2 (moneda e identidad)

- [ ] Comando `actualizar_tasa_bcv` + cron de Railway; probar la fuente desde Railway antes de comprometerse
- [ ] Fuentes en `static/`
- [ ] Pantalla «Añadir a inicio» para iPhone
- [ ] Decidir: ¿la tasa la ve cualquier miembro en el panel, o solo quien maneja dinero?

## Luego

Fase 5 miembros y cuenta personal · Fase 7 inventario · Fase 8 cierre (arqueo, importador de Excel, alta de organizaciones).
