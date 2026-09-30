#!/usr/bin/env python3
"""
proxy_e2e.py — proxy HTTP del emulador E2E: internet abierto, produccion bloqueada.

El emulador arranca con `-http-proxy http://127.0.0.1:<puerto>`: toda conexion TCP de la app pasa
por aqui (CONNECT host:puerto). Se deja pasar todo salvo los servidores de produccion del proyecto
(por nombre y por las IPs a las que resuelven), y se anota cada destino en el log. 10.0.2.2 (el
localhost de la maquina visto desde el emulador) se reenvia a 127.0.0.1.

uso: proxy_e2e.py <puerto> <bloqueados.json> <log>
     bloqueados.json: {"hosts": ["prod.example.com", ...]}
"""
import json
import select
import socket
import sys
import threading
import time


def resolver(hosts):
    ips = {}
    for h in hosts:
        try:
            for info in socket.getaddrinfo(h, None):
                ips[info[4][0]] = h
        except OSError:
            pass
    return ips


class Proxy:
    def __init__(self, puerto, hosts, log):
        self.hosts = {h.lower() for h in hosts}
        self.ips = resolver(self.hosts)
        self.log = open(log, "a", buffering=1)
        self.puerto = puerto
        self.lock = threading.Lock()

    def anotar(self, estado, destino):
        with self.lock:
            self.log.write("%s %s %s\n" % (time.strftime("%H:%M:%S"), estado, destino))

    def bloqueado(self, host):
        h = host.lower().strip("[]")
        return h in self.hosts or h in self.ips or any(h.endswith("." + b) for b in self.hosts)

    def atender(self, cli):
        destino_txt = "?"
        try:
            cli.settimeout(30)
            data = b""
            while b"\r\n\r\n" not in data and len(data) < 65536:
                trozo = cli.recv(4096)
                if not trozo:
                    return
                data += trozo
            linea = data.split(b"\r\n", 1)[0].decode("latin-1")
            metodo, destino, _ = (linea.split(" ") + ["", ""])[:3]
            if metodo.upper() == "CONNECT":
                host, _, puerto = destino.rpartition(":")
                resto = b""
            else:  # HTTP plano con URL absoluta
                sin = destino.split("://", 1)[-1]
                hostport = sin.split("/", 1)[0]
                host, _, puerto = hostport.partition(":")
                puerto = puerto or "80"
                resto = data
            nombre = self.ips.get(host, host)
            destino_txt = "%s:%s" % (host, puerto)
            if self.bloqueado(host):
                self.anotar("BLOQUEADO", "%s:%s (%s)" % (host, puerto, nombre))
                cli.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                return
            host = host.strip("[]")          # IPv6 viene como [2001:db8::1]
            real = "127.0.0.1" if host == "10.0.2.2" else host
            srv = socket.create_connection((real, int(puerto)), timeout=20)
            self.anotar("OK", "%s:%s%s" % (host, puerto, "" if nombre == host else " (%s)" % nombre))
            if metodo.upper() == "CONNECT":
                cli.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            else:
                srv.sendall(resto)
            self.tunel(cli, srv)
        except Exception as e:  # una conexion que falla no tumba el proxy
            self.anotar("ERROR", "%s %s" % (destino_txt, str(e)[:100]))
        finally:
            try:
                cli.close()
            except OSError:
                pass

    @staticmethod
    def tunel(a, b):
        a.settimeout(None)
        b.settimeout(None)
        socks = [a, b]
        try:
            while True:
                listos, _, _ = select.select(socks, [], [], 300)
                if not listos:
                    return
                for s in listos:
                    d = s.recv(65536)
                    if not d:
                        return
                    (b if s is a else a).sendall(d)
        finally:
            b.close()

    def correr(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", self.puerto))
        srv.listen(128)
        self.anotar("INICIO", "bloqueados: %s" % ", ".join(sorted(self.hosts)) or "ninguno")
        while True:
            cli, _ = srv.accept()
            threading.Thread(target=self.atender, args=(cli,), daemon=True).start()


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    hosts = json.load(open(sys.argv[2])).get("hosts", [])
    Proxy(int(sys.argv[1]), hosts, sys.argv[3]).correr()
