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

## Hecho — Fase 5 (miembros y cuenta personal)

- [x] Miembros sin usuario: gente de la comunidad que aporta o recibe y no entra a Arca; «Dar acceso» después
- [x] Permiso «Ver reportes» por tipo de miembro, separado de «Ver movimientos»
- [x] Sección «Personal» para todos, director incluido: «Mi resumen» (lo que aporté y recibí de la organización)
- [x] Cuotas de miembros: aporte mensual esperado, pagado, pendiente y último pago
- [x] Asignaciones: egreso de la organización que entra a la cuenta personal del miembro
- [x] «Mi cuenta»: ingresos y gastos propios, conceptos propios, saldo, gráfico mensual y en qué se gasta
- [x] El director ve las cuentas personales solo si el soporte activa el interruptor; cada consulta queda en la bitácora
- [x] Aviso de presupuesto al registrar un egreso: cuánto queda de la partida del mes y si se pasa (A-34)
- [x] Conceptos nuevos desde el presupuesto: se escriben en la última fila y pasan al catálogo de Conceptos
- [x] Panel de plataforma (/plataforma/): alta de organizaciones, plan, vencimiento, límite de usuarios, suspensión
- [x] Claves temporales generadas por el sistema y mostradas una sola vez (superadmin y director)
- [x] Enlace propio por organización (/enlace/) con usuarios propios; la dirección principal es de la plataforma
- [x] Panel principal con una tarjeta por caja (disponible, ingresos y egresos del mes) y filtro por caja en Movimientos
- [x] Panel con pestañas por caja (Todas · cada caja), transiciones y estilos de interacción unificados
- [x] 176 pruebas hasta aquí

## Hecho — Fase 7 (inventario)

- [x] Catálogo de artículos: bienes y consumibles, con categoría, unidad, código, valor, responsable y estado
- [x] Ubicaciones y categorías definidas por la organización
- [x] Entradas, salidas y cambios de ubicación, con motivo e historial; se anulan con motivo
- [x] Existencia por ubicación y total; aviso de consumibles por reponer; valor de lo que hay en $ y Bs.
- [x] Permiso «Gestionar inventario» por tipo de miembro; todo queda en la bitácora
- [x] Reportes de inventario en pantalla, Excel y PDF: valorizado, por ubicación (hoja de conteo), por reponer y movimientos
- [x] 191 pruebas hasta aquí

## Hecho — Fase 8 (cierre, parte 1)

- [x] Arqueo de cuentas: sistema contra contado, historial y ajuste de la diferencia con un clic
- [x] Anticipos por rendir: entrega, rendición por concepto, devolución o reposición, anulación
- [x] 196 pruebas hasta aquí

## Hecho — Preparación para producción

- [x] `railway.json`: arranque, health check y reinicio; el dominio de Railway se acepta solo
- [x] `asegurar_superadmin`: crea la cuenta de plataforma en el primer arranque
- [x] Respaldo diario cifrado por GitHub Actions (`despliegue/respaldo.yml`, que hay que copiar a `.github/workflows/`), 30 días
- [x] Guía paso a paso en `docs/DESPLIEGUE.md`, con restauración
- [x] 197 pruebas en total

Pendiente y es tuyo: crear el proyecto en Railway, cargar variables y secretos, y probar una restauración.

Pendiente de verificar en tu máquina: `migrate` y las 197 pruebas contra PostgreSQL.

## Hecho — Fase 2 (tasa e identidad) y datos en Excel

- [x] Tasa BCV automática: `cambio/bcv.py` lee el dólar y la «Fecha Valor» de la página del BCV y guarda la tasa con esa fecha (A-44). Comando `actualizar_tasa_bcv`, envoltorio `tareas_programadas`, `railway.cron.json` para el servicio Cron y botón «Consultar BCV ahora» en `/cambio/tasas/`
- [x] Datos en Excel, solo el director (Configuración → Datos en Excel): descargar todo en un libro (13 hojas) y cargar desde una plantilla con revisión previa (A-45, A-46)
- [x] Panel: avisos de anticipos por rendir y de consumibles en el mínimo
- [x] Cuotas: Excel y PDF desde la misma pantalla
- [x] Fuentes Inter y Manrope en `static/vendor/fuentes/` (ya no se pide nada a Google)
- [x] Pantalla `/instalar/` con los pasos de iPhone, Android y computadora (menú del usuario)
- [x] `/sw.js` ya no se pide en cada página
- [x] 219 pruebas

Pendiente y es tuyo: crear el servicio Cron en Railway (docs/DESPLIEGUE.md, sección 6) y mirar su primer log.
**La lectura del BCV no se pudo probar contra la página real desde aquí** (sin salida a esa dirección): está
probada contra una copia del HTML. La primera corrida real es la prueba.

Pendiente de verificar en tu máquina: `pip install -r requirements.txt`, `migrate` y las 219 pruebas en PostgreSQL.

## Lo que NO está todavía

- Abrir la app desde cero sin señal: no se puede (A-20).
- Sin conexión solo funcionan ingreso y egreso de la organización: ni traslados ni la cuenta personal.
- Asignar dinero a un miembro sin acceso: no se puede, porque no tiene cuenta personal. Se registra como egreso normal a su nombre.
- Cuotas: sin aviso de morosidad.
- Anticipos: máximo 8 gastos por rendición, todos con la fecha de la rendición y en la moneda de la cuenta; el miembro no rinde por su cuenta, lo hace el director.
- Arqueo: no pide el desglose por billetes ni tiene reporte en PDF.
- Editar un movimiento de la organización: no existe a propósito (A-18).
- El aviso de presupuesto no aparece sin conexión, ni cuenta los egresos que esperan aprobación.
- Presupuesto anual con montos distintos por mes; flujo de «se solicita con antelación».
- Reportes de traslados, diferencia en cambio y saldos a una fecha pasada. Gráficos dentro de los PDF.
- Inventario: sin registro sin conexión, sin fotos, sin conteo físico guiado y sin enlace con el egreso de la compra. Un artículo por cantidad no distingue unidades individuales (40 sillas son una fila, no 40 fichas).
- Carga desde Excel: no trae traslados, presupuesto, cuotas ni anticipos; los movimientos entran confirmados y necesitan una tasa de su fecha o anterior (para historia vieja, la plataforma carga antes esas tasas a mano).
- Tasa: si el BCV cambia su página, la consulta falla y avisa en el log del Cron; no hay alerta por correo.
- Traspasar la dirección de una organización: solo desde `/admin/`.
- Recuperar la contraseña por correo: ya no se ofrece; la restablece el director (o la plataforma, la del director).
- La pantalla de entrada lleva el nombre de la organización, pero no su logo ni sus colores.
- Suscripción: no hay cobro, historial de pagos ni aviso automático de vencimiento; el plan es una etiqueta y lo único que limita es la fecha y el número de usuarios.
- El flujo de respaldo no se ha ejecutado nunca contra una base real: hay que probarlo y restaurar una vez.

## Siguiente — por decidir

Repaso visual del resto de pantallas; offline para traslados y cuenta personal; aviso de morosidad de cuotas.
