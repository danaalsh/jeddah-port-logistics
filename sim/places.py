"""Destinations: Saudi industrial cities from OpenStreetMap industrial areas."""
import re

import geopandas as gpd
import osmium
import pandas as pd
from shapely import wkb

NAME = re.compile(r"industrial city|المدينة الصناعية|مدينة .*الصناعية", re.IGNORECASE)


def in_saudi(lon, lat):
    """Rough Saudi test for points from the GCC extract: east of 50.25°E is Bahrain, Qatar, UAE or
    Oman for industrial areas, and the Kuwait corner is excluded. Good enough to pick
    industrial cities; not a border."""
    return (lon < 50.25) & ~((lat > 28.53) & (lon > 46.5))


def industrial_cities(extras_pbf, min_area_km2=0.5):
    """Named Saudi industrial cities (OSM landuse=industrial areas whose name says industrial city).
    Areas with the same name are merged; returns one point per city at its largest part's centre."""
    factory = osmium.geom.WKBFactory()
    rows = []
    for o in osmium.FileProcessor(str(extras_pbf)).with_areas():
        if not (o.is_area() and o.tags.get("landuse") == "industrial"):
            continue
        name_en, name = o.tags.get("name:en"), o.tags.get("name")
        label = name_en or name
        if not label or not (NAME.search(label) or (name and NAME.search(name))):
            continue
        try:
            geom = wkb.loads(factory.create_multipolygon(o), hex=True)
        except RuntimeError:  # broken multipolygon in OSM
            continue
        rows.append(dict(name=label, name_ar=name if name != label else None, osm_id=o.orig_id(),
                         geometry=geom))
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    metric = gdf.to_crs("+proj=lcc +lat_1=17 +lat_2=27 +lat_0=22 +lon_0=48 +datum=WGS84 +units=m")
    gdf["area_km2"] = metric.area / 1e6
    gdf = gdf.sort_values("area_km2", ascending=False)
    merged = gdf.groupby("name", sort=False).agg(
        name_ar=("name_ar", "first"), osm_id=("osm_id", "first"), area_km2=("area_km2", "sum"),
        geometry=("geometry", "first"))
    out = gpd.GeoDataFrame(merged.reset_index(), crs="EPSG:4326")
    pt = out.to_crs(metric.crs).representative_point().to_crs("EPSG:4326")
    out["lon"], out["lat"] = pt.x.round(5), pt.y.round(5)
    out = out[in_saudi(out.lon, out.lat) & (out.area_km2 >= min_area_km2)]
    out = out.drop(columns="geometry").sort_values("area_km2", ascending=False).reset_index(drop=True)
    out.insert(0, "dest_id", [f"IND{i + 1:02d}" for i in range(len(out))])
    out["type"] = "industrial_city"
    out["source"] = "OpenStreetMap landuse=industrial (name match)"
    return pd.DataFrame(out)
