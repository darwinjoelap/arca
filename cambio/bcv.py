"""Consulta de la tasa oficial en la página del BCV.

Se lee el bloque del dólar (id="dolar") y la «Fecha Valor» que publica el
banco. La tasa se guarda con ESA fecha, no con la de hoy: el BCV publica en la
tarde la tasa del siguiente día hábil, y así los movimientos de hoy siguen
usando la de hoy.

El servidor del BCV no envía su certificado intermedio, así que la
verificación TLS falla. No se desactiva: se descarga el intermedio desde la
dirección que el propio certificado declara (AIA) y se verifica contra las
raíces de certifi más ese intermedio. Nunca se agregan raíces descargadas.
"""

import logging
import os
import ssl
import tempfile
import warnings
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from django.utils import timezone

from .models import TasaCambio

log = logging.getLogger("arca.cambio")
URL_BCV = "https://www.bcv.org.ve/"
CABECERAS = {"User-Agent": "Mozilla/5.0 (Arca)"}
SALTO_MAXIMO = Decimal("0.5")  # una tasa que cambia más de 50 % de golpe es una lectura mala


class ErrorBCV(Exception):
    """No se pudo leer una tasa confiable de la página del BCV."""


def leer_tasa_html(html):
    """(valor, fecha_valor) a partir del HTML del BCV. `fecha_valor` es None
    si la página no la trae en el formato esperado."""
    from bs4 import BeautifulSoup

    sopa = BeautifulSoup(html, "html.parser")
    bloque = sopa.find(id="dolar")
    fuerte = bloque.find("strong") if bloque else None
    if not fuerte:
        raise ErrorBCV("No se encontró el bloque del dólar en la página del BCV.")
    texto = fuerte.get_text(strip=True).replace(".", "").replace(",", ".")
    try:
        valor = Decimal(texto).quantize(Decimal("0.0001"))
    except InvalidOperation:
        raise ErrorBCV(f"El valor de la tasa no es un número: {texto!r}")
    if valor <= 0:
        raise ErrorBCV("La tasa debe ser mayor que cero.")

    fecha = None
    marca = sopa.find(class_="date-display-single")
    if marca is not None and marca.get("content"):
        try:
            fecha = date.fromisoformat(marca["content"][:10])
        except ValueError:
            fecha = None
    return valor, fecha


# --- Certificado incompleto del BCV ------------------------------------------


def _sha256():
    from cryptography.hazmat.primitives import hashes
    return hashes.SHA256()


def _urls_ca_issuers(cert):
    from cryptography import x509
    from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID
    try:
        aia = cert.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
    except x509.ExtensionNotFound:
        return []
    return [d.access_location.value for d in aia if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS]


def _cargar_certs(datos, url=""):
    """Certificados de una descarga AIA: DER, PEM o PKCS#7."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import pkcs7
    intentos = (
        lambda d: [x509.load_der_x509_certificate(d)],
        lambda d: x509.load_pem_x509_certificates(d),
        lambda d: pkcs7.load_der_pkcs7_certificates(d),
        lambda d: pkcs7.load_pem_pkcs7_certificates(d),
    )
    for cargar in intentos:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)  # el PKCS#7 del BCV viene en BER
                certs = cargar(datos)
            if certs:
                return certs
        except Exception:  # noqa: BLE001 - se prueba el siguiente formato
            continue
    raise ErrorBCV(f"Formato de certificado no reconocido en {url}.")


def _intermedios_por_aia(host, port=443, max_niveles=3):
    import requests
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    cert = x509.load_pem_x509_certificate(ssl.get_server_certificate((host, port), timeout=20).encode())
    intermedios, vistos = [], set()
    for _ in range(max_niveles):
        urls = _urls_ca_issuers(cert)
        if not urls:
            break
        respuesta = requests.get(urls[0], timeout=20, headers=CABECERAS)
        respuesta.raise_for_status()
        siguiente = None
        for c in _cargar_certs(respuesta.content, urls[0]):
            huella = c.fingerprint(_sha256())
            if c.issuer == c.subject or huella in vistos:
                continue  # raíz: no se agrega, debe estar en certifi
            vistos.add(huella)
            intermedios.append(c.public_bytes(Encoding.PEM).decode())
            if c.subject == cert.issuer:
                siguiente = c
        if siguiente is None:
            break
        cert = siguiente
    return intermedios


def _bundle_con_intermedios(host, port=443):
    import certifi

    intermedios = _intermedios_por_aia(host, port)
    if not intermedios:
        raise ErrorBCV(f"No se pudo obtener el certificado intermedio de {host}.")
    with open(certifi.where()) as f:
        base = f.read()
    fd, ruta = tempfile.mkstemp(prefix="arca-ca-", suffix=".pem")
    with os.fdopen(fd, "w") as f:
        f.write(base + "\n" + "\n".join(intermedios))
    return ruta


def descargar(url=None):
    """El HTML de la página del BCV."""
    import requests

    url = url or URL_BCV
    try:
        respuesta = requests.get(url, timeout=20, headers=CABECERAS)
    except requests.exceptions.SSLError:
        log.info("BCV sin certificado intermedio: se completa la cadena por AIA.")
        u = urlparse(url)
        ruta = _bundle_con_intermedios(u.hostname, u.port or 443)
        try:
            respuesta = requests.get(url, timeout=20, headers=CABECERAS, verify=ruta)
        finally:
            os.remove(ruta)
    respuesta.raise_for_status()
    return respuesta.text


# --- Registro ------------------------------------------------------------------


def registrar(valor, fecha=None, usuario=None):
    """Guarda la tasa BCV de `fecha`. Devuelve (tasa, estado) con estado
    "nueva", "igual" o "corregida". Rechaza un salto absurdo respecto a la
    última tasa BCV: es más probable una lectura mala que una devaluación."""
    fecha = fecha or timezone.localdate()
    anterior = (
        TasaCambio.objects.filter(fuente=TasaCambio.Fuente.BCV, fecha__lt=fecha).order_by("-fecha").first()
    )
    if anterior and abs(valor - anterior.valor) / anterior.valor > SALTO_MAXIMO:
        raise ErrorBCV(
            f"La tasa leída ({valor}) cambia demasiado respecto a la anterior ({anterior.valor}). "
            "No se guardó: revísala y cárgala a mano si es correcta."
        )
    tasa = TasaCambio.objects.filter(fuente=TasaCambio.Fuente.BCV, fecha=fecha).first()
    if tasa is None:
        return TasaCambio.objects.create(
            fecha=fecha, valor=valor, fuente=TasaCambio.Fuente.BCV, cargada_por=usuario
        ), "nueva"
    if tasa.valor == valor:
        return tasa, "igual"
    tasa.valor = valor
    tasa.save()  # recalcula lo que aún no está congelado
    return tasa, "corregida"


def actualizar(usuario=None):
    """Consulta el BCV y guarda la tasa. Devuelve (tasa, estado) o lanza
    ErrorBCV / un error de red."""
    valor, fecha = leer_tasa_html(descargar())
    return registrar(valor, fecha, usuario)
