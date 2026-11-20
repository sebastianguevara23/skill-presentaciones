"""Gráficos nativos de PowerPoint: sus datos y su marca.

Desde el 2026-10-01 son los únicos gráficos que se trabajan (`plans/decisiones.md`). Siguen
nativos y editables: aquí solo se lee lo que la integridad exige intacto (tipo, título,
categorías, series y valores) y se cambia el estilo del XML del gráfico. Nada se rasteriza.
"""
from __future__ import annotations

from copy import deepcopy

from lxml import etree
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Pt

from .knowledge import Knowledge
from .schemas import ChartData, ChartSeries

_PER_POINT = {"pieChart", "pie3DChart", "doughnutChart", "ofPieChart"}
_LINES = {"lineChart", "line3DChart", "scatterChart", "radarChart", "stockChart"}
# Orden de CT_TextCharacterProperties: el relleno va tras `a:ln` y la fuente antes de esto.
_FILLS = ("a:noFill", "a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill", "a:grpFill")
_AFTER_LATIN = ("a:ea", "a:cs", "a:sym", "a:hlinkClick", "a:hlinkMouseOver", "a:rtl", "a:extLst")


def chart_data(chart) -> ChartData:
    """Lo que el gráfico dice. Un gráfico que python-pptx no sabe leer igual queda registrado."""
    try:
        chart_type = chart.chart_type.name
    except (KeyError, NotImplementedError, ValueError, AttributeError):
        chart_type = "unknown"
    title = None
    if chart.has_title and chart.chart_title.has_text_frame:
        title = chart.chart_title.text_frame.text.strip() or None
    categories: list[str] = []
    series: list[ChartSeries] = []
    for plot in chart.plots:
        try:
            labels = [str(label) for label in plot.categories]
        except (AttributeError, ValueError):
            labels = []
        if labels and not categories:
            categories = labels
        for item in plot.series:
            try:
                values = [None if value is None else float(value) for value in item.values]
            except (AttributeError, ValueError, TypeError):
                values = []
            series.append(ChartSeries(name=item.name or "", values=values))
    return ChartData(chart_type=chart_type, title=title, categories=categories, series=series)


def _chart_space(shape):
    return shape.chart._chartSpace


def scale_text(shape, factor: float) -> int:
    """La normalización a 1920×1080 agranda el marco; el texto del gráfico vive en otra parte
    del paquete y no se escala solo. Sin esto queda a la mitad de su tamaño visual."""
    space = _chart_space(shape)
    changed = 0
    for props in space.iter(qn("a:defRPr"), qn("a:rPr"), qn("a:endParaRPr")):
        if props.get("sz"):
            props.set("sz", str(round(int(props.get("sz")) * factor)))
            changed += 1
    font = shape.chart.font
    if font.size is None:  # el gráfico hereda 10 pt de PowerPoint
        font.size = Pt(10 * factor)
        changed += 1
    return changed


def _style_text(props, color: str, min_sz: int) -> None:
    if props.get("sz") and int(props.get("sz")) < min_sz:
        props.set("sz", str(min_sz))
    for tag in (*_FILLS, "a:latin"):
        for old in props.findall(qn(tag)):
            props.remove(old)
    fill = props.makeelement(qn("a:solidFill"), {})
    etree.SubElement(fill, qn("a:srgbClr"), val=color)
    line = props.find(qn("a:ln"))
    props.insert(0 if line is None else list(props).index(line) + 1, fill)
    latin = props.makeelement(qn("a:latin"), {"typeface": "Montserrat"})
    after = next((child for child in props if child.tag in {qn(tag) for tag in _AFTER_LATIN}), None)
    if after is None:
        props.append(latin)
    else:
        after.addprevious(latin)


def _no_fill_sppr(parent, before: tuple[str, ...]) -> None:
    """Fondo y borde transparentes: el gráfico se apoya en el fondo de marca de la slide."""
    for old in parent.findall(qn("c:spPr")):
        parent.remove(old)
    sp_pr = parent.makeelement(qn("c:spPr"), {})
    etree.SubElement(sp_pr, qn("a:noFill"))
    line = etree.SubElement(sp_pr, qn("a:ln"))
    etree.SubElement(line, qn("a:noFill"))
    anchor = next((child for child in parent if child.tag in {qn(tag) for tag in before}), None)
    if anchor is None:
        parent.append(sp_pr)
    else:
        anchor.addprevious(sp_pr)


# Lo que una etiqueta de datos muestra y cómo; se copia tal cual a la etiqueta de un punto.
_LABEL_FLAGS = ("c:numFmt", "c:spPr", "c:txPr", "c:dLblPos", "c:showLegendKey", "c:showVal",
                "c:showCatName", "c:showSerName", "c:showPercent", "c:showBubbleSize", "c:separator")
_SHOWS = ("c:showVal", "c:showCatName", "c:showSerName", "c:showPercent", "c:showBubbleSize")


def _luma(hex_: str) -> float:
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_labels(series, point_colors: dict[int, str], light: str, dark: str) -> None:
    """Etiqueta dentro de una porción: texto claro sobre relleno oscuro y al revés. Sin esto,
    la etiqueta de la porción navy sale navy sobre navy y desaparece."""
    ser, plot = series._element, series._element.getparent()
    source = ser.find(qn("c:dLbls"))
    source = source if source is not None else plot.find(qn("c:dLbls"))
    if source is None or not any((flag := source.find(qn(tag))) is not None and flag.get("val") in ("1", "true")
                                 for tag in _SHOWS):
        return
    target = ser.find(qn("c:dLbls"))
    if target is None:
        target = deepcopy(source)
        for old in target.findall(qn("c:dLbl")):
            target.remove(old)
        anchor = next((child for child in ser if child.tag in {qn(t) for t in ("c:cat", "c:val", "c:extLst")}), None)
        anchor.addprevious(target) if anchor is not None else ser.append(target)
    existing = {int(d.find(qn("c:idx")).get("val")): d for d in target.findall(qn("c:dLbl"))}
    for index, fill in point_colors.items():
        label = existing.get(index)
        if label is None:
            label = target.makeelement(qn("c:dLbl"), {})
            etree.SubElement(label, qn("c:idx"), val=str(index))
            for tag in _LABEL_FLAGS:
                if (flag := target.find(qn(tag))) is not None:
                    label.append(deepcopy(flag))
            first = next((child for child in target if child.tag != qn("c:dLbl")), None)
            first.addprevious(label) if first is not None else target.append(label)
            existing[index] = label
        if label.find(qn("c:delete")) is not None:
            continue
        tx_pr = label.find(qn("c:txPr"))
        if tx_pr is None:
            tx_pr = label.makeelement(qn("c:txPr"), {})
            etree.SubElement(tx_pr, qn("a:bodyPr"))
            etree.SubElement(tx_pr, qn("a:lstStyle"))
            paragraph = etree.SubElement(tx_pr, qn("a:p"))
            etree.SubElement(etree.SubElement(paragraph, qn("a:pPr")), qn("a:defRPr"))
            etree.SubElement(paragraph, qn("a:endParaRPr"), lang="es-ES")
            anchor = next((child for child in label if child.tag in {qn(t) for t in _LABEL_FLAGS[3:] + ("c:extLst",)}), None)
            anchor.addprevious(tx_pr) if anchor is not None else label.append(tx_pr)
        for props in tx_pr.iter(qn("a:defRPr")):
            for old in props.findall(qn("a:solidFill")):
                props.remove(old)
            fill_el = props.makeelement(qn("a:solidFill"), {})
            etree.SubElement(fill_el, qn("a:srgbClr"), val=light if _luma(fill) < 0.45 else dark)
            line = props.find(qn("a:ln"))
            props.insert(0 if line is None else list(props).index(line) + 1, fill_el)


def _color_series(plot, palette: list[str], line_width, light: str, dark: str) -> None:
    kind = etree.QName(plot._element).localname
    for k, series in enumerate(plot.series):
        color = RGBColor.from_string(palette[k % len(palette)])
        if kind in _PER_POINT:
            fills = {j: palette[j % len(palette)] for j in range(len(series.values))}
            for j, fill in fills.items():
                point = series.points[j].format
                point.fill.solid()
                point.fill.fore_color.rgb = RGBColor.from_string(fill)
            _contrast_labels(series, fills, light, dark)
            continue
        if kind in _LINES:
            series.format.line.color.rgb = color
            series.format.line.width = line_width
            marker = getattr(series, "marker", None)
            if marker is not None:
                marker.format.fill.solid()
                marker.format.fill.fore_color.rgb = color
                marker.format.line.color.rgb = color
            continue
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = color
        # Un punto que el autor destacó con otro color sigue destacado, con la paleta.
        accent = RGBColor.from_string(palette[(k + 1) % len(palette)])
        for d_pt in series._element.findall(qn("c:dPt")):
            index = int(d_pt.find(qn("c:idx")).get("val"))
            series.points[index].format.fill.solid()
            series.points[index].format.fill.fore_color.rgb = accent


def apply_brand(shape, kn: Knowledge, *, dark: bool, scale: float = 1.0) -> int:
    """Aplica la marca al gráfico nativo de `shape` sin tocar sus datos. Devuelve 1 si lo cambió.

    `scale` lleva el mínimo tipográfico (lienzo lógico de 720 pt) al lienzo real de la slide.
    """
    spec = kn.tokens["brand_rules"]["chart"]
    mode = spec["dark" if dark else "light"]
    text = kn.color(mode["text"])
    palette = [kn.color(name) for name in mode["series"]]
    grid = RGBColor.from_string(kn.color(mode["grid"]))
    min_sz = round(kn.min_size * scale * 100)
    chart = shape.chart
    space = _chart_space(shape)

    font = chart.font
    font.name = "Montserrat"
    if font.size is None or font.size.pt < kn.min_size * scale:
        font.size = Pt(kn.min_size * scale)
    for props in space.iter(qn("a:defRPr"), qn("a:rPr"), qn("a:endParaRPr")):
        _style_text(props, text, min_sz)

    rounded = space.find(qn("c:roundedCorners"))
    if rounded is None:
        rounded = space.makeelement(qn("c:roundedCorners"), {})
        anchor = next((child for child in space if child.tag not in (qn("c:date1904"), qn("c:lang"))), None)
        anchor.addprevious(rounded)
    rounded.set("val", "0")
    _no_fill_sppr(space, ("c:txPr", "c:externalData", "c:printSettings", "c:userShapes", "c:extLst"))
    plot_area = space.find(f"{qn('c:chart')}/{qn('c:plotArea')}")
    if plot_area is not None:
        _no_fill_sppr(plot_area, ("c:extLst",))

    for plot in chart.plots:
        _color_series(plot, palette, Pt(spec["line_width_pt"] * scale), kn.color("white"), kn.color("navy"))
    for getter in ("category_axis", "value_axis"):
        try:
            axis = getattr(chart, getter)
        except (ValueError, AttributeError):
            continue  # torta y anillo no tienen ejes
        axis.format.line.color.rgb = grid
        axis.format.line.width = Pt(spec["grid_width_pt"] * scale)
        if axis.has_major_gridlines:
            axis.major_gridlines.format.line.color.rgb = grid
            axis.major_gridlines.format.line.width = Pt(spec["grid_width_pt"] * scale)
    return 1


def charts_in(slide):
    """Gráficos nativos de la slide, también dentro de grupos."""
    def walk(shapes):
        for shape in shapes:
            if getattr(shape, "shapes", None) is not None and shape.shape_type == 6:  # grupo
                yield from walk(shape.shapes)
            elif getattr(shape, "has_chart", False) and shape.has_chart:
                yield shape
    return list(walk(slide.shapes))
