"""Style the GeoPackage layers in QGIS, store the styles in the GeoPackage (default
styles + QML copies), write a ready-to-open project, and render a preview.
Needs PyQGIS (QGIS 3.34+). Usage: QT_QPA_PLATFORM=offscreen python3 qgis_style.py OUT_DIR [PREVIEW_PNG]
OUT_DIR holds jeddah_port_gis.gpkg; writes OUT_DIR/styles/*.qml and OUT_DIR/jeddah_port_map.qgz."""
import sys, os
from pathlib import Path
from qgis.core import (QgsApplication, QgsProject, QgsVectorLayer, QgsRasterLayer, QgsLineSymbol,
                       QgsMarkerSymbol, QgsRuleBasedRenderer, QgsSingleSymbolRenderer, QgsPalLayerSettings,
                       QgsTextFormat, QgsTextBufferSettings, QgsVectorLayerSimpleLabeling, QgsCoordinateReferenceSystem,
                       QgsRectangle, QgsReferencedRectangle, QgsCoordinateTransform, QgsMapSettings,
                       QgsMapRendererParallelJob, QgsLayerTreeLayer, QgsProperty, QgsSymbolLayer, Qgis)
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtCore import QSize

out = Path(sys.argv[1]).resolve()
gpkg = out / "jeddah_port_gis.gpkg"
app = QgsApplication([], False); app.initQgis()

def lyr(name, title):
    l = QgsVectorLayer(f"{gpkg}|layername={name}", title, "ogr")
    assert l.isValid(), name
    return l

def line(color, width, style="solid"):
    return QgsLineSymbol.createSimple({"line_color": color, "line_width": str(width), "line_style": style,
                                       "capstyle": "round", "joinstyle": "round"})

def marker(shape, color, size):
    return QgsMarkerSymbol.createSimple({"name": shape, "color": color, "size": str(size),
                                         "outline_color": "255,255,255", "outline_width": "0.4"})

def rules(layer, specs):  # (label, filter, symbol, active, min_scale)
    root = QgsRuleBasedRenderer.Rule(None)
    for label, flt, sym, active, min_scale in specs:
        r = QgsRuleBasedRenderer.Rule(sym, 0, min_scale, flt, label)
        r.setActive(active)
        root.appendChild(r)
    layer.setRenderer(QgsRuleBasedRenderer(root))

def labels(layer, expr, size=9, bold=False, color="#1f2d3a"):
    s = QgsPalLayerSettings()
    s.fieldName, s.isExpression = expr, True
    f = QgsTextFormat()
    font = QFont("Arial"); font.setBold(bold)
    f.setFont(font); f.setSize(size); f.setColor(QColor(color))
    b = QgsTextBufferSettings(); b.setEnabled(True); b.setSize(1); b.setColor(QColor("white"))
    f.setBuffer(b)
    s.setFormat(f)
    s.placement = Qgis.LabelPlacement.OrderedPositionsAroundPoint
    s.dist = 1.5
    layer.setLabeling(QgsVectorLayerSimpleLabeling(s)); layer.setLabelsEnabled(True)

L = {}
L["roads"] = lyr("roads", "Road network (model)")
rules(L["roads"], [
    ("Motorway", "\"road_class\" = 'motorway'", line("#8c8c8c", 0.55), True, 0),
    ("Trunk", "\"road_class\" = 'trunk'", line("#a3a3a3", 0.45), True, 0),
    ("Primary", "\"road_class\" = 'primary'", line("#c2c2c2", 0.3), True, 0),
    ("Secondary (zoom in past 1:2,500,000)", "\"road_class\" = 'secondary'", line("#d9d9d9", 0.2), True, 2_500_000),
])
L["routes"] = lyr("routes", "Routes")
rules(L["routes"], [
    ("Truck (speed capped)", "\"profile\" = 'truck'", line("#c0392b", 0.9), True, 0),
    ("Car (free-flow)", "\"profile\" = 'car'", line("#2471a3", 0.6, "dash"), False, 0),
])
L["destinations"] = lyr("destinations", "Cities & sites")
L["destinations"].setRenderer(QgsSingleSymbolRenderer(marker("circle", "#2c3e50", 2.6)))
labels(L["destinations"], "\"name\" || if(\"truck_hours\" IS NULL, '', '\\n' || format_number(\"truck_hours\", 1) || ' h by truck')")
L["port"] = lyr("port", "Port")
L["port"].setRenderer(QgsSingleSymbolRenderer(marker("star", "#000000", 5.5)))
labels(L["port"], "\"name\"", size=10, bold=True)
L["seaports"] = lyr("seaports", "Seaports (PortWatch)")
size = QgsProperty.fromExpression(
    'scale_linear(sqrt(coalesce("import_Mt_month_before", 0) + coalesce("export_Mt_month_before", 0)), 0, 3.7, 1.6, 7)')
port_syms = []
for color in ("#2a78d6", "#eb6834"):
    sym = marker("circle", color, 2.5)
    sym.setDataDefinedSize(size)
    sym.setOpacity(0.85)
    port_syms.append(sym)
rules(L["seaports"], [
    ("Red Sea port (size = monthly trade before the Hormuz closure)", "\"coast\" = 'Red Sea'", port_syms[0], True, 0),
    ("Gulf port", "\"coast\" = 'Gulf'", port_syms[1], True, 0),
])
labels(L["seaports"], "if(coalesce(\"import_Mt_month_before\", 0) + coalesce(\"export_Mt_month_before\", 0) >= 0.5, \"portname\", '')", size=8, color="#52514e")
L["port_gates"] = lyr("port_gates", "Truck gates")
L["port_gates"].setRenderer(QgsSingleSymbolRenderer(marker("square", "#7d3c98", 2.6)))
labels(L["port_gates"], "\"name\"", size=8)
L["constraints"] = lyr("constraints", "Constraints")
L["constraints"].setRenderer(QgsSingleSymbolRenderer(marker("triangle", "#e67e22", 3.4)))
labels(L["constraints"], "\"kind\"", size=8, color="#a04000")
L["shipments"] = lyr("shipments", "Shipments")

# Simulation layers (notebook 02), if present: one colour per scenario, baseline shown by default
SCENARIO_COLORS = {"baseline": "#2a78d6", "hormuz_closed": "#eb6834", "babelmandeb_closed": "#1baf7a",
                   "both_closed": "#eda100"}
SIM = [n for n in ("sim_road_legs", "sim_sea_legs", "sim_ports", "sim_destinations")
       if QgsVectorLayer(f"{gpkg}|layername={n}", n, "ogr").isValid()]
if "sim_road_legs" in SIM:
    L["sim_road_legs"] = lyr("sim_road_legs", "Routes by scenario (road)")
    rules(L["sim_road_legs"], [(sc.replace("_", " ").capitalize(), f"\"scenario\" = '{sc}'", line(c, 0.8), sc == "baseline", 0)
                               for sc, c in SCENARIO_COLORS.items()])
if "sim_sea_legs" in SIM:
    L["sim_sea_legs"] = lyr("sim_sea_legs", "Routes by scenario (sea)")
    rules(L["sim_sea_legs"], [(sc.replace("_", " ").capitalize(), f"\"scenario\" = '{sc}' AND \"used\"",
                               line(c, 0.5, "dash"), sc == "baseline", 0) for sc, c in SCENARIO_COLORS.items()])
if "sim_ports" in SIM:
    L["sim_ports"] = lyr("sim_ports", "Ports in the model")
    L["sim_ports"].setRenderer(QgsSingleSymbolRenderer(marker("square", "#0b0b0b", 2.8)))
    labels(L["sim_ports"], "\"port_key\" || ' ' || \"name\"", size=8)
if "sim_destinations" in SIM:
    L["sim_destinations"] = lyr("sim_destinations", "Destinations in the model")
    rules(L["sim_destinations"], [
        ("Industrial city", "\"type\" = 'industrial_city'", marker("triangle", "#6250d6", 3.0), True, 0),
        ("City", "\"type\" <> 'industrial_city'", marker("circle", "#52514e", 2.2), True, 0)])
    labels(L["sim_destinations"], "\"name\"", size=7.5, color="#52514e")

# Default styles inside the GeoPackage, plus QML copies the notebook can re-apply to a fresh file
(out / "styles").mkdir(exist_ok=True)
for name, l in L.items():
    if name == "shipments":
        continue
    err = l.saveStyleToDatabase("jeddah_port", "styled by notebook setup", True, "")
    assert not err, (name, err)
    l.saveNamedStyle(str(out / "styles" / f"{name}.qml"))

# Project: layer order, groups, basemap, start view on KSA
p = QgsProject.instance()
p.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
p.setTitle("Jeddah Islamic Port road routes")
p.setFilePathStorage(Qgis.FilePathType.Relative)
# Esri Light Gray needs no API key (CARTO now watermarks keyless tiles). Note the {y}/{x} order.
base = QgsRasterLayer("type=xyz&url=https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/"
                      "MapServer/tile/%7Bz%7D/%7By%7D/%7Bx%7D&zmax=16&zmin=0", "Basemap (Esri Light Gray)", "wms")
osm = QgsRasterLayer("type=xyz&url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=19&zmin=0",
                     "Basemap (OpenStreetMap)", "wms")
root = p.layerTreeRoot()
if SIM:
    simg = root.addGroup("Simulation (notebook 02)")
    for name in ("sim_ports", "sim_destinations", "sim_sea_legs", "sim_road_legs"):
        if name in L:
            p.addMapLayer(L[name], False); simg.addLayer(L[name])
yours = root.addGroup("Your data (to fill in)")
for name in ("port_gates", "constraints", "shipments"):
    p.addMapLayer(L[name], False); yours.addLayer(L[name])
model = root.addGroup("Model")
for name in ("port", "seaports", "destinations", "routes", "roads"):
    p.addMapLayer(L[name], False); model.addLayer(L[name])
for b, on in ((base, True), (osm, False)):
    p.addMapLayer(b, False); root.addLayer(b).setItemVisibilityChecked(on)

ksa = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), p.crs(), p).transformBoundingBox(
    QgsRectangle(34.0, 15.5, 56.5, 32.5))
p.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(ksa, p.crs()))
assert p.write(str(out / "jeddah_port_map.qgz"))

# Preview (no basemap: tile servers are unreachable from where this runs)
ms = QgsMapSettings()
ms.setLayers([L[n] for n in ("port", "seaports", "destinations", "routes", "roads")])
ms.setDestinationCrs(p.crs()); ms.setExtent(ksa); ms.setOutputSize(QSize(1400, 1250))
ms.setBackgroundColor(QColor("white")); ms.setFlag(Qgis.MapSettingsFlag.DrawLabeling, True)
job = QgsMapRendererParallelJob(ms); job.start(); job.waitForFinished()
job.renderedImage().save(sys.argv[2] if len(sys.argv) > 2 else str(out / "qgis_preview.png"))
print("ok", sorted(os.listdir(out)))
app.exitQgis()
