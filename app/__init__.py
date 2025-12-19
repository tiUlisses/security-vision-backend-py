"""
Inicializações globais do pacote app.

- Aplica patch em httpx para garantir que AsyncClient(app=...) use ASGITransport,
  mesmo em versões que descontinuaram o atalho, evitando chamadas reais de rede
  durante testes.
"""

import httpx


def _patch_httpx_app_transport() -> None:
    original_async_init = httpx.AsyncClient.__init__
    original_sync_init = httpx.Client.__init__

    def _inject_transport(original_init):
        def wrapper(self, *args, **kwargs):
            app = kwargs.pop("app", None)
            if app is not None and "transport" not in kwargs:
                kwargs["transport"] = httpx.ASGITransport(app=app)
                kwargs.setdefault("base_url", "http://testserver")
            return original_init(self, *args, **kwargs)

        return wrapper

    httpx.AsyncClient.__init__ = _inject_transport(original_async_init)
    httpx.Client.__init__ = _inject_transport(original_sync_init)


_patch_httpx_app_transport()
