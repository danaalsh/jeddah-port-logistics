#!/usr/bin/env bash
# Download the latest Geofabrik GCC extract (Saudi Arabia, UAE, Oman, Qatar, Bahrain, Kuwait)
# and keep only the layers the model uses. Needs osmium-tool and curl.
# Usage: scripts/refresh_osm.sh OUT_DIR
set -euo pipefail
out=${1:?usage: refresh_osm.sh OUT_DIR}
mkdir -p "$out"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

curl -sSfL --retry 3 -o "$tmp/gcc.osm.pbf" https://download.geofabrik.de/asia/gcc-states-latest.osm.pbf
# Filtered files lose the snapshot date, so record it separately for citation
osmium fileinfo -g header.option.osmosis_replication_timestamp "$tmp/gcc.osm.pbf" > "$out/osm_date.txt"

# Routable road network: major roads only
osmium tags-filter "$tmp/gcc.osm.pbf" \
  w/highway=motorway,motorway_link,trunk,trunk_link,primary,primary_link,secondary,secondary_link \
  -o "$out/gcc_major.osm.pbf" --overwrite

# Context layers: industrial areas (industrial city outlines), ports, harbours, railways
osmium tags-filter "$tmp/gcc.osm.pbf" \
  nwr/landuse=industrial,port nwr/industrial nwr/harbour w/railway=rail \
  -o "$out/gcc_extras.osm.pbf" --overwrite

ls -lh "$out"
echo "OSM snapshot: $(cat "$out/osm_date.txt")"
