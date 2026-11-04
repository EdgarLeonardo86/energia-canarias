#!/usr/bin/env python3
import datetime
import sys
import time
from meteo_utils import PUNTOS, fetch_open_meteo_archive, parse_meteo_response, save_to_csv

CSV_PATH = '/home/agentes/proyectos/ree/meteo.csv'

def main():
    # Hoy es 2026-11-02, ayer 2026-11-01
    start_date = datetime.date(2026, 1, 1)
    end_date = datetime.date(2026, 11, 1)  # Ayer
    
    print(f"Descargando datos meteorológicos desde {start_date} hasta {end_date}...")
    
    all_new_rows = []
    
    for punto in PUNTOS:
        nombre = punto['nombre']
        lat, lon = punto['lat'], punto['lon']
        print(f"  Procesando {nombre} ({lat}, {lon})...")
        
        success = False
        for attempt in range(3):
            try:
                data = fetch_open_meteo_archive(
                    lat, lon,
                    start_date.strftime('%Y-%m-%d'),
                    end_date.strftime('%Y-%m-%d')
                )
                rows = parse_meteo_response(data, nombre)
                all_new_rows.extend(rows)
                print(f"    {len(rows)} días (intento {attempt + 1})")
                success = True
                break
            except Exception as e:
                print(f"    Error (intento {attempt + 1}): {e}")
                time.sleep(2)
        
        if not success:
            print(f"    ¡Aviso! No se pudo descargar {nombre} tras 3 intentos.")
        
        time.sleep(1)
    
    if all_new_rows:
        saved = save_to_csv(CSV_PATH, all_new_rows)
        print(f"\nGuardados {saved} nuevos registros en {CSV_PATH}")
    else:
        print("No hay nuevos datos para guardar.")

if __name__ == '__main__':
    main()