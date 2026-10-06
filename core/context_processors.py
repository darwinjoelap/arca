def organizacion(request):
    """Expone la organización, la membresía y los permisos de menú a todas las plantillas."""
    membresia = getattr(request, "membresia", None)

    def puede(permiso):
        return bool(membresia and membresia.tiene_permiso(permiso))

    puede_ingresos = puede("puede_registrar_ingresos")
    puede_egresos = puede("puede_registrar_egresos")
    return {
        "organizacion_activa": getattr(request, "organizacion", None),
        "membresia_activa": membresia,
        "puede_administrar": bool(membresia and membresia.puede_administrar),
        "puede_ingresos": puede_ingresos,
        "puede_egresos": puede_egresos,
        "entra_al_libro": puede_ingresos or puede_egresos or puede("puede_ver_movimientos"),
        "ve_el_libro": puede("puede_ver_movimientos"),
        "ve_reportes": puede("puede_ver_reportes"),
        "tiene_cuenta_personal": puede("tiene_cuenta_personal"),
        "puede_ver_presupuesto": puede("puede_ver_presupuesto"),
        "gestiona_inventario": puede("puede_gestionar_inventario"),
    }
