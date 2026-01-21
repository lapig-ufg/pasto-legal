import json
import requests
import textwrap

from typing import Literal

from agno.run import RunContext
from agno.tools import tool
from agno.tools.function import ToolResult

from app.utils.image_scripts import get_mosaic
from app.utils.gee_scripts import retrieve_feature_image
from app.utils.dummy_logger import log


# TODO: As vezes o request retorna 302 e 307 de redirecionamento. Garantir que não ira redirecionar com allow_redirects=False. Ou tentar conexão direta com a API.
@tool

def query_car(latitude: float, longitude: float, run_context: RunContext):
    """
    Recupera as própriedades com Cadastro Ambiental Rural (CAR) para a coordenada informada.

    Args:
        latitude (float): Latitude in decimal degrees 
        longitude (float): Longitude in decimal degrees

    Returns:
        ToolResult: Imagem com todos os CARs encontrados para seleção da propriedade do usuário.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://consultapublica.car.gov.br/publico/imoveis/index'
    }

    sess = requests.Session()

    base_url = "https://consultapublica.car.gov.br/publico/imoveis/index"

    try:
        sess.get(base_url, verify=False, headers=headers, timeout=5)

        url_api = f'https://consultapublica.car.gov.br/publico/imoveis/getImovel?lat={latitude}&lng={longitude}'
        response = sess.get(url_api, verify=False, headers=headers, timeout=5)

        response.raise_for_status()

        try:
            result = response.json()
        except json.JSONDecodeError:
            raise ValueError("O servidor retornou uma resposta inválida (não é JSON).")

        features = result.get("features", [])

        if not features:
            return textwrap.dedent("""
                Falha: Nenhuma propriedade rural (CAR) foi encontrada nestas coordenadas. 
                Informe ao usuário que o local indicado não consta na base pública do CAR e 
                peça para ele garantir que esta dentro da área da propriedade.
            """).strip()
            
        run_context.session_state['car'] = result

        return ToolResult(content= "A imagem contém 3 propriedades CAR distintas enúmeradas como A, B e C. Peça que o usuário escolha entre uma das opções.")
    except requests.exceptions.Timeout:
        return "Erro: O servidor do CAR demorou muito para responder. Peça ao usuário para tentar novamente em alguns minutos."
    except requests.exceptions.ConnectionError:
        return "Erro: Falha na conexão com o site do CAR. Pode ser uma instabilidade no site do governo. Peça para tentar mais tarde."
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code

        if status == 403:
            return "Erro: Acesso negado pelo servidor."
        
        return f"Erro HTTP {status}: Ocorreu um problema técnico ao acessar a base do CAR."
    except Exception as e:
        return f"Erro Inesperado: {str(e)}. Peça desculpas ao usuário e informe que houve um erro interno no processamento."


@tool
def select_car(selection: Literal['A', 'B', 'C', 'D', 'E'], run_context: RunContext):
    """
    Seleciona uma das própriedades de Cadastro Ambiental Rural (CAR) para armazenar no sistema.

    Args:
        selection (Literal['A', 'B', 'C', 'D', 'E']): Letra representando a própriedade CAR escolhida pelo usuário.

    Returns:
        str: Resultado da operação.
    """
    log(selection)
    return "Informe ao usuário que o CAR foi salvo com sucesso e que será mantido na memória do sistema por 3 meses e ele pode pedir para remover a qualquer momento"


@tool
def confirm_car():
    pass