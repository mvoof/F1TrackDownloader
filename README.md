# F1™ Track Downloader

Downloads Formula 1™ circuit geometries from OpenStreetMap as GeoJSON files.

## Installation

```bash
# Install uv (if needed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone https://github.com/mvoof/F1TrackDownloader.git
cd F1TrackDownloader
uv sync
```

## Usage

```bash
# Download all circuits
uv run main.py

# Check for updates only
uv run main.py --check-update

# Alternative: run as module
uv run -m f1_downloader
```

Output files are saved to `tracks_geojson/` directory.

## Project Structure

```
f1_downloader/
├── __init__.py       # Package exports
├── __main__.py       # Entry: python -m f1_downloader
├── config.py         # Configuration dataclass
├── models.py         # Circuit, SearchResult, CacheEntry
├── cache.py          # CircuitCache class
├── clients/          # API clients
│   ├── overpass.py   # Overpass API (5 servers, failover)
│   ├── wikipedia.py  # Wikipedia parser
│   ├── wikidata.py   # Wikidata API
│   └── osm.py        # OSM API
├── services.py       # Search and processing logic
├── utils.py          # Logging, atomic writes
└── cli.py            # CLI interface

main.py               # Entry point wrapper
```

## How It Works

### Data Pipeline

```
Wikipedia → Wikidata → OpenStreetMap → GeoJSON
```

1. **Fetch circuit list** from [Wikipedia](https://en.wikipedia.org/wiki/List_of_Formula_One_circuits)
2. **Find Wikidata ID** (Q-ID) for each circuit name
3. **Find OSM relation** using:
   - Wikidata P402 property (direct link to OSM)
   - `wikidata=Q*` tag search in OSM
   - Direct name search in OSM
4. **Download geometry** from Overpass API
5. **Save as GeoJSON**

### Overpass API Servers

The script uses 5 [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API) servers with automatic failover:
- overpass-api.de (Germany, main)
- kumi.systems (Global)
- maps.mail.ru (Russia)
- private.coffee (Global)
- osm.jp (Japan)

If one server fails, the next is tried automatically.

### Caching

All discovered mappings are cached in `circuit_mappings.json`:
- First run: searches for all circuits, saves results
- Subsequent runs: uses cached IDs, much faster
- Cache includes OSM ID, Wikidata ID, and search method

## Manual Mapping

Some circuits can't be found automatically because:
- Different names in OSM
- Missing Wikidata links
- Circuit no longer exists

When a circuit is not found, it's automatically added to `circuit_mappings.json` with `manual: true` and a TODO comment.

### Adding Manual Mappings

Edit `circuit_mappings.json`. Minimal required fields:

```json
"Autódromo Hermanos Rodríguez": {
  "osm_id": 16251935,
  "osm_type": "relation",
  "manual": true
}
```

Full example with all fields:

```json
"Autódromo Hermanos Rodríguez": {
  "osm_id": 16251935,
  "osm_type": "relation",
  "wikidata_id": "Q173099",
  "manual": true,
  "comment": "Found via Mexican Grand Prix search"
}
```

### Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `osm_id` | **Yes** | OSM element ID (number) or `null` if doesn't exist |
| `osm_type` | **Yes** | `"relation"` or `"way"` |
| `manual` | **Yes** | Set to `true` to prevent auto-updates |
| `wikidata_id` | No | Wikidata Q-ID (e.g., `"Q173099"`) |
| `comment` | No | Notes for yourself |
| `search_method` | No | Auto-filled: how it was found |
| `search_name` | No | Auto-filled: which name matched |
| `verified_at` | No | Auto-filled: timestamp |
| `osm_version` | No | Auto-filled: for update tracking |

### Finding OSM ID

1. Go to [openstreetmap.org](https://www.openstreetmap.org)
2. Search for the circuit name or browse the map
3. Click on the track (look for `leisure=track` or `highway=raceway`)
4. Check URL: `openstreetmap.org/relation/16251935` → ID is `16251935`, type is `relation`
5. Or: `openstreetmap.org/way/123456` → ID is `123456`, type is `way`

### Marking Non-Existent Circuits

For demolished or unmapped circuits, set `osm_id` to `null`:

```json
"Ain-Diab Circuit": {
  "osm_id": null,
  "manual": true,
  "comment": "Circuit demolished, not in OSM"
}
```

## Output Format

Each circuit is saved as a GeoJSON FeatureCollection:

```json
{
  "type": "FeatureCollection",
  "properties": {
    "name": "Silverstone Circuit",
    "_osm_id": 2783447,
    "_osm_version": 15
  },
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "LineString",
        "coordinates": [[...], [...]]
      },
      "properties": {
        "role": "outer",
        "ref": 123456
      }
    }
  ]
}
```

## Troubleshooting

### Circuit not found

Check the output message:
- `Not in OSM (Wikidata: Q123)` → Circuit exists in Wikidata but not linked to OSM
- `Not found in Wikidata` → Need to add manually to `circuit_mappings.json`

Also you can manualy check tags on OSM like `highway=raceway` or `sport=motor` and check track name.

### API errors

The script automatically retries with different servers. If all fail:
- Check your internet connection
- Wait a few minutes (servers may be overloaded)
- Try again later

### Updating cached data

Delete the circuit entry from `circuit_mappings.json` or set `manual: false` to force re-search.

### Disclaimer

This repository is unofficial and is not associated in any way with the Formula 1 companies. F1, FORMULA ONE, FORMULA 1, FIA FORMULA ONE WORLD CHAMPIONSHIP, GRAND PRIX, and related marks are trademarks of Formula One Licensing B.V.

Formula 1™ circuits data are not official, and they are not approved nor endorsed by Formula One Licensing B.V.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

### Data Attribution

This tool uses data from:
- **Wikipedia** - Content is available under the [CC BY-SA license](https://creativecommons.org/licenses/by-sa/3.0/)
- **OpenStreetMap** - Data is available under the [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/)

Please respect the respective licenses when using the downloaded data.
