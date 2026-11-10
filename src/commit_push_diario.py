#!/usr/bin/env python3
"""
Script de commit y push diario a las 08:30.
- Verifica claves en archivos (patrones: nvapi-, sk-or-, AIza, ghp_, github_pat_)
- Si hay claves: no sube nada y avisa
- Si no hay claves: git add data/ graficas/ && git commit -m "Actualización diaria YYYY-MM-DD" && git push
Solo actúa si hay cambios.
"""
import os
import sys
import subprocess
import re
from datetime import date

BASE_DIR = '/home/agentes/proyectos/ree'
REPO_DIR = BASE_DIR

# Patrones de claves
SECRET_PATTERNS = [
    r'nvapi-[a-zA-Z0-9_-]+',
    r'sk-or-[a-zA-Z0-9_-]+',
    r'AIza[a-zA-Z0-9_-]+',
    r'ghp_[a-zA-Z0-9_-]+',
    r'github_pat_[a-zA-Z0-9_-]+',
]

def check_secrets():
    """Busca patrones de claves en archivos del repo"""
    # Archivos a revisar (data/, graficas/, etc.)
    for root, dirs, files in os.walk(REPO_DIR):
        # Saltar .git
        if '.git' in dirs:
            dirs.remove('.git')
        for f in files:
            filepath = os.path.join(root, f)
            # Solo archivos de texto
            if f.endswith(('.csv', '.json', '.md', '.txt', '.py', '.yml', '.yaml')):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    for pattern in SECRET_PATTERNS:
                        if re.search(pattern, content):
                            return True, f"Patrón '{pattern}' encontrado en {filepath}"
                except Exception:
                    pass
    return False, ""

def has_changes():
    """Verifica si hay cambios en data/ o graficas/"""
    result = subprocess.run(
        ['git', 'status', '--porcelain', 'data/', 'graficas/'],
        cwd=REPO_DIR, capture_output=True, text=True
    )
    return len(result.stdout.strip()) > 0

def main():
    # 1. Verificar claves
    has_secret, msg = check_secrets()
    if has_secret:
        print(f"❌ SECRETO DETECTADO: {msg}")
        print("Commit y push cancelados por seguridad.")
        sys.exit(1)
    
    # 2. Verificar si hay cambios
    if not has_changes():
        print("No hay cambios en data/ ni graficas/. Nada que hacer.")
        return
    
    # 3. Commit y push
    date_str = date.today().strftime('%Y-%m-%d')
    commit_msg = f"Actualización diaria {date_str}"
    
    try:
        subprocess.run(['git', 'add', 'data/', 'graficas/'], cwd=REPO_DIR, check=True)
        subprocess.run(['git', 'commit', '-m', commit_msg], cwd=REPO_DIR, check=True)
        subprocess.run(['git', 'push'], cwd=REPO_DIR, check=True)
        print(f"✅ Commit y push realizados: {commit_msg}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error en git: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()