"""Inicialização do Earth Engine para os testes de integração de biomassa.

`app.services.geospatial.gee` autentica e chama `ee.Initialize` na importação do
módulo, então importá-lo aqui é o que habilita os testes que tocam o GEE. Os
testes herméticos (schemas, conversões e guardas) não passam por este conftest
porque não importam `ee`.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def initialize_earth_engine():
    """Inicializa o Earth Engine uma vez por sessão, pulando os testes sem credencial."""
    try:
        import app.services.geospatial.gee  # noqa: F401
    except Exception as error:
        pytest.skip(f"Earth Engine indisponível neste ambiente: {error}", allow_module_level=True)
