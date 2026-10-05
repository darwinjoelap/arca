// offline-forms.js — Envío de «Registrar ingreso» y «Registrar egreso».
//
// El formulario se envía por fetch al endpoint de sync en vez de con un POST
// normal. Así, si no hay conexión o se cae a mitad de camino, lo capturado
// se guarda en este teléfono y se envía solo cuando vuelva la señal, en vez
// de perderse con la pantalla de error del navegador.
//
// Mejora progresiva: si este archivo no carga o el navegador no tiene
// IndexedDB, el formulario sigue funcionando con su POST de siempre.
(function () {
  "use strict";

  function nuevoUuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    // Respaldo para navegadores viejos o contextos sin HTTPS.
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function textoDe(select) {
    return select && select.selectedIndex > 0 ? select.options[select.selectedIndex].text : "";
  }

  function leer(form) {
    var datos = {};
    new FormData(form).forEach(function (valor, nombre) {
      if (nombre !== "csrfmiddlewaretoken" && nombre !== "otro") datos[nombre] = valor;
    });
    datos.tipo = form.dataset.tipo;
    datos._usuario = document.body.dataset.usuario || "";
    datos._organizacion = document.body.dataset.organizacion || "";
    // Para poder mostrar el pendiente sin conexión, sin consultar al servidor.
    datos._resumen = {
      tipo: form.dataset.tipo,
      titulo: textoDe(form.elements.concepto) || datos.descripcion || "",
      cuenta: textoDe(form.elements.cuenta),
      monto: datos.monto,
      fecha: datos.fecha,
    };
    return datos;
  }

  function aviso(form, clase, html) {
    var caja = document.getElementById("aviso-formulario");
    if (!caja) {
      caja = document.createElement("div");
      caja.id = "aviso-formulario";
      caja.setAttribute("role", "status");
      form.parentNode.insertBefore(caja, form);
    }
    caja.className = "alert alert-" + clase;
    caja.innerHTML = html;
    caja.scrollIntoView({ block: "nearest" });
  }

  function limpiar(form) {
    // Se conservan fecha y cuenta: lo normal es registrar varios seguidos.
    ["monto", "descripcion", "tercero", "referencia"].forEach(function (n) {
      if (form.elements[n]) form.elements[n].value = "";
    });
    ["concepto", "miembro"].forEach(function (n) {
      if (form.elements[n]) form.elements[n].selectedIndex = 0;
    });
    form.elements.uuid_cliente.value = nuevoUuid();
    if (form.elements.monto) {
      form.elements.monto.dispatchEvent(new Event("input"));
      form.elements.monto.focus();
    }
  }

  async function registrarSyncEnSegundoPlano() {
    if (!("serviceWorker" in navigator)) return;
    try {
      var registro = await navigator.serviceWorker.ready;
      if (registro.sync) await registro.sync.register(window.ArcaOffline.TAG_SYNC);
    } catch (error) {
      // Sin Background Sync (iPhone): la cola se envía al volver a abrir la
      // app o al recuperar la conexión con ella abierta (offline-status.js).
    }
  }

  async function guardarEnElTelefono(form, datos, motivoSesion) {
    try {
      await window.ArcaOffline.agregarPendiente(datos);
    } catch (error) {
      aviso(form, "danger",
        "<strong>No se pudo guardar.</strong> No hay conexión y este navegador no permite guardar en el teléfono. " +
        "No cierres esta pantalla e inténtalo de nuevo cuando tengas señal.");
      return;
    }
    registrarSyncEnSegundoPlano();
    limpiar(form);
    if (motivoSesion) {
      aviso(form, "warning",
        '<i class="bi bi-person-lock me-1"></i> <strong>No se envió.</strong> ' + motivoSesion +
        " El " + datos.tipo + ' quedó guardado en este teléfono. <a href="/cuentas/login/">Iniciar sesión</a>');
    } else {
      aviso(form, "warning",
        '<i class="bi bi-cloud-slash-fill me-1"></i> <strong>Sin conexión.</strong> El ' + datos.tipo +
        " quedó guardado en este teléfono y se enviará solo cuando vuelva la señal. Puedes seguir registrando.");
    }
    document.dispatchEvent(new CustomEvent("arca:cola-cambio"));
  }

  function conectar(form) {
    var botonUsado = null;
    form.querySelectorAll('button[type="submit"]').forEach(function (boton) {
      boton.addEventListener("click", function () { botonUsado = boton; });
    });

    form.addEventListener("submit", async function (evento) {
      if (form.dataset.envioNormal) return; // segunda pasada: POST de siempre
      evento.preventDefault();
      if (form.dataset.ocupado) return;     // doble toque
      if (typeof form.reportValidity === "function" && !form.reportValidity()) return;

      form.dataset.ocupado = "1";
      var botones = form.querySelectorAll('button[type="submit"]');
      botones.forEach(function (b) { b.disabled = true; });
      var registrarOtro = !!(botonUsado && botonUsado.name === "otro");
      var datos = leer(form);

      try {
        var resultado = navigator.onLine
          ? await window.ArcaOffline.enviar(datos, form.elements.csrfmiddlewaretoken.value)
          : { estado: "sin_conexion" };

        if (resultado.estado === "ok") {
          var c = resultado.cuerpo;
          var texto = c.tipo + " #" + c.numero_vale + (c.por_aprobar ? " registrado. Queda por aprobar." : " registrado.");
          if (registrarOtro) {
            limpiar(form);
            aviso(form, "success", '<i class="bi bi-check-circle-fill me-1"></i> ' + texto);
          } else {
            try { sessionStorage.setItem("arca_aviso", JSON.stringify({ clase: "success", texto: texto })); } catch (e) {}
            window.location.assign(c.url);
            return; // se va de la página: los botones quedan deshabilitados
          }
        } else if (resultado.estado === "sesion") {
          // Sesión cerrada: un POST normal iría al login y se perdería lo escrito.
          await guardarEnElTelefono(form, datos, resultado.detalle);
        } else if (resultado.estado === "rechazado") {
          // Que el servidor pinte los errores con el POST normal.
          // No duplica: el intento anterior no guardó nada.
          form.dataset.envioNormal = "1";
          if (registrarOtro) {
            var oculto = document.createElement("input");
            oculto.type = "hidden"; oculto.name = "otro"; oculto.value = "1";
            form.appendChild(oculto);
          }
          form.submit();
          return;
        } else {
          await guardarEnElTelefono(form, datos);
        }
      } finally {
        delete form.dataset.ocupado;
        botones.forEach(function (b) { b.disabled = false; });
        botonUsado = null;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!window.ArcaOffline || !("indexedDB" in window)) return;
    document.querySelectorAll("form[data-offline]").forEach(conectar);
  });
})();
