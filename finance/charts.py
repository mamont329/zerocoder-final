"""Построение графиков plotly и их встраивание в шаблоны.

Фигуры отдаются кусками HTML: библиотека plotly.js подключается один раз
в шаблоне страницы, поэтому здесь include_plotlyjs=False.
"""
import plotly.graph_objects as go

# Палитра проверена на различимость при дальтонизме (см. этап 3 в README).
# Доход — синий, расход — оранжевый: красно-зелёная пара, привычная в финансах,
# для дальтоников наименее различима, поэтому цветом её не кодируем.
INCOME_COLOR = '#2a78d6'
EXPENSE_COLOR = '#eb6834'

# Слоты для категорий и приглушённый серый для хвоста «Прочее»
CATEGORY_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4']
OTHER_COLOR = '#8a9099'

# Больше сегментов на кольцевой диаграмме читаются хуже, чем «Прочее» + таблица
MAX_SLICES = 5

TEXT_PRIMARY = '#0b0b0b'
TEXT_SECONDARY = '#52514e'
GRID_COLOR = '#e6e7e9'
SURFACE = '#ffffff'

LAYOUT = {
    'paper_bgcolor': SURFACE,
    'plot_bgcolor': SURFACE,
    'font': {'family': 'system-ui, -apple-system, Segoe UI, sans-serif', 'size': 13, 'color': TEXT_SECONDARY},
    'margin': {'l': 60, 'r': 20, 't': 30, 'b': 40},
    'hovermode': 'x unified',
    'separators': ', ',
}

CONFIG = {'displayModeBar': False, 'locale': 'ru', 'responsive': True}


def _to_html(figure):
    return figure.to_html(full_html=False, include_plotlyjs=False, config=CONFIG)


def timeline_chart(frame, by_month=False):
    """Динамика доходов и расходов по времени."""
    if frame.empty:
        return None

    axis_format = '%m.%Y' if by_month else '%d.%m'
    figure = go.Figure()
    for column, name, color in (
        ('income', 'Доходы', INCOME_COLOR),
        ('expense', 'Расходы', EXPENSE_COLOR),
    ):
        figure.add_trace(go.Scatter(
            x=frame.index,
            y=frame[column],
            name=name,
            mode='lines+markers',
            line={'color': color, 'width': 2},
            marker={'size': 8, 'color': color},
            hovertemplate='%{y:,.2f} ₽<extra>' + name + '</extra>',
        ))

    figure.update_layout(
        **LAYOUT,
        legend={'orientation': 'h', 'yanchor': 'bottom', 'y': 1.02, 'x': 0, 'title': None},
        xaxis={'showgrid': False, 'linecolor': GRID_COLOR, 'tickformat': axis_format},
        yaxis={'gridcolor': GRID_COLOR, 'zeroline': False, 'ticksuffix': ' ₽', 'tickformat': ',.0f'},
    )
    return _to_html(figure)


def cumulative_chart(frame, by_month=False):
    """Доходы и расходы нарастающим итогом за период.

    Отдельный график, а не вторая ось на предыдущем: накопленные суммы на
    порядок больше дневных, и общая шкала сплющила бы дневную динамику.
    """
    if frame.empty:
        return None

    cumulative = frame.cumsum()
    axis_format = '%m.%Y' if by_month else '%d.%m'

    figure = go.Figure()
    for column, name, color in (
        ('income', 'Доходы нарастающим итогом', INCOME_COLOR),
        ('expense', 'Расходы нарастающим итогом', EXPENSE_COLOR),
    ):
        series = cumulative[column]
        figure.add_trace(go.Scatter(
            x=cumulative.index,
            y=series,
            name=name,
            mode='lines',
            line={'color': color, 'width': 2, 'shape': 'hv'},
            hovertemplate='%{y:,.2f} ₽<extra>' + name + '</extra>',
        ))
        # Подпись итога прямо у линии — чтобы значение читалось без наведения
        figure.add_trace(go.Scatter(
            x=[cumulative.index[-1]],
            y=[series.iloc[-1]],
            mode='markers+text',
            marker={'size': 8, 'color': color},
            text=[f'{series.iloc[-1]:,.0f} ₽'.replace(',', ' ')],
            textposition='top left',
            textfont={'color': TEXT_PRIMARY},
            showlegend=False,
            hoverinfo='skip',
        ))

    figure.update_layout(
        **LAYOUT,
        legend={'orientation': 'h', 'yanchor': 'bottom', 'y': 1.02, 'x': 0, 'title': None},
        xaxis={'showgrid': False, 'linecolor': GRID_COLOR, 'tickformat': axis_format},
        yaxis={'gridcolor': GRID_COLOR, 'zeroline': False, 'ticksuffix': ' ₽', 'tickformat': ',.0f'},
    )
    return _to_html(figure)


def category_chart(categories):
    """Кольцевая диаграмма расходов по категориям.

    Хвост мелких категорий сворачивается в «Прочее»: больше пяти сегментов
    перестают различаться, а полный список всё равно есть в таблице рядом.
    """
    if not categories:
        return None

    head = categories[:MAX_SLICES]
    tail = categories[MAX_SLICES:]

    labels = [item['name'] for item in head]
    values = [float(item['total']) for item in head]
    colors = CATEGORY_COLORS[:len(head)]

    if tail:
        labels.append('Прочее')
        values.append(float(sum(item['total'] for item in tail)))
        colors.append(OTHER_COLOR)

    figure = go.Figure(go.Pie(
        labels=labels,
        values=values,
        hole=0.55,
        sort=False,
        direction='clockwise',
        marker={'colors': colors, 'line': {'color': SURFACE, 'width': 2}},
        # Подписи внутри сегментов: снаружи они съедают ширину узкой колонки,
        # и от самого кольца ничего не остаётся. Названия дублирует легенда.
        textinfo='percent',
        # Целые проценты: доли до сотых plotly пишет вразнобой («6,77%», «43,9%»),
        # а точные суммы всё равно есть в таблице рядом
        texttemplate='%{percent:.0%}',
        textposition='inside',
        insidetextorientation='horizontal',
        hovertemplate='%{label}: %{value:,.2f} ₽ (%{percent})<extra></extra>',
    ))
    figure.update_layout(
        # Нижнее поле оставлено под легенду, иначе она наезжает на кольцо
        **{**LAYOUT, 'hovermode': 'closest', 'margin': {'l': 10, 'r': 10, 't': 10, 'b': 60}},
        height=380,
        showlegend=True,
        legend={'orientation': 'h', 'yanchor': 'top', 'y': -0.02, 'x': 0.5, 'xanchor': 'center', 'title': None},
        # Проценты, которым не хватает места в сегменте, прячутся, а не наползают друг на друга
        uniformtext={'minsize': 11, 'mode': 'hide'},
    )
    return _to_html(figure)
