import datetime
import json
import urllib.request
import sys
import time

# 4 puntos con muchos parques eólicos/solares en Canarias
PUNTOS = [
    {"nombre": "Arinaga", "lat": 27.86, "lon": -15.39},
    {"nombre": "Granadilla", "lat": 28.08, "lon": -16.50},
    {"nombre": "Fuerteventura", "lat": 28.40, "lon": -14.00},
    {"nombre": "Lanzarote", "lat": 29.00, "lon": -13.65},
]

VARIABLES_DIARIAS = [
    "wind_speed_10m_mean",
    "wind_gusts_10m_max",
    "shortwave_radiation_sum",
]

KM_H_TO_M_S = 1/3.6

def fetch_open_meteo_archive(lat, lon, start_date, end_date):
    """Consulta la API histórica (archive) de Open-Meteo."""
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={lat}&longitude={lon}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&daily={','.join(VARIABLES_DIARIAS)}"
        f"&timezone=UTC"
    )
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

def parse_meteo_response(data, punto_nombre):
    """Convierte la respuesta de Open-Meteo a lista de dicts (unidades en m/s y MJ/m2)."""
    daily = data.get('daily', {})
    dates = daily.get('time', [])
    wind_mean_kmh = daily.get('wind_speed_10m_mean', [])
    wind_gust_kmh = daily.get('wind_gusts_10m_max', [])
    radiation = daily.get('shortwave_radiation_sum', [])
    
    rows = []
    for i, d in enumerate(dates):
        wm = wind_mean_kmh[i] if i < len(wind_mean_kmh) else None
        wg = wind_gust_kmh[i] if i < len(wind_gust_kmh) else None
        rad = radiation[i] if i < len(radiation) else None
        rows.append({
            'fecha': d,
            'punto': punto_nombre,
            'viento_medio': round(wm * KM_H_TO_M_S, 1) if wm is not None else None,
            'racha_max': round(wg * KM_H_TO_M_S, 1) if wg is not None else None,
            'radiacion': rad,
        })
    return rows

def save_to_csv(csv_path, new_rows):
    """Guarda/actualiza el CSV sin duplicados (fecha + punto)."""
    import csv
    import os
    
    fieldnames = ['fecha', 'punto', 'viento_medio', 'racha_max', 'radiacion']
    
    existing = []
    if os.path.exists(csv_path):
        with open(csv_path, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing.append(row)
    
    existing_keys = {(r['fecha'], r['punto']) for r in existing}
    
    for row in new_rows:
        key = (row['fecha'], row['punto'])
        if key not in existing_keys:
            existing.append(row)
            existing_keys.add(key)
    
    existing.sort(key=lambda x: (x.get('fecha', ''), x.get('punto', '')))
    
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator='\n')
        writer.writeheader()
        writer.writerows(existing)
    
    return len(new_rows)