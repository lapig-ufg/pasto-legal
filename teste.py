import requests
import re

def extrair_coordenadas_maps(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, allow_redirects=True, timeout=10)
        response.raise_for_status()

        url_final = response.url

        match_url = re.search(r'(-?\d+\.\d+),(-?\d+\.\d+)', url_final)
        if match_url:
            return float(match_url.group(1)), float(match_url.group(2))

        return None, None

    except requests.RequestException as e:
        print(f"Erro ao acessar a URL: {e}")
        return None, None


if __name__ == "__main__":
    url_teste = "https://maps.app.goo.gl/BkCVdp7x4sYx1yuTA" 
    
    lat, lng = extrair_coordenadas_maps(url_teste)
    
    if lat and lng:
        print(f"Coordenadas encontradas com sucesso!")
        print(f"Latitude:  {lat}")
        print(f"Longitude: {lng}")
    else:
        print("Não foi possível localizar as coordenadas nesta URL.")