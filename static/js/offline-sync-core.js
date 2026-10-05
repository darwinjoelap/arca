// offline-sync-core.js — Cola offline de Arca (heredada de la Fase 7 de Edumia).
//
// Se carga tal cual (sin type="module") en las páginas y en el service worker
// (con importScripts): por eso no usa import/export ni toca el DOM. Solo
// IndexedDB y fetch, colgado de `self`/`window`.
//
// Una sola cola, «movimientos»: cada registro es lo que el formulario iba a
// enviar, más unos campos internos que empiezan con «_».
(function (global) {
  "use strict";

  const DB_NOMBRE = "arca-offline";
  const DB_VERSION = 1;
  const ALMACEN = "cola_movimientos";
  const URL_SYNC = "/sync/api/movimiento/";
  const TAG_SYNC = "sync-movimientos";
  const ESPERA_MS = 12000;

  function abrirDB() {
    return new Promise((resolve, reject) => {
      if (!("indexedDB" in global)) {
        reject(new Error("IndexedDB no disponible en este navegador."));
        return;
      }
      const solicitud = indexedDB.open(DB_NOMBRE, DB_VERSION);
      solicitud.onupgradeneeded = () => {
        const db = solicitud.result;
        if (!db.objectStoreNames.contains(ALMACEN)) {
          db.createObjectStore(ALMACEN, { keyPath: "uuid_cliente" });
        }
      };
      solicitud.onsuccess = () => resolve(solicitud.result);
      solicitud.onerror = () => reject(solicitud.error);
    });
  }

  async function operar(modo, accion) {
    const db = await abrirDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(ALMACEN, modo);
      const resultado = accion(tx.objectStore(ALMACEN));
      tx.oncomplete = () => resolve(resultado && "result" in resultado ? resultado.result : undefined);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  }

  function agregarPendiente(datos) {
    return operar("readwrite", (almacen) =>
      almacen.put({ ...datos, _offline: true, _guardado_en: new Date().toISOString(), _estado: "pendiente", _error: null })
    );
  }

  function listarPendientes() {
    return operar("readonly", (almacen) => almacen.getAll()).then((lista) =>
      (lista || []).sort((a, b) => (a._guardado_en < b._guardado_en ? -1 : 1))
    );
  }

  function eliminarPendiente(uuidCliente) {
    return operar("readwrite", (almacen) => almacen.delete(uuidCliente));
  }

  async function marcar(uuidCliente, estado, mensaje) {
    const db = await abrirDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(ALMACEN, "readwrite");
      const almacen = tx.objectStore(ALMACEN);
      const solicitud = almacen.get(uuidCliente);
      solicitud.onsuccess = () => {
        const registro = solicitud.result;
        if (registro) {
          registro._estado = estado;
          registro._error = mensaje || null;
          almacen.put(registro);
        }
      };
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  function leerCookie(nombre) {
    if (typeof document === "undefined") return null;
    const partes = `; ${document.cookie}`.split(`; ${nombre}=`);
    if (partes.length === 2) return partes.pop().split(";").shift();
    return null;
  }

  // Envía un registro al servidor y dice qué pasó. NO toca la cola.
  //   {estado: "ok", cuerpo}         se guardó o ya existía.
  //   {estado: "rechazado", detalle} el servidor dijo que los datos o el permiso están mal.
  //   {estado: "sesion", detalle}    no hay sesión, o es de otra persona u organización.
  //   {estado: "sin_conexion"}       no hubo respuesta útil: se puede reintentar.
  //
  // Solo es «ok» si la respuesta es JSON con `resultado`. Una página HTML con
  // 200 (un login tras una redirección, un portal cautivo de wifi) NO cuenta
  // como guardado: darla por buena borraría de la cola algo que nunca llegó.
  async function enviar(datos, csrf) {
    const cuerpoEnvio = {};
    Object.keys(datos).forEach((clave) => {
      if (!["_guardado_en", "_estado", "_error", "_resumen"].includes(clave)) cuerpoEnvio[clave] = datos[clave];
    });
    const control = typeof AbortController !== "undefined" ? new AbortController() : null;
    const reloj = control ? setTimeout(() => control.abort(), ESPERA_MS) : null;
    let respuesta;
    try {
      respuesta = await fetch(URL_SYNC, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf || leerCookie("csrftoken") || "" },
        credentials: "same-origin",
        redirect: "manual",
        signal: control ? control.signal : undefined,
        body: JSON.stringify(cuerpoEnvio),
      });
    } catch (error) {
      return { estado: "sin_conexion" };
    } finally {
      if (reloj) clearTimeout(reloj);
    }

    let cuerpo = null;
    try {
      cuerpo = await respuesta.json();
    } catch (error) {
      cuerpo = null;
    }
    if ((respuesta.status === 200 || respuesta.status === 201) && cuerpo && cuerpo.resultado) {
      return { estado: "ok", cuerpo };
    }
    if (cuerpo && (respuesta.status === 401 || respuesta.status === 409)) {
      return { estado: "sesion", detalle: cuerpo.detalle || "Inicia sesión para enviar lo pendiente." };
    }
    if (cuerpo && cuerpo.detalle && (respuesta.status === 422 || respuesta.status === 403)) {
      return { estado: "rechazado", detalle: cuerpo.detalle, errores: cuerpo.errores || null };
    }
    // Redirección, HTML, 5xx, CSRF vencido…: nada de eso prueba que se guardó.
    return { estado: "sin_conexion" };
  }

  // Recorre la cola e intenta enviar lo pendiente. Los marcados «error» se
  // saltan: esperan a que la persona los revise (ver el panel de pendientes).
  // Devuelve {enviados, rechazados, sesion}.
  let sincronizando = null;
  function sincronizarCola() {
    if (sincronizando) return sincronizando;
    sincronizando = (async () => {
      const resumen = { enviados: 0, rechazados: 0, sesion: null };
      let pendientes;
      try {
        pendientes = (await listarPendientes()).filter((r) => r._estado !== "error");
      } catch (error) {
        return resumen;
      }
      for (const registro of pendientes) {
        const resultado = await enviar(registro);
        if (resultado.estado === "ok") {
          await eliminarPendiente(registro.uuid_cliente);
          resumen.enviados += 1;
        } else if (resultado.estado === "rechazado") {
          await marcar(registro.uuid_cliente, "error", resultado.detalle);
          resumen.rechazados += 1;
        } else if (resultado.estado === "sesion") {
          resumen.sesion = resultado.detalle;
          continue; // puede haber otros pendientes que sí sean de esta sesión
        } else {
          break; // sin red: los siguientes tampoco van a pasar ahora
        }
      }
      return resumen;
    })().finally(() => {
      sincronizando = null;
    });
    return sincronizando;
  }

  async function contarPendientes() {
    try {
      return (await listarPendientes()).length;
    } catch (error) {
      return 0;
    }
  }

  global.ArcaOffline = {
    TAG_SYNC,
    agregarPendiente,
    listarPendientes,
    eliminarPendiente,
    marcar,
    enviar,
    sincronizarCola,
    contarPendientes,
  };
})(typeof self !== "undefined" ? self : this);
