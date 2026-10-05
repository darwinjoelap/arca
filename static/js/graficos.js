// graficos.js — Globo de detalle al pasar por (o enfocar) una columna del
// gráfico. Los valores vienen ya formateados en data-*, así que aquí no se
// calcula nada: solo se muestra y se posiciona.
(function () {
  "use strict";
  document.querySelectorAll(".grafico-contenedor").forEach(function (contenedor) {
    var globo = contenedor.querySelector(".grafico-globo");
    if (!globo) return;

    function mostrar(banda, evento) {
      globo.innerHTML = "";
      var titulo = document.createElement("strong");
      titulo.textContent = banda.dataset.titulo;
      globo.appendChild(titulo);
      (banda.dataset.lineas || "").split("|").forEach(function (linea) {
        var div = document.createElement("div");
        div.textContent = linea;
        globo.appendChild(div);
      });
      globo.hidden = false;
      var caja = contenedor.getBoundingClientRect();
      var marca = banda.getBoundingClientRect();
      var x = (evento && evento.clientX ? evento.clientX : marca.left + marca.width / 2) - caja.left + 12;
      if (x + globo.offsetWidth > caja.width) x = x - globo.offsetWidth - 24;
      globo.style.left = Math.max(0, x) + "px";
      globo.style.top = "8px";
    }
    contenedor.querySelectorAll(".banda").forEach(function (banda) {
      banda.addEventListener("mousemove", function (e) { mostrar(banda, e); });
      banda.addEventListener("focus", function () { mostrar(banda, null); });
      banda.addEventListener("mouseleave", function () { globo.hidden = true; });
      banda.addEventListener("blur", function () { globo.hidden = true; });
    });
  });
})();
