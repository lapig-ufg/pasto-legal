import PIL

from PIL import Image, ImageDraw, ImageFont, ImageColor
from typing import Dict, List, Tuple, Union


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


def format_tick(value: Union[int, float], ndigits: int = 2) -> str:
    """Formats a colorbar tick with a fixed number of decimal places."""
    return f"{float(value):.{ndigits}f}"


def _colorbar_layout(
    font_path: str,
    base_font_size: int,
    labels: Tuple[str, str, str],
    available: int,
    min_width: int,
) -> Tuple["ImageFont.ImageFont", int, bool, int]:
    """Picks the tick font, whether the mid tick fits, and the bar width.

    Labels are anchored at the bar ends (min left, max right), so the bar must
    be at least as wide as ``min + gap + max``. The mid tick is only drawn when
    it also fits, otherwise the labels would overlap on narrow images.

    Returns:
        (font, font_size, show_mid, cb_width)
    """
    vmin_label, mid_label, vmax_label = labels
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def measure(font, size) -> Tuple[float, float, float, int]:
        gap = max(6, int(size * 0.6))
        return (
            probe.textlength(vmin_label, font=font),
            probe.textlength(mid_label, font=font),
            probe.textlength(vmax_label, font=font),
            gap,
        )

    candidates = []
    for scale in (1.0, 0.85, 0.7):
        size = max(9, int(base_font_size * scale))
        try:
            candidate = ImageFont.truetype(font_path, size)
        except IOError:
            candidate = ImageFont.load_default()
        candidates.append((size, candidate))

    size, font = candidates[-1]
    show_mid = False
    for candidate_size, candidate_font in candidates:
        wmin, wmid, wmax, gap = measure(candidate_font, candidate_size)
        if wmin + wmax + gap <= available:
            size, font = candidate_size, candidate_font
            show_mid = (wmin + wmid + wmax + 3 * gap) <= available
            break

    wmin, wmid, wmax, gap = measure(font, size)
    needed = wmin + wmid + wmax + 3 * gap if show_mid else wmin + wmax + gap
    cb_width = min(max(min_width, int(needed)), available)
    return font, size, show_mid, max(1, int(cb_width))


def append_continuous_colorbar(
    image: Image.Image, 
    title: str, 
    vmin: Union[int, float], 
    vmax: Union[int, float], 
    unit: str,
    palette: List[str],
    ndigits: int = 2,
    font_path: str = "assets/fonts/DejaVuSans-Bold.ttf"
) -> Image.Image:
    """
    Appends a continuous color gradient bar below the image, with the title
    centered above it. The bar is horizontal with min, mid and max ticks
    (the unit is shown only on the max label; the mid tick is omitted when the
    image is too narrow for the three labels).

    Args:
        ndigits (int, optional): Decimal places for the tick labels
            (2 by default).
    """
    width, height = image.size

    margin = max(10, int(width * 0.02))
    available = max(1, width - 2 * margin)
    base_font_size = max(12, int(height * 0.025))

    # 1. Dynamic sizing based on image dimensions and label widths, so the ticks
    #    never overlap (labels carry decimals and the unit).
    mid = vmin + (vmax - vmin) / 2
    vmin_label = format_tick(vmin, ndigits)
    mid_label = format_tick(mid, ndigits)
    vmax_label = format_tick(vmax, ndigits)
    font, font_size, show_mid, cb_width = _colorbar_layout(
        font_path=font_path,
        base_font_size=base_font_size,
        labels=(vmin_label, mid_label, f"{vmax_label} {unit}"),
        available=available,
        min_width=max(150, int(width * 0.6)),
    )

    cb_height = font_size
    title_font_size = int(font_size * 1.2)
    try:
        title_font = ImageFont.truetype(font_path, title_font_size)
    except IOError:
        title_font = ImageFont.load_default()

    # 2. Create new expanded canvas: title band on top, legend band below
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_bbox = probe.multiline_textbbox((0, 0), title, font=title_font)
    title_height = title_bbox[3] - title_bbox[1]
    font_height = font_size
    
    top_band = title_height + (margin * 2)
    bottom_band = cb_height + font_height + (margin * 3)
    new_width = width
    new_height = height + top_band + bottom_band
    
    new_image = Image.new("RGB", (new_width, new_height), "white")
    new_image.paste(image, (0, top_band))
    
    draw = ImageDraw.Draw(new_image)
    
    # 3. Title centered above the image
    draw.multiline_text(
        (new_width // 2, top_band // 2),
        title,
        fill="black",
        font=title_font,
        anchor="mm",
        align="center"
    )
    
    # 4. Horizontal gradient colorbar centered below the image
    x_offset = (new_width - cb_width) // 2
    y_offset = new_height - bottom_band + margin
    
    for x in range(cb_width):
        ratio = x / (cb_width - 1) if cb_width > 1 else 0
        n = len(palette) - 1
        idx = max(0, min(int(ratio * n), n - 1))
        local_ratio = (ratio * n) - idx
        
        c1 = ImageColor.getrgb(palette[idx])
        c2 = ImageColor.getrgb(palette[idx+1])
        
        rgb = tuple(int(c1[i] + (c2[i] - c1[i]) * local_ratio) for i in range(3))
        
        draw.line(
            [x_offset + x, y_offset, x_offset + x, y_offset + cb_height], 
            fill=rgb
        )
        
    # Draw a clean border around the gradient bar
    draw.rectangle(
        [x_offset, y_offset, x_offset + cb_width, y_offset + cb_height],
        outline="black",
        width=1
    )

    # 5. Draw labels (vmin left, mid centered when it fits, vmax + unit right)
    text_y = y_offset + cb_height + margin // 2

    draw.text(
        (x_offset, text_y),
        vmin_label,
        fill="black",
        font=font,
        anchor="la"
    )

    if show_mid:
        draw.text(
            (x_offset + cb_width // 2, text_y),
            mid_label,
            fill="black",
            font=font,
            anchor="ma"
        )

    draw.text(
        (x_offset + cb_width, text_y),
        f"{vmax_label} {unit}",
        fill="black",
        font=font,
        anchor="ra"
    )

    return new_image


def append_discrete_legend(
    image: Image.Image, 
    title: str, 
    class_colors: Dict[str, str], 
    font_path: str = "assets/fonts/DejaVuSans-Bold.ttf"
) -> Image.Image:
    """
    Appends a discrete legend below the image, with the title centered above
    it. Legend items (color patch + label) are laid out horizontally.
    """
    width, height = image.size
    
    margin = max(10, int(width * 0.02))
    
    base_font_size = max(12, int(height * 0.025))
    title_font_size = int(base_font_size * 1.2)
    patch_size = int(base_font_size * 1.2)
    item_height = int(base_font_size * 1.8)
    item_gap = int(margin * 1.5)
    
    try:
        font = ImageFont.truetype(font_path, base_font_size)
        title_font = ImageFont.truetype(font_path, title_font_size)
    except IOError:
        font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    # 1. Measure title height for the top band
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_bbox = probe.multiline_textbbox((0, 0), title, font=title_font)
    title_height = title_bbox[3] - title_bbox[1]
    
    top_band = title_height + (margin * 2)
    new_width = width
    
    # 2. Legend items laid out horizontally below the image, wrapped in
    # centered rows when they do not fit on a single line
    margin_half = margin // 2
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    items = [(label, color, probe.textlength(label, font=font)) for label, color in class_colors.items()]
    item_widths = [patch_size + margin_half + int(text_width) for _, _, text_width in items]
    
    rows, current_row, current_width = [], [], 0
    for item, item_width in zip(items, item_widths):
        width_with_item = current_width + item_width + (item_gap if current_row else 0)
        if current_row and width_with_item > new_width - (margin * 2):
            rows.append(current_row)
            current_row, current_width = [], 0
        current_row.append(item)
        current_width = current_width + item_width + (item_gap if len(current_row) > 1 else 0)
    if current_row:
        rows.append(current_row)
    
    # 3. Create expanded canvas sized to fit title band + all legend rows
    row_height = item_height + margin // 2
    bottom_band = (row_height * len(rows)) + margin
    new_height = height + top_band + bottom_band
    
    new_image = Image.new("RGB", (new_width, new_height), "white")
    new_image.paste(image, (0, top_band))
    
    draw = ImageDraw.Draw(new_image)
    
    # 4. Title centered above the image
    draw.multiline_text(
        (new_width // 2, top_band // 2),
        title,
        fill="black",
        font=title_font,
        anchor="mm",
        align="center"
    )
    
    # 5. Draw each legend row centered horizontally
    y_offset = new_height - bottom_band + margin // 2
    for row in rows:
        row_width = sum(patch_size + margin_half + int(text_width) for _, _, text_width in row)
        row_width += item_gap * (len(row) - 1)
        x_offset = max(margin, (new_width - row_width) // 2)
        
        for label, color, text_width in row:
            draw.rectangle(
                [x_offset, y_offset, x_offset + patch_size, y_offset + patch_size],
                fill=color, 
                outline="black",
                width=1
            )
            
            text_x = x_offset + patch_size + margin_half
            draw.text(
                (text_x, y_offset + patch_size // 2),
                label,
                fill="black",
                font=font,
                anchor="lm"
            )
            
            x_offset += patch_size + margin_half + int(text_width) + item_gap
        
        y_offset += row_height
        
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