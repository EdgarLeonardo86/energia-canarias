#!/usr/bin/env python3
import datetime
import sys
import csv
import os

# Añadir src al path para imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from ree_utils import fetch_data, parse_day_stats, fill_missing_days, REEApiError, REEZeroDataError, REEIncompleteDataError
from meteo_utils import fetch_open_meteo_archive, parse_meteo_response, save_to_csv as save_meteo_to_csv, PUNTOS

# Rutas relativas a la raíz del repositorio
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, 'data', 'historico.csv')
METEO_CSV_PATH = os.path.join(BASE_DIR, 'data', 'meteo.csv')

def save_to_csv(date_str, tech_data, total_gen, ren_pct):
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    if date_str >= today_str:
        return

    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    
    fieldnames = ['fecha', 'tecnologia', 'mwh', 'porcentaje', 'total_mwh', 'porcentaje_renovable']
    
    existing_rows = []
    file_exists = os.path.exists(CSV_PATH)
    
    if file_exists:
        with open(CSV_PATH, mode='r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('fecha') != date_str:
                    existing_rows.append(row)

    new_rows = []
    for tech in tech_data:
        pct = (tech['val'] / total_gen * 100) if total_gen > 0 else 0.0
        new_rows.append({
            'fecha': date_str,
            'tecnologia': tech['title'],
            'mwh': f"{tech['val']:.2f}",
            'porcentaje': f"{pct:.2f}",
            'total_mwh': f"{total_gen:.2f}",
            'porcentaje_renovable': f"{ren_pct:.2f}"
        })

    all_rows = existing_rows + new_rows
    all_rows.sort(key=lambda x: (x.get('fecha', ''), x.get('tecnologia', '')))

    with open(CSV_PATH, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator='\n')
        writer.writeheader()
        writer.writerows(all_rows)

def update_meteo_for_date(date_str):
    """Descarga y añade los datos meteo de la fecha indicada a meteo.csv"""
    d = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    today = datetime.date.today()
    if d >= today:
        return
    
    all_new_rows = []
    for punto in PUNTOS:
        nombre = punto['nombre']
        lat, lon = punto['lat'], punto['lon']
        try:
            data = fetch_open_meteo_archive(lat, lon, date_str, date_str)
            rows = parse_meteo_response(data, nombre)
            all_new_rows.extend(rows)
        except Exception as e:
            print(f"Advertencia al descargar meteo para {nombre} ({date_str}): {e}", file=sys.stderr)
    
    if all_new_rows:
        save_meteo_to_csv(METEO_CSV_PATH, all_new_rows)

def update_meteo_up_to_yesterday():
    """Actualiza meteo.csv para todos los días faltantes hasta ayer inclusive"""
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    
    # Leer fechas ya existentes en meteo.csv
    existing_dates = set()
    if os.path.exists(METEO_CSV_PATH):
        with open(METEO_CSV_PATH, mode='r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_dates.add(row.get('fecha'))
    
    # Rellenar desde 2026-01-01 hasta ayer
    start_date = datetime.date(2026, 1, 1)
    end_date = datetime.date.today() - datetime.timedelta(days=1)
    
    current = start_date
    while current <= end_date:
        date_str = current.strftime('%Y-%m-%d')
        if date_str not in existing_dates:
            update_meteo_for_date(date_str)
            existing_dates.add(date_str)
        current += datetime.timedelta(days=1)

def main():
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    day_before = today - datetime.timedelta(days=2)

    yesterday_str = yesterday.strftime('%Y-%m-%d')
    day_before_str = day_before.strftime('%Y-%m-%d')

    # 1. ACTUALIZAR METEO SIEMPRE (hasta ayer inclusive)
    update_meteo_up_to_yesterday()

    # 2. Rellenar días faltantes de REE de los últimos 7 días
    try:
        recovered = fill_missing_days(CSV_PATH, days_back=7)
        if recovered:
            recovered_display = [datetime.datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m') for d in recovered]
            print(f"Recuperados: {', '.join(recovered_display)}")
    except Exception as e:
        print(f"Advertencia al rellenar histórico REE: {e}", file=sys.stderr)

    # 3. Obtener datos de ayer y anteayer (un solo intento, sin esperas)
    try:
        data = fetch_data(day_before_str, yesterday_str, retries=0)
    except REEApiError:
        print(f"REE aún no ha publicado los datos de {yesterday_str}; se recuperarán automáticamente en la próxima ejecución")
        sys.exit(0)
    except REEZeroDataError as e:
        print(f"DATOS A CERO: {e}", file=sys.stderr)
        sys.exit(1)

    included = data.get('included', [])

    try:
        prev_day_stats = parse_day_stats(included, day_before_str, CSV_PATH)
        yest_stats = parse_day_stats(included, yesterday_str, CSV_PATH)
    except REEZeroDataError as e:
        print(f"DATOS A CERO: {e}", file=sys.stderr)
        sys.exit(1)
    except REEIncompleteDataError as e:
        print(f"DATO INCOMPLETO: {e}", file=sys.stderr)
        sys.exit(1)

    total_gen = yest_stats['total_gen']
    ren_pct = yest_stats['ren_pct']
    prev_ren_pct = prev_day_stats['ren_pct']
    diff_pct = ren_pct - prev_ren_pct

    save_to_csv(yesterday_str, yest_stats['tech_data'], total_gen, ren_pct)

    sign = "+" if diff_pct >= 0 else ""

    print(f"=== Resumen de Generación Eléctrica en Canarias ({yesterday_str}) ===")
    print(f"Generación total: {total_gen:,.2f} MWh\n")
    print("Desglose por tecnología:")
    for tech in yest_stats['tech_data']:
        pct = (tech['val'] / total_gen * 100) if total_gen > 0 else 0.0
        print(f"  - {tech['title']}: {tech['val']:,.2f} MWh ({pct:.2f}%)")

    print(f"\nGeneración renovable total: {yest_stats['renewable_mwh']:,.2f} MWh")
    print(f"Porcentaje renovable sobre el total: {ren_pct:.2f}%")
    print(f"Comparación vs. día anterior ({day_before_str}): {ren_pct:.2f}% vs {prev_ren_pct:.2f}% ({sign}{diff_pct:.2f} p.p.)")

if __name__ == '__main__':
    main()