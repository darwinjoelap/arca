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

## Heredadas de Edumia que siguen vigentes

- **D-02 (revisado)** — El valor de una tasa se puede corregir; recalcula lo no congelado.
- **D-05** — No se guardan archivos.
- **D-09** — Lo aprobado no se recalcula ni se edita: se anula con motivo y se registra de nuevo.
- **D-28** — La llamada a la bitácora se escribe en el mismo cambio que crea el flujo.
- **D-33** — Los catálogos se borran solo si no están en uso (`on_delete=PROTECT` + `eliminar_protegido`).
