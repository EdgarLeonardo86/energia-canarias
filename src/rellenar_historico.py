#!/usr/bin/env python3
import datetime
import sys
import csv
import os
import time

from ree_utils import fetch_data, parse_day_stats

CSV_PATH = os.path.expanduser('~/proyectos/ree/historico.csv')

def get_months_ranges(start_date, end_date):
    ranges = []
    current = start_date
    while current <= end_date:
        year = current.year
        month = current.month
        if month == 12:
            next_month = datetime.date(year + 1, 1, 1)
        else:
            next_month = datetime.date(year, month + 1, 1)
        month_end = next_month - datetime.timedelta(days=1)
        
        m_start = max(current, datetime.date(year, month, 1))
        m_end = min(end_date, month_end)
        
        ranges.append((m_start.strftime('%Y-%m-%d'), m_end.strftime('%Y-%m-%d')))
        current = next_month
    return ranges

def main():
    start_date = datetime.date(2026, 1, 1)
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    today_str = today.strftime('%Y-%m-%d')

    if start_date > yesterday:
        print("La fecha de inicio es posterior a ayer.")
        return

    month_ranges = get_months_ranges(start_date, yesterday)
    
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    
    fieldnames = ['fecha', 'tecnologia', 'mwh', 'porcentaje', 'total_mwh', 'porcentaje_renovable']
    
    existing_rows = []
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('fecha', '') < today_str:
                    existing_rows.append(row)

    saved_dates = set()
    
    for i, (m_start, m_end) in enumerate(month_ranges):
        print(f"Consultando datos desde {m_start} hasta {m_end}...")
        try:
            data = fetch_data(m_start, m_end)
        except Exception as e:
            print(f"Error al consultar API para {m_start} - {m_end}: {e}", file=sys.stderr)
            continue

        included = data.get('included', [])
        
        dates_set = set()
        for item in included:
            attrs = item.get('attributes', {})
            for v in attrs.get('values', []):
                dt_str = v.get('datetime', '')[:10]
                if dt_str and dt_str < today_str:
                    dates_set.add(dt_str)

        sorted_dates = sorted(list(dates_set))

        for d_str in sorted_dates:
            try:
                stats = parse_day_stats(included, d_str)
            except ValueError as e:
                print(f"  Saltando {d_str}: {e}", file=sys.stderr)
                continue

            tech_data = stats['tech_data']
            total_gen = stats['total_gen']
            ren_pct = stats['ren_pct']

            existing_rows = [r for r in existing_rows if r.get('fecha') != d_str]

            for tech in tech_data:
                pct = (tech['val'] / total_gen * 100) if total_gen > 0 else 0.0
                existing_rows.append({
                    'fecha': d_str,
                    'tecnologia': tech['title'],
                    'mwh': f"{tech['val']:.2f}",
                    'porcentaje': f"{pct:.2f}",
                    'total_mwh': f"{total_gen:.2f}",
                    'porcentaje_renovable': f"{ren_pct:.2f}"
                })
            saved_dates.add(d_str)

        if i < len(month_ranges) - 1:
            time.sleep(2)

    existing_rows.sort(key=lambda x: (x.get('fecha', ''), x.get('tecnologia', '')))

    with open(CSV_PATH, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_rows)

    print(f"\nProceso completado. Se han guardado/actualizado datos de {len(saved_dates)} días en {CSV_PATH}.")

if __name__ == '__main__':
    main()