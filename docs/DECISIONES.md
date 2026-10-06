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

**A-24 — Presupuesto mensual por concepto.** Como en los Excel: un monto al mes; el acumulado es ese monto por
los meses transcurridos del ejercicio. Lo ejecutado no se guarda, se suma de los movimientos confirmados de la
caja en la moneda del presupuesto, con la tasa de su día.

**A-25 — Un reporte, tres salidas.** Cada reporte se construye una vez como un `Reporte` (columnas y filas con
su clase: sección, grupo, normal, subtotal, total) y de ahí salen la pantalla, el Excel y el PDF. Agregar un
reporte es escribir una función en `reportes/services.py` y registrarlo en `CATALOGO`.

**A-26 — Favorable o desfavorable depende del tipo.** En egresos es favorable gastar menos; en ingresos,
recibir más. El color acompaña siempre a un número con su signo; nunca es el único indicio.

**A-27 — El gráfico no usa el verde y el terracota de los montos.** Ese par no se distingue con daltonismo
rojo-verde. Las columnas usan verde y ámbar, validados, con leyenda y con los valores en el globo y en la tabla.

**A-28 — Los reportes los ve quien ve el libro completo.** `puede_ver_movimientos` (director y administradores
incluidos). El presupuesto y su comparativo los ve además quien tiene `puede_ver_presupuesto`.

**A-28 (revisada) — Los reportes tienen permiso propio.** `puede_ver_reportes`, que el director marca por tipo
de miembro. La migración lo enciende a quien ya tenía `puede_ver_movimientos`.

**A-29 — Miembro no es lo mismo que usuario.** Una membresía puede no tener usuario: figura en ingresos,
egresos y cuotas, pero no entra. Sin usuario no puede ser director ni administrador. «Dar acceso» le crea el
usuario después sin perder su historial.

**A-30 — El director también es miembro.** No hay dos cuentas ni cambio de modo: el menú tiene una sección
«Personal» (Mi resumen, Mi cuenta) igual para todos, y debajo lo que cada quien puede hacer por su permiso.

**A-31 — La cuota es una expectativa, no un cobro.** Se define miembro + concepto + monto mensual + vigencia.
Lo pagado no se guarda: es la suma de los ingresos confirmados a nombre del miembro con ese concepto.

**A-32 — Una asignación son dos asientos atados.** Egreso en el libro de la organización y entrada en la
cuenta personal, unidos por `origen`. La entrada no se edita ni se borra desde la cuenta personal; anular el
egreso la retira.

**A-33 — La cuenta personal es del miembro.** No toca saldos de la organización. Su saldo es la suma de los
equivalentes congelados de cada movimiento. El director ve solo lo asignado; el detalle, únicamente si el
soporte activa `director_ve_cuentas_personales`, y cada consulta queda en la bitácora.

**A-34 — El presupuesto avisa, no impide.** Al registrar un egreso con concepto, el formulario muestra cuánto
queda de la partida del mes y advierte si se pasa; se puede guardar igual y queda un aviso tras guardar. Solo
rigen los presupuestos aprobados y las partidas con monto. Cuenta lo confirmado del mes, en la moneda del
presupuesto. Lo ve quien puede registrar egresos. Sin conexión el aviso no aparece.

**A-35 — Suscripción por organización, desde /plataforma/.** Estructura tomada de Ordo: plan, «activa hasta»,
límite de usuarios, notas internas y suspensión. Suspendida o vencida corta el acceso de todo el equipo en la
siguiente petición, sin borrar nada. El límite cuenta solo membresías activas con usuario; los miembros sin
acceso no ocupan cupo. Cada cambio queda en la bitácora de esa organización.

**A-36 — La clave temporal la genera el sistema.** Nadie la escribe: ni el superadmin al crear al director ni
el director al crear o restablecer a un miembro. Formato `Arca-` + 10 caracteres sin los que se confunden. Se
muestra una sola vez, en una respuesta sin caché, y obliga a cambiarla al entrar.

**A-37 — Sin «entrar como soporte».** A diferencia de Ordo, el superadmin no entra a una organización: ve el
equipo y la suscripción, nunca movimientos ni saldos. Sí puede restablecer la clave del director.

**A-38 — Cada organización tiene su enlace y sus propios usuarios.** Como en Ordo: se entra por `/<enlace>/`
y el usuario es único dentro de la organización (`organizacion_cuenta` + `username`), así que «maria» puede
existir en dos. Las cuentas de plataforma no tienen organización y entran por la dirección principal. Una
cuenta no cruza a otra organización: quien pertenezca a dos tiene dos cuentas. El equipo recuerda su enlace
(cookie) para que la app instalada y «cerrar sesión» vuelvan a su login. Los datos siguen en una sola base,
aislados por la columna `organizacion` (A-01): no hay esquema ni base por organización.

**A-39 — El inventario no toca el dinero.** Bienes y consumibles en un mismo catálogo. El valor por unidad es
informativo (cuánto vale lo que hay); una compra se registra aparte como egreso en el libro. No hay enlace
entre una entrada de inventario y un vale.

**A-40 — Las existencias no se guardan, se suman.** Son el resultado de los movimientos vigentes (entrada,
salida, traslado) por artículo y ubicación. Un movimiento no se edita: se anula con motivo. No se puede sacar
más de lo que hay en la ubicación de origen, ni anular una entrada si deja una ubicación en negativo; el
desfase con la realidad se corrige con un ajuste por conteo.

**A-41 — Mínimo solo en consumibles, estado solo en bienes.** El aviso «por reponer» salta cuando la existencia
total llega al mínimo o baja de él. El responsable es por artículo, no por ubicación.

**A-42 — El arqueo guarda una foto y ofrece el ajuste.** Se guarda el saldo que el sistema tenía a la fecha y
lo contado; si después cambia el libro, el arqueo no cambia. La diferencia no se lleva sola al libro: se ofrece
un botón que la registra como ingreso (sobrante) o egreso (faltante), una sola vez.

**A-43 — El anticipo sale al entregar y se reemplaza al rendir.** La entrega es un egreso provisional sin
concepto («anticipo por rendir»). Al rendir, ese egreso se anula y quedan los gastos reales, cada uno con su
concepto, con la fecha de la rendición; lo que sobró vuelve a la cuenta porque los gastos suman menos. Si gastó
de más, la diferencia sale de la cuenta. El egreso provisional no se anula desde el libro, solo desde el anticipo.

## Heredadas de Edumia que siguen vigentes

- **D-02 (revisado)** — El valor de una tasa se puede corregir; recalcula lo no congelado.
- **D-05** — No se guardan archivos.
- **D-09** — Lo aprobado no se recalcula ni se edita: se anula con motivo y se registra de nuevo.
- **D-28** — La llamada a la bitácora se escribe en el mismo cambio que crea el flujo.
- **D-33** — Los catálogos se borran solo si no están en uso (`on_delete=PROTECT` + `eliminar_protegido`).
