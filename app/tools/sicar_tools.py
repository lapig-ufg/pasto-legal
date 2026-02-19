import json
import requests
import textwrap

from io import BytesIO

from agno.run import RunContext
from agno.tools import tool
from agno.tools.function import ToolResult
from agno.media import Image

from app.utils.scripts.image_scripts import get_mosaic
from app.utils.scripts.gee_scripts import retrieve_feature_images
from app.utils.dummy_logger import log, error


@tool
def query_car(latitude: float, longitude: float, run_context: RunContext):
    """
    Busca imóveis no Cadastro Ambiental Rural (CAR) baseando-se nas coordenadas fornecidas.
    
    Use esta ferramenta quando o usuário fornecer uma localização (latitude/longitude) e quiser verificar propriedades rurais.
    
    Args:
        latitude (float): Latitude em graus decimais.
        longitude (float): Longitude em graus decimais.

    Returns:
        ToolResult: Resultado da busca contendo imagem e instruções para o próximo passo.
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
            return ToolResult(content=textwrap.dedent("""
                [FALHA] Nenhuma propriedade foi encontrada nesta coordenada. 
                                                      
                # INTRUÇÕES
                - Informe ao usuário que o local indicado não consta na base pública do CAR. 
            """).strip())
        
        size_feat = len(features)

        imgs = retrieve_feature_images(result)
        mosaic = get_mosaic(imgs)

        buffer = BytesIO()
        mosaic.save(buffer, format="PNG")
        
        if size_feat == 1:
            run_context.session_state['car_candidate'] = features[0]
            run_context.session_state['is_confirming_car'] = True

            cars = f"CAR {features[0]["properties"]["codigo"]}, Tamanho da área {round(features[0]["properties"]["area"])} ha, município de {features[0]["properties"]["municipio"]}."

            return ToolResult(
                content=textwrap.dedent("""
                [STATUS: 1 PROPRIEDADE ENCONTRADA]

                # INSTRUÇÕES PARA O AGENTE:
                1. Informe ao usuário as informações das propriedades na integra:
                    {cars}
                2. Pergunte: "É esta a propriedade correta?"
                3. Se o usuário confirmar, chame a ferramenta 'confirm_car_selection'.
                """).strip(),
                images=[Image(content=buffer.getvalue())]
                )
        
        elif size_feat > 1:
            run_context.session_state['car_all'] = features
            run_context.session_state['is_selecting_car'] = True

            # TODO: Conflito com as Áreas (Área da imagem e Área da medida)
            cars = "- ".join(f"Área {i + 1}, CAR {features[i]["properties"]["codigo"]}, Tamanho da área {round(features[i]["properties"]["area"])} ha, município de {features[i]["properties"]["municipio"]}.\n" for i in range(0, size_feat))

            return ToolResult(
                content=textwrap.dedent(f"""
                [STATUS: {size_feat} PROPRIEDADES ENCONTRADAS]
                
                # INSTRUÇÕES PARA O AGENTE:
                1. Informe ao usuário as informações das propriedades na integra:
                    {cars}
                2. Peça ao usuário que escolhe um propriedade entre as informadas.
                3. Quando o usuário responder com um número, chame a ferramenta 'select_car_from_list'.
                """).strip(),
                images=[Image(content=buffer.getvalue())]
                )
        
    except requests.exceptions.Timeout:
        return ToolResult(content=textwrap.dedent("""
                [FALHA] O servidor do SICAR demorou muito para responder.
                                                      
                # INTRUÇÕES
                - Peça ao usuário para tentar novamente mais tarde.
            """).strip())
    except requests.exceptions.ConnectionError:
        return ToolResult(content=textwrap.dedent("""
                [FALHA] Falha na conexão com o site do SICAR.
                                                      
                # INTRUÇÕES
                - Peça ao usuário para tentar novamente mais tarde.
            """).strip())
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code

        if status == 403:
            return "Erro: Acesso negado pelo servidor."
        
        return f"Erro HTTP {status}: Ocorreu um problema técnico ao acessar a base do CAR."
    except Exception as e:
        error(e)
        return ToolResult(content=textwrap.dedent("""
                [FALHA] Houve um erro interno. 
                                                      
                # INTRUÇÕES
                - Peça desculpas ao usuário e informe que houve um erro interno.
                - Peça que usuário tente novamente mais tarde.
            """).strip())


@tool
def select_car_from_list(selection: int, run_context: RunContext):
    """
    Seleciona uma propriedade específica quando a busca retorna múltiplos resultados.
    
    Use esta ferramenta APENAS quando o usuário fornecer um número correspondente a uma das opções apresentadas anteriormente.

    Args:
        selection (int): O número da opção escolhida pelo usuário (ex: 1, 2, 3...).
    """
    try:
        features = run_context.session_state.get('car_all', [])
        
        if not features:
            return ToolResult(content="Nenhuma busca foi realizada ainda. Informe uma localização primeiro.")

        if selection < 1 or selection > len(features):
            return ToolResult(content=f"Seleção inválida. Escolha um número válido entre 1 e {len(features)}.")

        selected_feature = features[selection - 1]
        selected_feature['properties']['area'] = round(selected_feature['properties']['area'])
        run_context.session_state['car_selected'] = selected_feature

        del run_context.session_state['car_all']
        del run_context.session_state['is_selecting_car']

        return ToolResult(content="Perfeito! A propriedade foi selecionada. ✅\n\n"
            "Como deseja seguir agora? Posso ajudar com:\n\n"
            "🌱 *Análise de pastagem*\n"
            "🗺️ *Uso e cobertura da terra*\n"
            "📊 *Visualização de biomassa*"
        )
    except Exception as e:
        return ToolResult(content=f"[ERRO] Falha ao selecionar: {str(e)}")


@tool
def confirm_car_selection(run_context: RunContext):
    """
    Confirma a propriedade encontrada quando a busca retorna apenas um resultado único.
    
    Use esta ferramenta quando a ferramenta 'query_car' encontrar apenas 1 imóvel e o usuário confirmar que está correto (ex: dizendo "Sim", "É essa mesmo").
    """
    candidate = run_context.session_state.get('car_candidate')
    
    if not candidate:
        return ToolResult(content="Não há propriedade pendente de confirmação. Realize uma busca primeiro.")

    run_context.session_state['car_selected'] = candidate
    
    del run_context.session_state['car_candidate']
    del run_context.session_state['is_confirming_car']

    return ToolResult(content="Perfeito! A propriedade foi confirmada. ✅\n\n"
        "Como deseja seguir agora? Posso ajudar com:\n\n"
        "🌱 *Análise de pastagem*\n"
        "🗺️ *Uso e cobertura da terra*\n"
        "📊 *Visualização de biomassa*"
        )

@tool
def reject_car_selection(run_context: RunContext):
    """
    Cancela a seleção ou rejeita os resultados encontrados.
    
    Use esta ferramenta se o usuário disser que a propriedade mostrada na imagem NÃO é a correta ou quiser cancelar a seleção.
    """
    keys_to_clear = ['car_all', 'car_candidate', 'is_confirming_car', 'is_selecting_car']

    for k in keys_to_clear:
        if k in run_context.session_state:
            del run_context.session_state[k]

    return ToolResult(
        content=textwrap.dedent("""
        Seleção limpa.

        # INSTRUÇÕES PARA O AGENTE:
        1. Peça desculpas por não ter encontrado a propriedade correta.
        """).strip()
    )