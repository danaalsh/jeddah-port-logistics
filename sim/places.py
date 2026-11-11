"""Saudi industrial areas from OpenStreetMap: used to locate industrial cities."""
import re

import geopandas as gpd
import osmium
import pandas as pd
from shapely import wkb

NAME = re.compile(r"industrial city|المدينة الصناعية|مدينة .*الصناعية", re.IGNORECASE)
METRIC = "+proj=lcc +lat_1=17 +lat_2=27 +lat_0=22 +lon_0=48 +datum=WGS84 +units=m"


def in_saudi(lon, lat):
    """Rough Saudi test for points from the GCC extract: east of 50.25°E is Bahrain, Qatar, UAE or
    Oman for industrial areas, and the Kuwait corner is excluded. Good enough to pick
    industrial cities; not a border."""
    return (lon < 50.25) & ~((lat > 28.53) & (lon > 46.5))


def industrial_areas(extras_pbf):
    """All OSM landuse=industrial areas in Saudi Arabia: osm_id, name, name_en, name_ar, area_km2,
    lat/lon of a point inside the area, geometry (EPSG:4326)."""
    factory = osmium.geom.WKBFactory()
    rows = []
    for o in osmium.FileProcessor(str(extras_pbf)).with_areas():
        if not (o.is_area() and o.tags.get("landuse") == "industrial"):
            continue
        try:
            geom = wkb.loads(factory.create_multipolygon(o), hex=True)
        except RuntimeError:  # broken multipolygon in OSM
            continue
        rows.append(dict(osm_id=o.orig_id(), name=o.tags.get("name"), name_en=o.tags.get("name:en"),
                         name_ar=o.tags.get("name:ar"), geometry=geom))
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    metric = gdf.to_crs(METRIC)
    gdf["area_km2"] = metric.area / 1e6
    pt = metric.representative_point().to_crs("EPSG:4326")
    gdf["lon"], gdf["lat"] = pt.x.round(5), pt.y.round(5)
    return gdf[in_saudi(gdf.lon, gdf.lat)].reset_index(drop=True)


def industrial_cities(extras_pbf, min_area_km2=0.5):
    """Saudi industrial areas whose OSM name says industrial city (a fallback when no official list
    is available; config/industrial_cities_modon.csv is the MODON list). Areas with the same name are
    merged; one point per city at its largest part."""
    a = industrial_areas(extras_pbf)
    a["label"] = a.name_en.fillna(a.name)
    a = a[a.label.notna() & (a.label.fillna("").str.contains(NAME) | a.name.fillna("").str.contains(NAME))]
    a = a.sort_values("area_km2", ascending=False)
    out = a.groupby("label", sort=False).agg(name_ar=("name", "first"), osm_id=("osm_id", "first"),
                                             area_km2=("area_km2", "sum"), lat=("lat", "first"), lon=("lon", "first"))
    out = out[out.area_km2 >= min_area_km2].reset_index().rename(columns={"label": "name"})
    out.insert(0, "dest_id", [f"IND{i + 1:02d}" for i in range(len(out))])
    out["type"] = "industrial_city"
    out["source"] = "OpenStreetMap landuse=industrial (name match)"
    return out
