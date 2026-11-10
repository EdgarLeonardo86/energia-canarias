import datetime
import json
import urllib.request
import sys
import time

class REEApiError(Exception):
    """Error cuando la API de REE no está disponible (502, 503, etc.)"""
    pass

class REEZeroDataError(Exception):
    """Error cuando la API responde pero los datos son 0"""
    pass

class REEIncompleteDataError(Exception):
    """Error cuando la API responde pero el total del día es inferior al 70% de la mediana de los 30 días anteriores"""
    pass

def fetch_data(start_date, end_date, retries=0, retry_delay_seconds=1800):
    """
    Consulta la API de REE con reintentos opcionales.
    retries=0 (por defecto): un solo intento, sin esperas.
    retries>0: reintenta cada retry_delay_seconds.
    Lanza REEApiError si la API falla tras reintentos.
    Lanza REEZeroDataError si la respuesta es exitosa pero total = 0.
    """
    url = (
        f"https://apidatos.ree.es/es/datos/generacion/estructura-generacion?"
        f"start_date={start_date}T00:00&end_date={end_date}T23:59&"
        f"time_trunc=day&geo_trunc=electric_system&geo_limit=canarias&geo_ids=8742"
    )
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})

    max_attempts = retries + 1

    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                included = data.get('included', [])
                has_data = False
                for item in included:
                    attrs = item.get('attributes', {})
                    values = attrs.get('values', [])
                    for v in values:
                        if v.get('value', 0) > 0:
                            has_data = True
                            break
                    if has_data:
                        break
                if not has_data and included:
                    raise REEZeroDataError("REE respondió pero todos los valores son 0")
                return data
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504):
                if attempt < max_attempts - 1:
                    time.sleep(retry_delay_seconds)
                    continue
                raise REEApiError(f"HTTP {e.code}")
            else:
                raise REEApiError(f"Error HTTP {e.code}")
        except urllib.error.URLError as e:
            if attempt < max_attempts - 1:
                time.sleep(retry_delay_seconds)
                continue
            raise REEApiError(f"Error de red: {e}")
        except REEZeroDataError:
            raise
        except Exception as e:
            if attempt < max_attempts - 1:
                time.sleep(retry_delay_seconds)
                continue
            raise REEApiError(f"Error inesperado: {e}")

    raise REEApiError("API no disponible")


def is_day_incomplete(csv_path, target_date_str, target_total, threshold=0.7, lookback_days=30):
    """
    Verifica si un día tiene datos incompletos comparando el total
    con el 70% de la mediana de los 30 días anteriores en el histórico.
    Devuelve True si el día es incompleto (no debe guardarse).
    """
    import csv
    import os

    if not os.path.exists(csv_path):
        return False  # Sin histórico, no podemos validar

    try:
        target_date = datetime.datetime.strptime(target_date_str, '%Y-%m-%d').date()
    except ValueError:
        return False

    # Leer histórico y calcular total diario
    daily_totals = {}
    try:
        with open(csv_path, mode='r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                fecha = row.get('fecha')
                total = row.get('total_mwh')
                if fecha and total:
                    try:
                        daily_totals[fecha] = float(total)
                    except ValueError:
                        pass
    except Exception:
        return False

    # Obtener totales de los 30 días anteriores
    target_date_obj = datetime.datetime.strptime(target_date_str, '%Y-%m-%d').date()
    prev_30_start = target_date_obj - datetime.timedelta(days=30)
    prev_30_end = target_date_obj - datetime.timedelta(days=1)

    prev_totals = []
    for fecha_str, total in daily_totals.items():
        try:
            fecha = datetime.datetime.strptime(fecha_str, '%Y-%m-%d').date()
            if prev_30_start <= fecha <= prev_30_end:
                prev_totals.append(total)
        except ValueError:
            pass

    if len(prev_totals) < 10:  # Mínimo 10 días para calcular mediana fiable
        return False

    # Calcular mediana
    prev_totals_sorted = sorted(prev_totals)
    n = len(prev_totals_sorted)
    if n % 2 == 0:
        mediana = (prev_totals_sorted[n//2 - 1] + prev_totals_sorted[n//2]) / 2
    else:
        mediana = prev_totals_sorted[n//2]

    # Verificar umbral usando el total pasado como parámetro
    threshold_value = 0.7 * mediana
    if target_total < threshold_value:
        return True  # Día incompleto

    return False


def parse_day_stats(included, target_date_str, csv_path=None):
    tech_data = []
    total_from_api = None
    sum_mwh = 0.0
    renewable_mwh = 0.0

    for item in included:
        attrs = item.get('attributes', {})
        title = attrs.get('title', '')
        gen_type = attrs.get('type', '')
        values = attrs.get('values', [])

        val = 0.0
        for v in values:
            if v.get('datetime', '').startswith(target_date_str):
                val = v.get('value', 0.0)
                break

        if gen_type == 'total' or title.lower() == 'generación total':
            total_from_api = val
        else:
            tech_data.append({
                'title': title,
                'type': gen_type,
                'val': val
            })
            if gen_type == 'Renovable':
                renewable_mwh += val
            sum_mwh += val

    total_gen = total_from_api if total_from_api is not None and total_from_api > 0 else sum_mwh
    ren_pct = (renewable_mwh / total_gen * 100) if total_gen > 0 else 0.0

    if total_gen == 0:
        raise REEZeroDataError(f"ERROR: La generación total para la fecha {target_date_str} es 0 MWh.")

    # Validar día incompleto si se proporciona csv_path
    if csv_path and is_day_incomplete(csv_path, target_date_str, total_gen):
        raise REEIncompleteDataError(
            f"DATOS INCOMPLETOS: La generación total para {target_date_str} ({total_gen:.2f} MWh) "
            f"está por debajo del 70% de la mediana de los 30 días anteriores. "
            f"Dato no guardado, se reintentará en siguientes ejecuciones."
        )

    return {
        'total_gen': total_gen,
        'renewable_mwh': renewable_mwh,
        'ren_pct': ren_pct,
        'tech_data': tech_data
    }


def fill_missing_days(csv_path, days_back=7):
    """
    Revisa los últimos N días en el histórico y rellena los que falten.
    Un solo intento por día (retries=0), sin esperas.
    Devuelve la lista de fechas efectivamente recuperadas (formato YYYY-MM-DD).
    """
    import csv
    import os

    today = datetime.date.today()
    end_date = today - datetime.timedelta(days=1)
    start_date = end_date - datetime.timedelta(days=days_back - 1)

    existing_dates = set()
    if os.path.exists(csv_path):
        with open(csv_path, mode='r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_dates.add(row.get('fecha'))

    missing_dates = []
    current = start_date
    while current <= end_date:
        date_str = current.strftime('%Y-%m-%d')
        if date_str not in existing_dates:
            missing_dates.append(date_str)
        current += datetime.timedelta(days=1)

    if not missing_dates:
        return []

    from collections import defaultdict
    month_data = defaultdict(list)
    for d in missing_dates:
        dt = datetime.datetime.strptime(d, '%Y-%m-%d')
        month_key = dt.strftime('%Y-%m')
        month_data[month_key].append(d)

    fieldnames = ['fecha', 'tecnologia', 'mwh', 'porcentaje', 'total_mwh', 'porcentaje_renovable']

    all_rows = []
    if os.path.exists(csv_path):
        with open(csv_path, mode='r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                all_rows.append(row)

    successfully_recovered = []

    for month_key, dates in month_data.items():
        dt = datetime.datetime.strptime(dates[0], '%Y-%m-%d')
        if dt.month == 12:
            next_month = datetime.date(dt.year + 1, 1, 1)
        else:
            next_month = datetime.date(dt.year, dt.month + 1, 1)
        month_end = next_month - datetime.timedelta(days=1)

        m_start = max(datetime.date(dt.year, dt.month, 1), min(map(lambda x: datetime.datetime.strptime(x, '%Y-%m-%d').date(), dates)))
        m_end = min(month_end, max(map(lambda x: datetime.datetime.strptime(x, '%Y-%m-%d').date(), dates)))

        try:
            data = fetch_data(m_start.strftime('%Y-%m-%d'), m_end.strftime('%Y-%m-%d'), retries=0)
            included = data.get('included', [])

            for d_str in dates:
                try:
                    stats = parse_day_stats(included, d_str, csv_path)
                    all_rows = [r for r in all_rows if r.get('fecha') != d_str]
                    for tech in stats['tech_data']:
                        pct = (tech['val'] / stats['total_gen'] * 100) if stats['total_gen'] > 0 else 0.0
                        all_rows.append({
                            'fecha': d_str,
                            'tecnologia': tech['title'],
                            'mwh': f"{tech['val']:.2f}",
                            'porcentaje': f"{pct:.2f}",
                            'total_mwh': f"{stats['total_gen']:.2f}",
                            'porcentaje_renovable': f"{stats['ren_pct']:.2f}"
                        })
                    successfully_recovered.append(d_str)  # YYYY-MM-DD
                except REEZeroDataError:
                    pass
                except REEIncompleteDataError as e:
                    print(f"Advertencia: {e}", file=sys.stderr)
                    pass
        except REEApiError:
            pass

    if successfully_recovered:
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        all_rows.sort(key=lambda x: (x.get('fecha', ''), x.get('tecnologia', '')))
        with open(csv_path, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator='\n')
            writer.writeheader()
            writer.writerows(all_rows)

    return successfully_recovered