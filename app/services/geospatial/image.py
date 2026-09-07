import PIL

from PIL import Image, ImageDraw, ImageFont, ImageColor
from typing import Dict, List, Union


def draw_corner_label(
    image: Image.Image,
    text: str,
    position: str = "top_left",
    font_path: str = "assets/fonts/DejaVuSans-Bold.ttf"
) -> Image.Image:
    """
    Draws a timestamp-style label (white text with black stroke) on a corner of
    the image, keeping it readable over satellite imagery.

    Args:
        image (PIL.Image.Image): Image to draw on (modified copy is returned).
        text (str): Label text (e.g. "08/2025").
        position (str): Corner to place the label ("top_left").
        font_path (str): Path to a TrueType font for the label.

    Returns:
        PIL.Image.Image: New image with the label drawn.

    Raises:
        ValueError: If the position is not supported.
    """
    if position != "top_left":
        raise ValueError(f"Posição de rótulo não suportada: {position}")

    width, height = image.size
    font_size = max(14, int(height * 0.05))

    try:
        font = ImageFont.truetype(font_path, font_size)
    except IOError:
        font = ImageFont.load_default()

    margin = max(5, int(width * 0.02))

    labeled = image.copy()
    draw = ImageDraw.Draw(labeled)

    draw.text(
        (margin, margin),
        text,
        font=font,
        fill=(255, 255, 255),
        stroke_width=2,
        stroke_fill=(0, 0, 0)
    )

    return labeled


def append_continuous_colorbar(
    image: Image.Image, 
    title: str, 
    vmin: Union[int, float], 
    vmax: Union[int, float], 
    palette: List[str],
    font_path: str = "assets/fonts/DejaVuSans-Bold.ttf"
) -> Image.Image:
    """
    Appends a continuous color gradient bar to the right side of an image.
    Handles multi-line titles dynamically without overlapping text.
    """
    width, height = image.size
    
    # 1. Dynamic sizing based on image dimensions
    legend_width = max(150, int(width * 0.25)) 
    margin = max(10, int(width * 0.02))
    
    base_font_size = max(12, int(height * 0.025))
    title_font_size = int(base_font_size * 1.2)
    
    cb_width = max(15, int(legend_width * 0.15))
    cb_height = int(height * 0.55) # Slightly reduced to guarantee room for multi-line text
    
    try:
        font = ImageFont.truetype(font_path, base_font_size)
        title_font = ImageFont.truetype(font_path, title_font_size)
    except IOError:
        font = ImageFont.load_default()
        title_font = ImageFont.load_default()
        
    # 2. Create new expanded image canvas
    new_width = width + legend_width
    new_image = Image.new("RGB", (new_width, height), "white")
    new_image.paste(image, (0, 0))
    
    draw = ImageDraw.Draw(new_image)
    
    # 3. Position elements on the right
    x_offset = width + margin
    y_offset = margin
    
    # Draw Title
    draw.text((x_offset, y_offset), title, fill="black", font=title_font)
    
    # FIX: Calculate exact height of the title block (handles single or multi-line)
    title_bbox = draw.textbbox((x_offset, y_offset), title, font=title_font)
    title_height = title_bbox[3] - title_bbox[1]
    
    # Push the colorbar down past the calculated title height + a safe margin
    y_offset += title_height + margin
    
    # Draw continuous gradient colorbar
    for y in range(cb_height):
        ratio = 1 - (y / (cb_height - 1)) if cb_height > 1 else 0
        n = len(palette) - 1
        idx = max(0, min(int(ratio * n), n - 1))
        local_ratio = (ratio * n) - idx
        
        c1 = ImageColor.getrgb(palette[idx])
        c2 = ImageColor.getrgb(palette[idx+1])
        
        rgb = tuple(int(c1[i] + (c2[i] - c1[i]) * local_ratio) for i in range(3))
        
        draw.line(
            [x_offset, y_offset + y, x_offset + cb_width, y_offset + y], 
            fill=rgb
        )
        
    # Draw a clean border around the gradient bar
    draw.rectangle(
        [x_offset, y_offset, x_offset + cb_width, y_offset + cb_height],
        outline="black",
        width=1
    )

    # 4. Draw labels (vmax at the top, vmin at the bottom)
    text_x_offset = x_offset + cb_width + int(margin * 0.8)
    
    # Get exact height of the value font to align vmin perfectly to the bottom line
    vmin_bbox = draw.textbbox((text_x_offset, y_offset), str(vmin), font=font)
    font_height = vmin_bbox[3] - vmin_bbox[1]
    
    # vmax aligned with the top of the colorbar
    draw.text((text_x_offset, y_offset), str(vmax), fill="black", font=font)
    
    # vmin aligned precisely with the bottom edge of the colorbar
    draw.text((text_x_offset, y_offset + cb_height - font_height), str(vmin), fill="black", font=font)
    
    return new_image


def append_discrete_legend(
    image: Image.Image, 
    title: str, 
    class_colors: Dict[str, str], 
    font_path: str = "assets/fonts/DejaVuSans-Bold.ttf"
) -> Image.Image:
    """
    Appends a discrete legend to the right side of an image.
    Updated with the same multi-line title fix for consistency.
    """
    width, height = image.size
    
    legend_width = max(150, int(width * 0.25))
    margin = max(10, int(width * 0.02))
    
    base_font_size = max(12, int(height * 0.025))
    title_font_size = int(base_font_size * 1.2)
    patch_size = int(base_font_size * 1.2)
    item_height = int(base_font_size * 1.8)
    
    try:
        font = ImageFont.truetype(font_path, base_font_size)
        title_font = ImageFont.truetype(font_path, title_font_size)
    except IOError:
        font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    new_width = width + legend_width
    new_image = Image.new("RGB", (new_width, height), "white")
    new_image.paste(image, (0, 0))
    
    draw = ImageDraw.Draw(new_image)
    
    x_offset = width + margin
    y_offset = margin
    
    # Draw Title
    draw.text((x_offset, y_offset), title, fill="black", font=title_font)
    
    # FIX: Calculate exact height of the title block dynamically
    title_bbox = draw.textbbox((x_offset, y_offset), title, font=title_font)
    title_height = title_bbox[3] - title_bbox[1]
    y_offset += title_height + margin 
    
    # Draw legend items
    for label, color in class_colors.items():
        draw.rectangle(
            [x_offset, y_offset, x_offset + patch_size, y_offset + patch_size],
            fill=color, 
            outline="black",
            width=1
        )
        
        text_x = x_offset + patch_size + int(margin * 0.8)
        draw.text((text_x, y_offset), label, fill="black", font=font)
        
        y_offset += item_height
        
    return new_image


def create_vertical_mosaic(
    images: List[Image.Image], 
    font_path: str = "assets/fonts/DejaVuSans-Bold.ttf"
) -> Image.Image:
    """
    Combines a list of PIL Images into a single vertical mosaic.
    
    Dynamically calculates canvas dimensions to prevent clipping and adjusts 
    font sizes and margins based on the input image sizes.
    
    Args:
        images (List[PIL.Image.Image]): A list of images to be stacked vertically.
        font_path (str): Path to a TrueType font for the labels.
        
    Returns:
        PIL.Image.Image: A single vertically stacked mosaic image.
        
    Raises:
        ValueError: If the input list is empty.
    """
    if not images:
        raise ValueError("The image list cannot be empty.")

    max_width = max(img.width for img in images)
    margin = max(10, int(max_width * 0.015))
    
    total_height = sum(img.height for img in images) + (margin * (len(images) + 1))
    total_width = max_width + (margin * 2)

    mosaic = Image.new("RGB", (total_width, total_height), "white")
    draw = ImageDraw.Draw(mosaic)
    
    current_y = margin
    
    for index, img in enumerate(images, 1):
        current_x = margin + ((max_width - img.width) // 2)
        
        mosaic.paste(img, (current_x, current_y))
        
        font_size = max(14, int(img.height * 0.04))
        try:
            font = ImageFont.truetype(font_path, font_size)
        except IOError:
            font = ImageFont.load_default()
            
        label_text = f'Area: {index}'
        text_x = current_x + max(5, int(margin * 0.5))
        text_y = current_y + max(5, int(margin * 0.5))
        
        draw.text(
            (text_x, text_y), 
            label_text, 
            font=font, 
            fill=(255, 255, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0)
        )
        
        current_y += img.height + margin

    return mosaic