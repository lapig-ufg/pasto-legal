from PIL import Image, ImageDraw, ImageFont

# TODO: Documentação da função.
# TODO: Definir tipo de retorno da função.
def get_mosaic(imgs: list):
    first = imgs[0]

    width, height = first.size
    
    widthMosaic = width + 5
    heightMosaic = (height * len(imgs)) + 10

    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",18)

    mosaic = Image.new("RGB", (widthMosaic, heightMosaic), "white")
    
    for index, img in enumerate(imgs, 1):
        count = (index - 1) * (height + 2)

        location = (2, count + 2)
        localtiontext = (5, count + 5)

        mosaic.paste(img, location)

        label = ImageDraw.Draw(mosaic)
        label.text(localtiontext, f'Area: {index}', font=font, fill=(255, 255, 255))

    return mosaic