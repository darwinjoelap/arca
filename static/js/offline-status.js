// offline-status.js — Aviso de «sin conexión», contador de pendientes, panel
// para revisarlos, y envío de la cola al abrir la app o al volver la señal.
//
// No depende de Background Sync (iPhone no lo tiene): se ejecuta en cualquier
// navegador, así que la cola se vacía apenas alguien abre Arca con señal.
(function () {
  "use strict";

  var formato = new Intl.NumberFormat("es-VE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function escapar(texto) {
    var div = document.createElement("div");
    div.textContent = texto == null ? "" : String(texto);
    return div.innerHTML;
  }

  function mostrarAviso(clase, html) {
    var contenedor = document.querySelector(".arca-content");
    if (!contenedor) return;
    var caja = document.createElement("div");
    caja.className = "alert alert-" + clase + " shadow-sm";
    caja.setAttribute("role", "status");
    caja.innerHTML = html;
    contenedor.prepend(caja);
  }

  function avisoDeLaPaginaAnterior() {
    var guardado;
    try {
      guardado = sessionStorage.getItem("arca_aviso");
      if (guardado) sessionStorage.removeItem("arca_aviso");
    } catch (error) {
      return;
    }
    if (!guardado) return;
    try {
      var aviso = JSON.parse(guardado);
      mostrarAviso(aviso.clase, '<i class="bi bi-check-circle-fill me-1"></i> ' + escapar(aviso.texto));
    } catch (error) { /* aviso ilegible: se ignora */ }
  }

  function pintarConexion() {
    var banda = document.getElementById("arca-sin-conexion");
    if (banda) banda.classList.toggle("d-none", navigator.onLine);
  }

  async function actualizarIndicador() {
    var boton = document.getElementById("arca-offline-boton");
    var contador = document.getElementById("arca-offline-contador");
    if (!boton || !contador) return;
    var total = await window.ArcaOffline.contarPendientes();
    contador.textContent = total;
    boton.classList.toggle("d-none", total === 0);
    boton.classList.toggle("d-inline-flex", total > 0);
    if (document.getElementById("arca-offline-lista")) pintarLista();
  }

  async function pintarLista() {
    var lista = document.getElementById("arca-offline-lista");
    if (!lista) return;
    var pendientes = [];
    try { pendientes = await window.ArcaOffline.listarPendientes(); } catch (error) {}
    if (!pendientes.length) {
      lista.innerHTML = '<p class="text-muted mb-0">No hay nada pendiente por enviar.</p>';
      return;
    }
    lista.innerHTML = pendientes.map(function (p) {
      var r = p._resumen || {};
      var esIngreso = (r.tipo || p.tipo) === "ingreso";
      var monto = parseFloat(r.monto);
      return (
        '<div class="border rounded p-2 mb-2" data-uuid="' + escapar(p.uuid_cliente) + '">' +
          '<div class="d-flex justify-content-between gap-2">' +
            '<span><span class="fw-semibold">' + escapar(r.titulo || "(sin descripción)") + "</span>" +
              '<div class="small text-muted">' + (esIngreso ? "Ingreso" : "Egreso") + " · " + escapar((r.fecha || "").split("-").reverse().join("/")) + " · " + escapar(r.cuenta || "") + "</div></span>" +
            '<span class="monto text-nowrap ' + (esIngreso ? "monto-ingreso" : "monto-egreso") + '">' + (isNaN(monto) ? "" : formato.format(monto)) + "</span>" +
          "</div>" +
          (p._estado === "error"
            ? '<div class="small text-danger mt-1"><i class="bi bi-exclamation-triangle-fill"></i> No se pudo guardar: ' + escapar(p._error || "el servidor lo rechazó.") + "</div>" +
              '<div class="mt-2 d-flex gap-2"><button type="button" class="btn btn-sm btn-outline-secondary" data-accion="reintentar">Reintentar</button>' +
              '<button type="button" class="btn btn-sm btn-outline-danger" data-accion="descartar">Descartar</button></div>'
            : '<div class="small text-muted mt-1"><i class="bi bi-hourglass-split"></i> Esperando conexión' +
              ' <button type="button" class="btn btn-link btn-sm p-0 ms-2 text-danger" data-accion="descartar">Descartar</button></div>') +
        "</div>"
      );
    }).join("");
  }

  var ultimoAvisoSesion = 0;
  async function sincronizar(manual) {
    if (!navigator.onLine) {
      if (manual) mostrarAviso("warning", "Sigues sin conexión. Lo pendiente se enviará solo cuando vuelva la señal.");
      return;
    }
    var resumen = await window.ArcaOffline.sincronizarCola();
    await actualizarIndicador();
    if (resumen.enviados) {
      mostrarAviso("success", '<i class="bi bi-cloud-check-fill me-1"></i> Se ' +
        (resumen.enviados === 1 ? "envió 1 movimiento pendiente." : "enviaron " + resumen.enviados + " movimientos pendientes."));
    }
    if (resumen.rechazados) {
      mostrarAviso("danger", '<i class="bi bi-exclamation-triangle-fill me-1"></i> ' + resumen.rechazados +
        " pendiente(s) no se pudieron guardar. Toca «pendientes» arriba para revisarlos.");
    }
    if (resumen.sesion && (manual || Date.now() - ultimoAvisoSesion > 60000)) {
      ultimoAvisoSesion = Date.now();
      mostrarAviso("warning", escapar(resumen.sesion));
    }
    if (manual && !resumen.enviados && !resumen.rechazados && !resumen.sesion) {
      var quedan = await window.ArcaOffline.contarPendientes();
      if (quedan) mostrarAviso("warning", "No se pudo enviar todavía. Se volverá a intentar solo.");
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    pintarConexion();
    avisoDeLaPaginaAnterior();
    if (!window.ArcaOffline) return;
    actualizarIndicador();
    sincronizar(false);

    var enviarAhora = document.getElementById("arca-offline-enviar");
    if (enviarAhora) {
      enviarAhora.addEventListener("click", function () {
        enviarAhora.disabled = true;
        sincronizar(true).finally(function () { enviarAhora.disabled = false; });
      });
    }
    var modal = document.getElementById("arcaPendientes");
    if (modal) modal.addEventListener("show.bs.modal", pintarLista);

    var lista = document.getElementById("arca-offline-lista");
    if (lista) {
      lista.addEventListener("click", async function (evento) {
        var boton = evento.target.closest("[data-accion]");
        if (!boton) return;
        var uuid = boton.closest("[data-uuid]").dataset.uuid;
        if (boton.dataset.accion === "descartar") {
          if (!window.confirm("¿Descartar este registro? No se enviará y no se puede recuperar.")) return;
          await window.ArcaOffline.eliminarPendiente(uuid);
        } else {
          await window.ArcaOffline.marcar(uuid, "pendiente", null);
          await sincronizar(true);
        }
        actualizarIndicador();
      });
    }
  });

  window.addEventListener("online", function () { pintarConexion(); if (window.ArcaOffline) sincronizar(false); });
  window.addEventListener("offline", pintarConexion);
  document.addEventListener("arca:cola-cambio", function () { if (window.ArcaOffline) actualizarIndicador(); });
  // Al volver a la app (cambio de pestaña, desbloqueo del teléfono).
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && window.ArcaOffline) { pintarConexion(); sincronizar(false); }
  });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("message", function (evento) {
      if (evento.data && evento.data.tipo === "arca-offline-sync" && window.ArcaOffline) actualizarIndicador();
    });
  }
})();
