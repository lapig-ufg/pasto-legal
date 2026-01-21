from PIL import Image, ImageDraw, ImageFont

# TODO: Documentação da função.
# TODO: Definir tipo de retorno da função.
def get_mosaic(imgs: list):
    first = imgs[imgs[0]]

    width, height = first['img'].size
    
    widthMosaic = width + 5
    heightMosaic = (height * len(imgs)) + 10

    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",18)

    mosaic = Image.new("RGB", (widthMosaic, heightMosaic), "white")

    count = 0
    space = 2
    
    #Iterar em cada propriedade encontrada
    for index, img in enumerate(imgs, 1):
        #Localização do rótulos e da imagem no mosaico (w x h)
        location = (space, count+space)
        localtiontext = (space + 3, count + space + 3)

        #Inserindo a imagem no mosaico
        mosaic.paste(img, location)

        #Inserindo o rótulo na imagem
        label = ImageDraw.Draw(mosaic)
        label.text(localtiontext, 'Area:'+ index, font = font, fill=(255, 255, 255))

        #Contagem
        count = count + height + space

    return mosaic