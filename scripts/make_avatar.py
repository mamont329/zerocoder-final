"""Рисует аватарку бота FinControl в scripts/avatar.png и avatar.jpg.

Одноразовый вспомогательный скрипт, в зависимостях проекта не нужен:
    pip install pillow
    python scripts/make_avatar.py

Мотив — кольцевая диаграмма расходов, главный график сервиса, и знак рубля
в центре. Цвета те же, что на графиках: синий фон и оранжевый сегмент.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 512
SCALE = 4  # рисуем крупнее и уменьшаем — так края получаются гладкими
CANVAS = SIZE * SCALE

BLUE_TOP = (58, 135, 229)      # #3a87e5
BLUE_BOTTOM = (24, 79, 149)    # #184f95
ORANGE = (235, 104, 52)        # #eb6834
WHITE = (252, 252, 251)

RING_OUTER = 0.78   # доля от половины стороны
RING_INNER = 0.52
# Оранжевый сегмент примерно на треть кольца — как доля крупной категории
SEGMENT_START, SEGMENT_END = -90, 30

FONT_CANDIDATES = [
    r'C:\Windows\Fonts\segoeuib.ttf',
    r'C:\Windows\Fonts\arialbd.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
]


def load_font(size):
    """Первый доступный жирный шрифт со знаком рубля."""
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def draw_avatar():
    image = Image.new('RGB', (CANVAS, CANVAS))
    draw = ImageDraw.Draw(image)

    # Фон: вертикальный градиент от светлого синего к тёмному
    for y in range(CANVAS):
        t = y / CANVAS
        color = tuple(round(a + (b - a) * t) for a, b in zip(BLUE_TOP, BLUE_BOTTOM))
        draw.line([(0, y), (CANVAS, y)], fill=color)

    center = CANVAS / 2
    outer = center * RING_OUTER
    inner = center * RING_INNER
    box_outer = [center - outer, center - outer, center + outer, center + outer]
    box_inner = [center - inner, center - inner, center + inner, center + inner]

    # Кольцо рисуем на прозрачном слое и вырезаем середину: если залить вырез
    # плоским цветом, он разойдётся с градиентом фона в нижней части
    ring = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(ring)
    ring_draw.ellipse(box_outer, fill=WHITE + (255,))
    ring_draw.pieslice(box_outer, SEGMENT_START, SEGMENT_END, fill=ORANGE + (255,))
    ring_draw.ellipse(box_inner, fill=(0, 0, 0, 0))
    image.paste(ring, (0, 0), ring)

    # Знак рубля в отверстии кольца
    font = load_font(int(CANVAS * 0.30))
    text = '₽'
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(
        (center - (right + left) / 2, center - (bottom + top) / 2),
        text, font=font, fill=WHITE,
    )

    return image.resize((SIZE, SIZE), Image.LANCZOS)


if __name__ == '__main__':
    avatar = draw_avatar()

    png = Path(__file__).with_name('avatar.png')
    avatar.save(png)

    # Telegram принимает статичную аватарку бота только в JPG
    jpg = Path(__file__).with_name('avatar.jpg')
    avatar.save(jpg, quality=95)

    print(f'Аватарка сохранена: {png} и {jpg}')
