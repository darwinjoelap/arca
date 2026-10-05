# Decisiones

Cada decisión lleva un código para citarla desde el código. Las heredadas de Edumia conservan el suyo (D-xx).

## Arca

**A-01 — Multi-organización con una sola base de datos.** Cada tabla con datos de una organización tiene una
FK `organizacion` (heredando de `ModeloDeOrganizacion`). No se usa un esquema de PostgreSQL por organización:
es más simple de migrar y respaldar en Railway.

**A-02 — El aislamiento es explícito, no automático.** No hay un manager que filtre solo por un "tenant
actual" guardado en un hilo. Las vistas filtran siempre por `request.organizacion` (`DeLaOrganizacionMixin` o
`get_object_or_404(..., organizacion=request.organizacion)`), y hay pruebas que piden por URL objetos de otra
organización y esperan 404. Un filtro implícito es cómodo, pero falla en silencio en comandos y tareas.

**A-03 — La organización activa nunca viene del cliente.** Se guarda en la sesión y el middleware la valida en
cada petición contra las membresías activas del usuario. Desactivar una membresía corta el acceso de inmediato.

**A-04 — Un solo rol fijo: el director, que es el dueño.** `Membresia.es_dueno`, uno por organización
(restricción en la base). Puede nombrar administradores, que hacen todo salvo modificar al director o a otros
administradores. El traspaso de la dirección lo hace el superadmin.

**A-05 — Tipos de miembro con nombre libre y permisos.** Reemplazan los cinco roles fijos de Edumia. La lista
de permisos vive en `organizaciones.models.PERMISOS`.

**A-06 — La visibilidad de las cuentas personales la decide el superadmin.** Campo
`Organizacion.director_ve_cuentas_personales`, editable solo en `/admin/`. Apagado por defecto. Cada cambio queda
en la bitácora de esa organización, y el miembro verá un aviso en su cuenta (Fase 5).

**A-07 — El superadmin no entra a los datos de una organización.** Ser superusuario no da permisos dentro de una
organización; para eso hace falta una membresía. Administra la plataforma desde `/admin/`.

**A-08 — Un director solo restablece la clave de usuarios exclusivos de su organización.** Si el usuario
pertenece a otra organización o es de plataforma, se rechaza: de lo contrario un director podría tomar una
cuenta ajena.

**A-09 — Desactivar es por membresía, no por usuario.** La persona puede seguir activa en otras organizaciones.

**A-10 — La tasa de cambio es global.** Una fila por día y fuente sirve a todas las organizaciones, así que la
carga el superadmin (y, desde la Fase 2, un comando).

**A-11 — Sin archivos adjuntos.** Solo datos, como en Edumia (D-05). No hay `MEDIA_ROOT`.

**A-12 — Las apps de Edumia entran por fases, no de golpe.** `academico` no se usa. `ingresos`, `gastos`,
`recibos`, `reportes` y `sync` no se copiaron todavía: dependen de la institución única y de los roles fijos, y
se reescriben como `finanzas`, `presupuestos`, `personal`, `inventario`, `reportes` y `sync` en sus fases,
tomando de Edumia el patrón y el código que sirva.

**A-13 — Saldos en la moneda de la cuenta; la conversión es solo para verlos.** Cada cuenta tiene una
moneda y todo movimiento toma la de su cuenta, así que el saldo de una cuenta es una suma exacta. «Ver en USD /
Ver en Bs.» convierte esos saldos con la tasa vigente (cuánto tengo hoy). Los ingresos y egresos de un período
usan el equivalente congelado de cada movimiento (cuánto entró y salió, a la tasa de su día). Edumia sumaba
equivalentes congelados también para el saldo; con cuentas en dos monedas eso da una cifra que no existe en
ninguna parte.

**A-14 — Un movimiento, un monto.** Sin renglones de producto, cantidad y precio como en Edumia: el libro del
Excel trabaja así y es mucho más rápido de capturar en el teléfono.

**A-15 — El saldo inicial vive en la cuenta, no en la caja.** La caja agrupa cuentas y tendrá el presupuesto;
el dinero está en las cuentas. Cambiar un saldo inicial queda en la bitácora como evento propio.

**A-16 — Aprobación de egresos opcional.** Con `requiere_aprobacion_egresos` apagado, todo se confirma al
registrarse. Encendido, el egreso de quien no es director ni administrador queda «por aprobar» y no cuenta en el
saldo hasta que uno de ellos lo apruebe. Los ingresos nunca esperan.

**A-17 — Quién ve el libro.** Director, administradores y quien tenga `puede_ver_movimientos` ven todo y ven
los saldos. Quien solo registra ve únicamente lo que registró él, y no ve saldos.

**A-18 — Un movimiento no se edita.** Ni siquiera recién creado: se anula con motivo y se registra de nuevo
(D-09). El `uuid_cliente` evita el duplicado por doble envío y será la clave de la cola offline.

**A-19 — Un traslado no es ingreso ni egreso.** Mueve dinero entre dos cuentas de la organización y guarda
dos montos, cada uno en la moneda de su cuenta. En un cambio de divisas se escribe lo que de verdad se recibió;
si se deja vacío, se usa la tasa del día. La diferencia contra la tasa oficial se ve como una variación de los
fondos disponibles: es la «diferencia por cambios» del Excel, que ya no hay que calcular a mano. Solo director
y administradores registran y anulan traslados.

**A-20 — Offline como en Edumia: con la app ya abierta.** Se registra sin conexión solo desde un formulario que
ya estaba cargado; no se precargan pantallas ni catálogos para abrir la app desde cero sin señal. Es más simple
y evita trabajar con cuentas, conceptos o tasa desactualizados.

**A-21 — El formulario siempre envía por el endpoint de sync.** No se confía en `navigator.onLine`: con wifi
sin internet dice que hay conexión. El formulario intenta enviar y, si no hay respuesta en 12 segundos, guarda
en el teléfono. Si el servidor sí recibió y solo se perdió la respuesta, el reintento no duplica (`uuid_cliente`).

**A-22 — Solo un JSON con `resultado` cuenta como guardado.** Una redirección al login o la página de un portal
cautivo responden 200 con HTML; darlas por buenas borraría de la cola algo que nunca llegó. Por eso el endpoint
nunca redirige (responde 401/409 en JSON) y el cliente exige el JSON. Edumia tenía ese hueco.

**A-23 — La cola es del teléfono, pero cada pendiente es de quien lo capturó.** Lleva el usuario y la
organización; el servidor rechaza con 409 lo que no sea de la sesión actual y el teléfono lo conserva.

## Heredadas de Edumia que siguen vigentes

- **D-02 (revisado)** — El valor de una tasa se puede corregir; recalcula lo no congelado.
- **D-05** — No se guardan archivos.
- **D-09** — Lo aprobado no se recalcula ni se edita: se anula con motivo y se registra de nuevo.
- **D-28** — La llamada a la bitácora se escribe en el mismo cambio que crea el flujo.
- **D-33** — Los catálogos se borran solo si no están en uso (`on_delete=PROTECT` + `eliminar_protegido`).
