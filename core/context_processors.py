def organizacion(request):
    """Expone la organización y la membresía activas a todas las plantillas."""
    membresia = getattr(request, "membresia", None)
    return {
        "organizacion_activa": getattr(request, "organizacion", None),
        "membresia_activa": membresia,
        "puede_administrar": bool(membresia and membresia.puede_administrar),
    }
