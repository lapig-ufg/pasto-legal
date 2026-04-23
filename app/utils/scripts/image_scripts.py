import PIL

from PIL import Image, ImageFont, ImageColor, ImageDraw


def add_legend_descriptor(image_pil: Image, title: str, classes: dict):
    """
    Cria uma nova imagem com a legenda posicionada externamente à direita.
    """
    width, height = image_pil.size
    
    # 1. Configurações de estilo e dimensões da legenda
    legend_width = 100  # Largura da área da legenda
    margin = 5
    item_height = 20
    
    try:
        font = ImageFont.truetype("assets/fonts/DejaVuSans-Bold.ttf", 8)
        title_font = ImageFont.truetype("assets/fonts/DejaVuSans-Bold.ttf", 10)
    except:
        font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    # 2. Criar uma nova imagem com largura extra para a legenda
    # Nova largura = largura original + largura da legenda
    new_width = width + legend_width
    new_image = Image.new("RGB", (new_width, height), "white")
    
    # 3. Colar a imagem original na nova imagem (no lado esquerdo)
    new_image.paste(image_pil, (0, 0))
    
    draw = ImageDraw.Draw(new_image)
    
    # 4. Desenhar a legenda na área em branco (à direita)
    x_offset = width + margin
    y_offset = margin
    
    # Desenhar Título
    draw.text((x_offset, y_offset), title, fill="black", font=title_font)
    y_offset += 20 # Espaço após o título
    
    # Desenhar itens da legenda
    for label, color in classes.items():
        # Quadrado de cor
        patch_size = 10
        draw.rectangle(
            [x_offset, y_offset, x_offset + patch_size, y_offset + patch_size],
            fill=color, 
            outline="black"
        )
        
        # Texto da classe
        draw.text((x_offset + patch_size + 4, y_offset), label, fill="black", font=font)
        
        y_offset += item_height
        
    return new_image


def get_mosaic(imgs: list[PIL.Image]) -> Image:
    first = imgs[0]

    width, height = first.size
    
    widthMosaic = width + 5
    heightMosaic = (height * len(imgs)) + 10

    font = ImageFont.truetype("assets/fonts/DejaVuSans-Bold.ttf", 16)

    mosaic = Image.new("RGB", (widthMosaic, heightMosaic), "white")
    
    for index, img in enumerate(imgs, 1):
        count = (index - 1) * (height + 2)

        location = (2, count + 2)
        localtiontext = (5, count + 5)

        mosaic.paste(img, location)

        label = ImageDraw.Draw(mosaic)
        label.text(localtiontext, f'Area: {index}', font=font, fill=(255, 255, 255))

    return mosaic

#Adicionar a legenda no mapa
def add_legend(img: Image, title: str, vmin: int, vmax: int, palette: list) -> Image:
    """Desenha uma barra de cores contínua na imagem PIL com respiro após o título."""
    draw = ImageDraw.Draw(img)
    width, height = img.size
    
    cb_width, cb_height = 12, 25
    
    # 1. Aumentamos um pouco a altura do fundo (de 35 para 45) para acomodar o espaço extra
    bg_box = [width - 70, height - cb_height - 45, width - 5, height - 5]
    draw.rectangle(bg_box, fill="white", outline="gray")
    
    #Fonte de dados utilizadas
    font = ImageFont.truetype("assets/fonts/DejaVuSans-Bold.ttf", 8)
    
    # Título 
    draw.text((bg_box[0] + 5, bg_box[1] + 2), title, fill="black", font=font)

    # Definição do espaço entre o título e o gradiente de cores
    gradient_top_offset = 30 

    # Criar o gradiente
    for y in range(cb_height):
        ratio = 1 - (y / (cb_height - 1))
        n = len(palette) - 1
        idx = max(0, min(int(ratio * n), n - 1))
        local_ratio = (ratio * n) - idx
        
        c1 = ImageColor.getrgb(palette[idx])
        c2 = ImageColor.getrgb(palette[idx+1])
        
        rgb = tuple(int(c1[i] + (c2[i] - c1[i]) * local_ratio) for i in range(3))
        
        # Aplicando o novo offset no desenho da linha
        draw.line([width - 60, bg_box[1] + gradient_top_offset + y, 
                   width - 60 + cb_width, bg_box[1] + gradient_top_offset + y], fill=rgb)

    # Ajuste dos rótulos para acompanharem o novo posicionamento da barra
    # Vmax alinhado ao topo da barra (gradient_top_offset)
    draw.text((width - 40, bg_box[1] + gradient_top_offset), str(vmax), fill="black", font=font)
    
    # Vmin alinhado à base da barra (offset + altura da barra - ajuste de texto)
    draw.text((width - 40, bg_box[1] + gradient_top_offset + cb_height - 8), str(vmin), fill="black", font=font)
    
    return img