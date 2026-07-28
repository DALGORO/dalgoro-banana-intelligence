import os

# Carpetas y archivos que NO queremos incluir para no saturar la lectura
DIRECTORIOS_IGNORADOS = {'.venv', 'node_modules', '__pycache__', '.git', '.vscode', 'dist', 'build', 'alembic'}
ARCHIVOS_IGNORADOS = {'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock'}
# Extensiones que SÍ queremos revisar
EXTENSIONES_PERMITIDAS = {'.py', '.tsx', '.ts', '.json', '.sql', '.env.example'}

archivo_salida = "sistema_completo_para_revision.txt"

with open(archivo_salida, 'w', encoding='utf-8') as salida:
    for raiz, directorios, archivos in os.walk('.'):
        # Modificar la lista 'directorios' in-place para saltarnos las carpetas ignoradas
        directorios[:] = [d for d in directorios if d not in DIRECTORIOS_IGNORADOS]
        
        for archivo in archivos:
            if archivo in ARCHIVOS_IGNORADOS:
                continue
                
            _, extension = os.path.splitext(archivo)
            if extension in EXTENSIONES_PERMITIDAS:
                ruta_completa = os.path.join(raiz, archivo)
                
                # Escribir un encabezado claro para separar cada archivo
                salida.write(f"\n{'='*60}\n")
                salida.write(f"RUTA DEL ARCHIVO: {ruta_completa}\n")
                salida.write(f"{'='*60}\n\n")
                
                try:
                    with open(ruta_completa, 'r', encoding='utf-8') as f:
                        salida.write(f.read() + "\n")
                except Exception as e:
                    salida.write(f"[Error al leer este archivo: {e}]\n")

print(f"¡Listo! Se ha generado el archivo '{archivo_salida}'.")