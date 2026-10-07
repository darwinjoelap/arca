"""Registro de movimientos y cálculo de saldos.

Saldos (decisión A-13): el saldo de una cuenta se suma en SU moneda y es
exacto. «Ver en USD / Ver en Bs.» convierte ese saldo con la tasa vigente:
responde a «¿cuánto tengo hoy?». Los ingresos y egresos de un período, en
cambio, usan el equivalente congelado de cada movimiento: responden a
«¿cuánto entró y salió?» con la tasa del día en que ocurrió.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from cambio.services import SinTasaError, convertir, obtener_tasa, tasa_propia
from organizaciones.models import Ejercicio

from .models import Caja, Cuenta, CuotaMiembro, Movimiento, Traslado

CERO = Decimal("0")


def ejercicio_para(organizacion, fecha):
    """El ejercicio abierto de la organización que contiene `fecha`, o None."""
    return Ejercicio.objects.filter(
        organizacion=organizacion, cerrado=False, fecha_inicio__lte=fecha, fecha_fin__gte=fecha,
    ).first()


def tasa_para(fecha, organizacion=None):
    """(TasaCambio, es_exacta) para `fecha`.

    Global: prefiere la del BCV; si no hay, cualquier otra global. Si se pasa
    la organización y esta cargó una tasa propia, se usa la más reciente de
    las dos; si son del mismo día, gana la propia (A-47).
    Lanza SinTasaError si no existe ninguna en esa fecha ni antes."""
    try:
        try:
            global_ = obtener_tasa(fecha, fuente="bcv")[0]
        except SinTasaError:
            global_ = obtener_tasa(fecha)[0]
    except SinTasaError:
        global_ = None
    propia = tasa_propia(organizacion, fecha) if organizacion is not None else None
    if propia is not None and (global_ is None or propia.fecha >= global_.fecha):
        return propia, propia.fecha == fecha
    if global_ is None:
        raise SinTasaError(f"No hay ninguna tasa de cambio registrada en o antes de {fecha}.")
    return global_, global_.fecha == fecha


def tasa_vigente(organizacion=None):
    """La tasa para convertir saldos hoy, o (None, False) si no hay ninguna."""
    try:
        return tasa_para(timezone.localdate(), organizacion)
    except SinTasaError:
        return None, False


@transaction.atomic
def registrar_movimiento(movimiento, *, membresia):
    """Guarda un Movimiento nuevo ya validado por su formulario.

    Completa lo que no viene del formulario: ejercicio, tasa, número de vale
    y estado inicial. Devuelve (movimiento, creado); `creado` es False si el
    `uuid_cliente` ya existía (doble envío): se devuelve el original.
    """
    organizacion = movimiento.organizacion

    if movimiento.uuid_cliente:
        existente = Movimiento.objects.filter(
            organizacion=organizacion, uuid_cliente=movimiento.uuid_cliente
        ).first()
        if existente:
            return existente, False

    ejercicio = ejercicio_para(organizacion, movimiento.fecha)
    if ejercicio is None:
        raise ValidationError({"fecha": "No hay un ejercicio abierto que incluya esa fecha."})
    try:
        tasa, _ = tasa_para(movimiento.fecha, organizacion)
    except SinTasaError:
        raise ValidationError(
            "No hay ninguna tasa de cambio para esa fecha ni antes. El director puede cargarla en Configuración → Tasa de cambio."
        )

    movimiento.ejercicio = ejercicio
    movimiento.tasa = tasa
    movimiento.registrado_por = membresia.user
    movimiento.caja = movimiento.cuenta.caja

    # Un egreso espera aprobación solo si la organización lo exige y quien
    # registra no es director ni administrador.
    espera = (
        movimiento.tipo == Movimiento.Tipo.EGRESO
        and organizacion.requiere_aprobacion_egresos
        and not membresia.puede_administrar
    )
    movimiento.estado = Movimiento.Estado.REGISTRADO if espera else Movimiento.Estado.CONFIRMADO

    # Correlativo por caja y ejercicio. Se bloquea la fila de la caja para
    # que dos registros simultáneos no tomen el mismo número.
    Caja.objects.select_for_update().get(pk=movimiento.caja_id)
    ultimo = Movimiento.objects.filter(caja_id=movimiento.caja_id, ejercicio=ejercicio).aggregate(
        n=Max("numero_vale")
    )["n"]
    movimiento.numero_vale = (ultimo or 0) + 1

    movimiento.full_clean(exclude=["tasa_aplicada", "monto_ves", "monto_usd", "moneda"])
    movimiento.save()
    return movimiento, True


@transaction.atomic
def registrar_traslado(traslado, *, usuario):
    """Guarda un Traslado nuevo. Devuelve (traslado, creado), igual que
    `registrar_movimiento`. Si las cuentas tienen la misma moneda, el monto
    que llega es el mismo que sale, se haya escrito lo que se haya escrito."""
    organizacion = traslado.organizacion
    if traslado.uuid_cliente:
        existente = Traslado.objects.filter(organizacion=organizacion, uuid_cliente=traslado.uuid_cliente).first()
        if existente:
            return existente, False

    ejercicio = ejercicio_para(organizacion, traslado.fecha)
    if ejercicio is None:
        raise ValidationError({"fecha": "No hay un ejercicio abierto que incluya esa fecha."})

    origen, destino = traslado.cuenta_origen, traslado.cuenta_destino
    if origen.moneda == destino.moneda:
        traslado.monto_destino = traslado.monto_origen
    elif not traslado.monto_destino:
        try:
            tasa, _ = tasa_para(traslado.fecha, organizacion)
        except SinTasaError:
            raise ValidationError({"monto_destino": "No hay tasa de cambio cargada: escribe cuánto se recibió."})
        ves, usd = convertir(traslado.monto_origen, origen.moneda, tasa.valor)
        traslado.monto_destino = usd if destino.moneda == "USD" else ves

    traslado.ejercicio = ejercicio
    traslado.registrado_por = usuario
    traslado.full_clean()
    traslado.save()
    return traslado, True


def _sumas_por_cuenta(organizacion, hasta=None):
    """{cuenta_id: neto de movimientos y traslados confirmados, en la moneda de la cuenta}."""
    qs = Movimiento.objects.filter(organizacion=organizacion, estado=Movimiento.Estado.CONFIRMADO)
    if hasta is not None:
        qs = qs.filter(fecha__lte=hasta)
    sumas = {}
    for fila in qs.values("cuenta_id", "tipo").annotate(total=Sum("monto")):
        signo = 1 if fila["tipo"] == Movimiento.Tipo.INGRESO else -1
        sumas[fila["cuenta_id"]] = sumas.get(fila["cuenta_id"], CERO) + signo * fila["total"]

    # Traslados: salen de una cuenta y entran en otra, cada monto en su moneda.
    traslados = Traslado.objects.filter(organizacion=organizacion, estado=Traslado.Estado.CONFIRMADO)
    if hasta is not None:
        traslados = traslados.filter(fecha__lte=hasta)
    for fila in traslados.values("cuenta_origen_id").annotate(total=Sum("monto_origen")):
        sumas[fila["cuenta_origen_id"]] = sumas.get(fila["cuenta_origen_id"], CERO) - fila["total"]
    for fila in traslados.values("cuenta_destino_id").annotate(total=Sum("monto_destino")):
        sumas[fila["cuenta_destino_id"]] = sumas.get(fila["cuenta_destino_id"], CERO) + fila["total"]
    return sumas


def saldo_cuenta(cuenta, hasta=None):
    return cuenta.saldo_inicial + _sumas_por_cuenta(cuenta.organizacion, hasta).get(cuenta.pk, CERO)


def resumen_saldos(organizacion, tasa=None):
    """Saldos por caja y cuenta, más el total, para el panel.

    Devuelve {"cajas": [{"caja", "cuentas": [{"cuenta", "saldo", "ves", "usd"}], "ves", "usd"}],
              "ves", "usd", "convertible"}.
    Sin tasa no se puede convertir: `ves` y `usd` suman solo las cuentas de
    esa moneda y `convertible` es False, para que la pantalla lo avise.
    """
    sumas = _sumas_por_cuenta(organizacion)
    cajas, total_ves, total_usd = [], CERO, CERO
    cuentas = Cuenta.objects.filter(organizacion=organizacion, activa=True, caja__activa=True).select_related("caja")
    por_caja = {}
    for cuenta in cuentas:
        saldo = cuenta.saldo_inicial + sumas.get(cuenta.pk, CERO)
        if tasa is not None:
            ves, usd = convertir(saldo, cuenta.moneda, tasa.valor)
        else:
            ves = saldo if cuenta.moneda == "VES" else CERO
            usd = saldo if cuenta.moneda == "USD" else CERO
        bloque = por_caja.setdefault(cuenta.caja_id, {"caja": cuenta.caja, "cuentas": [], "ves": CERO, "usd": CERO})
        bloque["cuentas"].append({"cuenta": cuenta, "saldo": saldo, "ves": ves, "usd": usd})
        bloque["ves"] += ves
        bloque["usd"] += usd
        total_ves += ves
        total_usd += usd
    cajas = sorted(por_caja.values(), key=lambda b: b["caja"].nombre.lower())
    return {"cajas": cajas, "ves": total_ves, "usd": total_usd, "convertible": tasa is not None}


def totales_por_caja(organizacion, desde, hasta):
    """{caja_id: {"ingreso": {"ves","usd"}, "egreso": {...}}} de lo confirmado entre dos fechas."""
    resultado = {}
    filas = (
        Movimiento.objects.filter(
            organizacion=organizacion, estado=Movimiento.Estado.CONFIRMADO, fecha__gte=desde, fecha__lte=hasta,
        )
        .values("caja_id", "tipo")
        .annotate(ves=Sum("monto_ves"), usd=Sum("monto_usd"))
    )
    for fila in filas:
        bloque = resultado.setdefault(fila["caja_id"], {
            "ingreso": {"ves": CERO, "usd": CERO}, "egreso": {"ves": CERO, "usd": CERO}})
        bloque[fila["tipo"]] = {"ves": fila["ves"] or CERO, "usd": fila["usd"] or CERO}
    return resultado


def totales_periodo(organizacion, desde, hasta):
    """Ingresos y egresos confirmados entre dos fechas, con el equivalente
    congelado de cada movimiento. {"ingreso": {"ves","usd"}, "egreso": {...}}"""
    totales = {
        Movimiento.Tipo.INGRESO: {"ves": CERO, "usd": CERO},
        Movimiento.Tipo.EGRESO: {"ves": CERO, "usd": CERO},
    }
    filas = (
        Movimiento.objects.filter(
            organizacion=organizacion, estado=Movimiento.Estado.CONFIRMADO, fecha__gte=desde, fecha__lte=hasta,
        )
        .values("tipo")
        .annotate(ves=Sum("monto_ves"), usd=Sum("monto_usd"))
    )
    for fila in filas:
        totales[fila["tipo"]] = {"ves": fila["ves"] or CERO, "usd": fila["usd"] or CERO}
    return {"ingreso": totales[Movimiento.Tipo.INGRESO], "egreso": totales[Movimiento.Tipo.EGRESO]}


# --- Cuotas de miembros -----------------------------------------------------


def _meses_entre(desde, hasta):
    """Cuántos meses calendario hay de `desde` a `hasta`, ambos incluidos."""
    if hasta < desde:
        return 0
    return (hasta.year - desde.year) * 12 + hasta.month - desde.month + 1


def estado_cuotas(organizacion, ejercicio, hasta=None, membresia=None):
    """Lo esperado contra lo pagado de cada cuota dentro del ejercicio, hasta
    el mes de `hasta` (por defecto hoy). Cada cuota en SU moneda.

    Devuelve una lista de dicts: cuota, meses, esperado, pagado, pendiente
    (positivo = debe; negativo = pagó de más) y ultimo_pago.
    """
    hasta = min(hasta or timezone.localdate(), ejercicio.fecha_fin)
    cuotas = CuotaMiembro.objects.filter(organizacion=organizacion).select_related(
        "membresia", "membresia__user", "membresia__tipo", "concepto")
    if membresia is not None:
        cuotas = cuotas.filter(membresia=membresia)
    resultado = []
    for cuota in cuotas:
        inicio = max(cuota.vigente_desde, ejercicio.fecha_inicio)
        fin = min(cuota.vigente_hasta or hasta, hasta)
        meses = _meses_entre(inicio, fin) if fin >= inicio.replace(day=1) else 0
        campo = "monto_usd" if cuota.moneda == "USD" else "monto_ves"
        pagos = Movimiento.objects.filter(
            organizacion=organizacion, estado=Movimiento.Estado.CONFIRMADO, tipo=Movimiento.Tipo.INGRESO,
            miembro=cuota.membresia_id, concepto=cuota.concepto_id,
            fecha__gte=inicio.replace(day=1), fecha__lte=ejercicio.fecha_fin,
        ).aggregate(total=Sum(campo), ultimo=Max("fecha"))
        esperado, pagado = cuota.monto * meses, pagos["total"] or CERO
        if not meses and not pagado:
            continue  # la cuota todavía no aplica en este ejercicio
        resultado.append({
            "cuota": cuota, "meses": meses, "esperado": esperado, "pagado": pagado,
            "pendiente": esperado - pagado, "ultimo_pago": pagos["ultimo"],
        })
    return resultado


# --- Arqueo y anticipos (Fase 8) ---------------------------------------------


@transaction.atomic
def registrar_arqueo(*, organizacion, cuenta, contado, fecha, nota, usuario):
    from .models import Arqueo

    return Arqueo.objects.create(
        organizacion=organizacion, cuenta=cuenta, fecha=fecha, contado=contado, nota=nota,
        saldo_sistema=saldo_cuenta(cuenta, fecha), realizado_por=usuario,
    )


@transaction.atomic
def ajustar_arqueo(arqueo, *, membresia):
    """Lleva la diferencia al libro: sobrante como ingreso, faltante como egreso."""
    if arqueo.ajuste_id:
        raise ValidationError("Este arqueo ya tiene su ajuste registrado.")
    if arqueo.cuadra:
        raise ValidationError("El arqueo cuadra: no hay nada que ajustar.")
    sobra = arqueo.diferencia > 0
    movimiento, _ = registrar_movimiento(Movimiento(
        organizacion=arqueo.organizacion, tipo=Movimiento.Tipo.INGRESO if sobra else Movimiento.Tipo.EGRESO,
        fecha=arqueo.fecha, cuenta=arqueo.cuenta, monto=abs(arqueo.diferencia),
        descripcion=f"{'Sobrante' if sobra else 'Faltante'} de arqueo del {arqueo.fecha:%d/%m/%Y}",
    ), membresia=membresia)
    arqueo.ajuste = movimiento
    arqueo.save(update_fields=["ajuste"])
    return movimiento


@transaction.atomic
def entregar_anticipo(*, organizacion, cuenta, monto, fecha, motivo, miembro, tercero, membresia):
    from .models import Anticipo

    if monto > saldo_cuenta(cuenta):
        raise ValidationError({"monto": "La cuenta no tiene saldo suficiente para entregar ese anticipo."})
    entrega, _ = registrar_movimiento(Movimiento(
        organizacion=organizacion, tipo=Movimiento.Tipo.EGRESO, fecha=fecha, cuenta=cuenta, monto=monto,
        descripcion=f"Anticipo por rendir: {motivo}"[:200], miembro=miembro, tercero=tercero,
    ), membresia=membresia)
    return Anticipo.objects.create(
        organizacion=organizacion, cuenta=cuenta, fecha=fecha, monto=monto, motivo=motivo, miembro=miembro,
        tercero=tercero, entrega=entrega, entregado_por=membresia.user,
    )


@transaction.atomic
def rendir_anticipo(anticipo, *, fecha, lineas, membresia):
    """`lineas`: [(concepto o None, descripción, monto)]. Anula el egreso
    provisional y registra en su lugar los gastos reales. Puede venir vacía:
    no gastó nada y lo devolvió todo."""
    from .models import Anticipo

    anticipo = Anticipo.objects.select_for_update().get(pk=anticipo.pk)
    if anticipo.estado != Anticipo.Estado.PENDIENTE:
        raise ValidationError("Este anticipo ya no está por rendir.")
    if fecha < anticipo.fecha:
        raise ValidationError({"fecha": "La rendición no puede ser anterior a la entrega."})
    anticipo.entrega.transicionar(
        Movimiento.Estado.ANULADO, membresia.user, motivo=f"Anticipo rendido el {fecha:%d/%m/%Y}: reemplazado por los gastos reales.")
    total = CERO
    for concepto, descripcion, monto in lineas:
        gasto, _ = registrar_movimiento(Movimiento(
            organizacion=anticipo.organizacion, tipo=Movimiento.Tipo.EGRESO, fecha=fecha, cuenta=anticipo.cuenta,
            monto=monto, concepto=concepto, descripcion=descripcion, miembro=anticipo.miembro, tercero=anticipo.tercero,
            referencia=f"Anticipo #{anticipo.pk}",
        ), membresia=membresia)
        anticipo.gastos.add(gasto)
        total += monto
    anticipo.estado, anticipo.fecha_rendicion, anticipo.gastado = Anticipo.Estado.RENDIDO, fecha, total
    anticipo.save(update_fields=["estado", "fecha_rendicion", "gastado"])
    return anticipo


@transaction.atomic
def anular_anticipo(anticipo, *, usuario, motivo):
    from .models import Anticipo

    if anticipo.estado != Anticipo.Estado.PENDIENTE:
        raise ValidationError("Solo se anula un anticipo que sigue por rendir.")
    anticipo.entrega.transicionar(Movimiento.Estado.ANULADO, usuario, motivo=f"Anticipo anulado: {motivo}")
    anticipo.estado = Anticipo.Estado.ANULADO
    anticipo.save(update_fields=["estado"])
    return anticipo
