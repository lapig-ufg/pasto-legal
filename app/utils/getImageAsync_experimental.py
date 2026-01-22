import asyncio
import aiohttp
import ee
import datetime
from io import BytesIO
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

# Configurações iniciais necessárias (assumindo que o ee já está autenticado)
# ee.Initialize() 

async def process_single_property(session, semaphore, row, roi, sentinel, idx):
    """
    Processa uma única propriedade de forma assíncrona.
    Usa um semáforo para limitar conexões simultâneas.
    """
    async with semaphore:
        try:
            # 1. Preparação dos dados (Operações leves de metadados do GEE)
            # Nota: Definições de objetos do EE são rápidas, o pesado é pedir o URL/Info
            empty = ee.Image().byte()
            feat = roi.filter(ee.Filter.eq('codigo', row))
            
            # Precisamos extrair a geometria para o buffer.
            # getThumbURL é uma chamada síncrona e bloqueante. 
            # Vamos rodar em uma thread separada para não travar o loop async.
            loop = asyncio.get_event_loop()
            
            def get_url_sync():
                # Toda a lógica de construção da imagem final
                outline = empty.paint(ee.FeatureCollection([ee.Feature(feat.geometry())]), 1, 3)
                outline = outline.updateMask(outline)
                outline_rgb = outline.visualize(**{"palette":['FF0000']})
                
                final_image = sentinel.blend(outline_rgb).clip(feat.geometry().buffer(400).bounds())
                
                # O gargalo está aqui: pedir o URL ao Google
                return final_image.getThumbURL({"dimensions": 256, "format": "png"})

            # Executa a parte do GEE num ThreadPool
            url = await loop.run_in_executor(None, get_url_sync)

            # 2. Download Assíncrono (Substitui o requests)
            async with session.get(url, timeout=60) as response:
                response.raise_for_status()
                content = await response.read()
                
                # Processamento de imagem (CPU bound, mas rápido para thumbnails)
                img_pil = Image.open(BytesIO(content))
                buffer = BytesIO()
                img_pil.save(buffer, format="PNG")
                
                # Retorna a estrutura pronta para o dicionário
                return str(idx + 1), {
                    'cod': row,
                    'img': img_pil,
                    'propriedade': ee.FeatureCollection(feat) # Nota: feat é um objeto EE, não resolvido localmente
                }

        except Exception as e:
            print(f"Erro ao processar propriedade {row}: {e}")
            return None

async def getImageAsync(data: str) -> dict:
    year = (datetime.date.today().year) - 1
    roi = gee.geojson_to_ee(data) # Assumindo que 'gee' é seu módulo customizado
    
    # getInfo() é bloqueante, mas necessário uma vez para saber o tamanho da lista
    rows = roi.aggregate_array('codigo').getInfo()
    print('Quantidade de propriedades:', len(rows))
    
    sDate = ee.Date.fromYMD(year, 10, 1)
    eDate = sDate.advance(2, 'month')
    sateliteID = 'COPERNICUS/S2_SR_HARMONIZED'

    sentinel = (ee.ImageCollection(sateliteID)
          .filterBounds(roi.geometry())
          .filterDate(sDate, eDate)
          .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 10))
          .median()
    )
    
    vis_params = {"bands": ["B4","B3","B2"], "min": 0, "max": 3000}
    sentinel = sentinel.visualize(**vis_params)
    
    # Semáforo para não sobrecarregar a API do GEE ou sua rede
    # Limita a 10 requisições simultâneas (ajuste conforme necessário)
    semaphore = asyncio.Semaphore(10)

    async with aiohttp.ClientSession() as session:
        tasks = []
        for idx, row in enumerate(rows):
            task = process_single_property(session, semaphore, row, roi, sentinel, idx)
            tasks.append(task)
        
        # Aguarda todas as tarefas finalizarem
        results = await asyncio.gather(*tasks)

    # Monta o dicionário final filtrando erros (None)
    dic = {k: v for r in results if r for k, v in [r]}
    
    return dic

# --- Como executar ---
# Se estiver no Jupyter Notebook:
# await getImageAsync(data)

# Se estiver em um script .py normal:
# if __name__ == "__main__":
#     resultado = asyncio.run(getImageAsync(data))