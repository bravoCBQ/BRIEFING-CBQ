import pdfplumber
import os
import json
import pandas as pd
import re
from datetime import datetime

class HighPrecisionPDFExtractor:
    def __init__(self, file_path):
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"El archivo {file_path} no existe.")
        self.file_path = file_path
        self.filename = os.path.basename(file_path)

    def extract_text_as_is(self):
        """Extrae el texto intentando mantener la estructura visual exacta."""
        extracted_data = []
        with pdfplumber.open(self.file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                # Usamos layout=True para mantener la posición visual del texto
                text = page.extract_text(layout=True)
                extracted_data.append({
                    "page": i + 1,
                    "content": text
                })
        return extracted_data

    def extract_tables(self):
        """Extrae tablas de forma estructurada."""
        all_tables = []
        with pdfplumber.open(self.file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                for j, table in enumerate(tables):
                    if not table or not table[0]: continue
                    # Filtrar columnas None
                    headers = [h if h else f"Col_{idx}" for idx, h in enumerate(table[0])]
                    df = pd.DataFrame(table[1:], columns=headers)
                    all_tables.append({
                        "page": i + 1,
                        "table_index": j,
                        "data": df.to_dict(orient="records")
                    })
        return all_tables

    def get_flight_summary(self):
        """Genera un resumen del vuelo extrayendo datos clave."""
        text_data = self.extract_text_as_is()
        all_text = "\n".join([p['content'] for p in text_data])
        first_page_text = text_data[0]['content'] if text_data else ""
        
        summary = {
            "vuelo": "No encontrado",
            "matricula": "No encontrada",
            "tiempo_vuelo": "No calculado",
            "turbulencia_max": "N/A",
            "turbulencia_loc": "N/A",
            "viento_arribo": "N/A",
            "pista_uso": "N/A",
            "tripulacion": []
        }

        # 1. Extraer Número de Vuelo (Formato LAN-XXX o LANXXXX)
        flight_match = re.search(r"LAN-?(\d+)", first_page_text)
        if flight_match:
            summary["vuelo"] = f"LAN-{flight_match.group(1)}"

        # 2. Extraer Matrícula (Formato CC-XXX)
        reg_match = re.search(r"CC-[A-Z]{3}", first_page_text)
        if reg_match:
            summary["matricula"] = reg_match.group(0)

        # 3. Extraer Tiempo de Vuelo y ETA (Calculando diferencia entre Schedule UTC)
        # Ejemplo: Schedule UTC 04:25 19:15
        time_match = re.search(r"Schedule UTC\s+(\d{2}:\d{2})\s+(\d{2}:\d{2})", first_page_text)
        eta_str = ""
        if time_match:
            t1_str = time_match.group(1)
            t2_str = time_match.group(2)
            eta_str = t2_str
            fmt = "%H:%M"
            t1 = datetime.strptime(t1_str, fmt)
            t2 = datetime.strptime(t2_str, fmt)
            
            # Calcular diferencia
            delta = t2 - t1
            total_seconds = delta.total_seconds()
            if total_seconds < 0:
                total_seconds += 24 * 3600  # Manejar cruce de día
                
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            summary["tiempo_vuelo"] = f"{hours}h {minutes}m"

        # 4. Extraer Turbulencia Máxima (MXWSR)
        # Buscamos MXWSR 04/5080W
        turb_match = re.search(r"MXWSR\s+(\d{2})/([A-Z0-9]+)", all_text)
        if turb_match:
            summary["turbulencia_max"] = turb_match.group(1)
            summary["turbulencia_loc"] = turb_match.group(2)

        # 5. Extraer Pista de Arribo
        # Buscamos el destino en la Navigation Summary o Log (ej: YSSY/16L)
        # Primero identificamos el destino (Route SCL SYD)
        dest_match = re.search(r"Route\s+[A-Z]{3}\s+([A-Z]{3})", first_page_text)
        dest_code = ""
        if dest_match:
            dest_code = dest_match.group(1)
            # Buscar ICAO del destino y la pista (ej: YSSY/16L)
            # En el Nav Log suele aparecer como YSSY/16L
            rwy_match = re.search(fr"Y[A-Z]{{3}}/(\d{{2}}[RCL]?)", all_text)
            if rwy_match:
                summary["pista_uso"] = rwy_match.group(1)

        # 6. Extraer Viento de Arribo (TAF)
        if dest_code and eta_str:
            # Intentar encontrar el ICAO completo (ej: YSSY)
            icao_match = re.search(fr"([A-Z]{4})\s+-\s+[A-Z]{3}\s+-\s+{dest_code}?", all_text)
            icao = ""
            if icao_match:
                icao = icao_match.group(1)
            else:
                if dest_code == "SYD": icao = "YSSY"
                elif dest_code == "SCL": icao = "SCEL"
                elif dest_code == "MEL": icao = "YMML"
                elif dest_code == "IPC": icao = "SCIP"
            
            if icao:
                taf_match = re.search(fr"{icao}.*?\n\s+(?:FT|TAF).*?\n(.*?)(?=\n\s+[A-Z]{{4}}|\n\n|$)", all_text, re.DOTALL)
                if not taf_match:
                    taf_match = re.search(fr"{icao}.*?\n\s+(?:FT|TAF)\s+.*?\n(.*?)(?==|$)", all_text, re.DOTALL)
                
                if taf_match:
                    taf_content = taf_match.group(1)
                    winds = re.findall(r"(\d{3})(\d{2,3})(?:G\d{2})?KT", taf_content)
                    if winds:
                        last_wind = winds[-1]
                        summary["viento_arribo"] = f"{last_wind[0]}{last_wind[1]}KT"

        # 7. Lógica Avanzada de Turbulencia (Nav Log Parsing)
        # Extraer EET (ACT) y WSR (Turbulencia) de cada waypoint
        coord_pattern = r"([SN]\d{4}\.\d\s+[WE]\d{5}\.\d)\s+(\d{3})\s+(\w{3})\s+(\d{3})\s+(\d{3}/\d{3})\s+(\d{2})\s+(\d{4,})\s+(\d{4,})\s+(\d{4})"
        matches = list(re.finditer(coord_pattern, all_text))
        
        all_turbulences = []
        waypoint_eets = {} # Para mapear waypoint -> EET
        
        for m in matches:
            wsr = int(m.group(6))
            act = m.group(9)
            eta_eet = f"{act[:2]}:{act[2:]}"
            
            # Buscar nombre del waypoint (retroceder líneas hasta encontrarlo)
            start_idx = m.start()
            preceding_text = all_text[:start_idx]
            prev_lines = [l.strip() for l in preceding_text.splitlines() if l.strip()]
            
            wp_name = "UNKNOWN"
            if prev_lines:
                # El nombre suele estar en la línea inmediatamente superior o una más arriba
                # Intentamos buscar el primer token alfanumérico largo
                for i in range(1, min(4, len(prev_lines) + 1)):
                    potential_wp = re.search(r"^([A-Z0-9/\-]+)", prev_lines[-i])
                    if potential_wp:
                        wp_name = potential_wp.group(1)
                        if wp_name not in ["NAVIGATION", "LATAM", "POSN", "COORD"]: # Filtrar encabezados
                            break
            
            waypoint_eets[wp_name] = eta_eet
            if wsr > 0:
                all_turbulences.append({
                    "grado": wsr,
                    "punto": wp_name,
                    "eet": eta_eet
                })

        # Determinar la Turbulencia Máxima Absoluta
        max_wsr_val = -1
        max_wsr_loc = "N/A"
        
        # 1. Considerar MXWSR del resumen
        mxwsr_match = re.search(r"MXWSR\s+(\d{2})/([A-Z0-9]+)", all_text)
        if mxwsr_match:
            max_wsr_val = int(mxwsr_match.group(1))
            mx_punto = mxwsr_match.group(2)
            mx_eet = waypoint_eets.get(mx_punto, "N/A")
            max_wsr_loc = f"{mx_punto} ({mx_eet})"

        # 2. Comparar con todos los puntos del log
        if all_turbulences:
            sorted_turb = sorted(all_turbulences, key=lambda x: x['grado'], reverse=True)
            log_max = sorted_turb[0]
            if log_max['grado'] > max_wsr_val:
                max_wsr_val = log_max['grado']
                max_wsr_loc = f"{log_max['punto']} ({log_max['eet']})"
        
        if max_wsr_val != -1:
            summary["turbulencia_max"] = f"{max_wsr_val:02}"
            summary["turbulencia_loc"] = max_wsr_loc

        # Turbulencias > 5 (Severas)
        summary["turbulencias_severas"] = [t for t in all_turbulences if t['grado'] > 5]
        
        # Repeticiones > 4
        degree_counts = {}
        for t in all_turbulences:
            if t['grado'] > 4:
                degree_counts[t['grado']] = degree_counts.get(t['grado'], []) + [t]
        
        summary["turbulencias_repetidas"] = {deg: pts for deg, pts in degree_counts.items() if len(pts) >= 2}

        # 8. Extraer Pesos y Limitaciones (MZFW, MTOW, MLDW vs EZFW, ETOW, ELDW)
        # EZFW 157867 ... MZFW 181436
        # ETOW 252650 ... MTOW 252650
        # ELDW 169741 ... MLDW 192776
        weights = {
            "ZFW": re.search(r"EZFW\s+(\d+).*?MZFW\s+(\d+)", all_text),
            "TOW": re.search(r"ETOW\s+(\d+).*?MTOW\s+(\d+)", all_text),
            "LDW": re.search(r"ELDW\s+(\d+).*?MLDW\s+(\d+)", all_text)
        }
        
        limit_name = "N/A"
        limit_val = "N/A"
        limit_margin = float('inf')
        limit_critical = False

        for key, match in weights.items():
            if match:
                est = int(match.group(1))
                max_w = int(match.group(2))
                margin = max_w - est
                if margin < limit_margin:
                    limit_margin = margin
                    limit_name = key
                    limit_val = f"{est} / {max_w}"
                    limit_critical = margin < 1000
        
        summary["limitacion_peso"] = limit_name
        summary["limitacion_valor"] = limit_val
        summary["limitacion_margen"] = limit_margin if limit_margin != float('inf') else "N/A"
        summary["limitacion_critica"] = limit_critical

        # 8. Extraer Tripulación (Cockpit y Cabin Crew)
        lines = first_page_text.split("\n")
        in_crew_section = False
        for line in lines:
            if "Cockpit Crew" in line or "Cabin Crew" in line:
                in_crew_section = True
                continue
            
            if in_crew_section:
                if "POS" in line and "Name" in line:
                    continue
                if "Flight Info" in line or not line.strip():
                    if not line.strip(): continue
                    in_crew_section = False
                    continue
                
                match = re.search(r"(?:CMD|CP|FO|CCM|BCC|CC)\s+([A-Z\s]{10,})", line)
                if match:
                    name = match.group(1).strip()
                    name = re.sub(r"\s+\d+.*$", "", name).strip()
                    if name and name not in summary["tripulacion"]:
                        summary["tripulacion"].append(name)

        return summary

    def save_to_text(self, output_path):
        """Guarda la extracción visual en un archivo de texto."""
        data = self.extract_text_as_is()
        summary = self.get_flight_summary()
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("========================================\n")
            f.write("           RESUMEN DEL VUELO            \n")
            f.write("========================================\n")
            f.write(f"Vuelo: {summary['vuelo']}\n")
            f.write(f"Matrícula: {summary['matricula']}\n")
            f.write(f"Tiempo de Vuelo: {summary['tiempo_vuelo']}\n")
            f.write(f"Turbulencia Máxima: {summary['turbulencia_max']}\n")
            f.write(f"Ubicación Estimada: {summary['turbulencia_loc']}\n")
            f.write(f"Viento de Arribo: {summary['viento_arribo']}\n")
            f.write(f"Pista en Uso: {summary['pista_uso']}\n")
            f.write(f"Limitación Más Restrictiva: {summary['limitacion_peso']} ({summary['limitacion_valor']})\n")
            f.write(f"Margen: {summary['limitacion_margen']} kg {'(CRÍTICA)' if summary['limitacion_critica'] else ''}\n")
            f.write("Tripulación:\n")
            for person in summary['tripulacion']:
                f.write(f" - {person}\n")
            f.write("========================================\n\n")
            
            for page in data:
                f.write(f"--- PÁGINA {page['page']} ---\n")
                f.write(page['content'] if page['content'] else "[Página vacía o imagen]")
                f.write("\n\n")
        return output_path

    def save_to_json(self, output_path):
        """Guarda toda la información (texto y tablas) en un JSON."""
        summary = self.get_flight_summary()
        result = {
            "metadata": {
                "filename": self.filename,
                "pages": 0,
                "flight_summary": summary
            },
            "pages": self.extract_text_as_is(),
            "tables": self.extract_tables()
        }
        with pdfplumber.open(self.file_path) as pdf:
            result["metadata"]["pages"] = len(pdf.pages)
            
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=4)
        return output_path

if __name__ == "__main__":
    # Ejemplo de uso
    input_pdf = "muestra.pdf"
    if os.path.exists(input_pdf):
        extractor = HighPrecisionPDFExtractor(input_pdf)
        
        print(f"Procesando {input_pdf}...")
        
        # Generar Resumen en Consola
        summary = extractor.get_flight_summary()
        print("\n--- RESUMEN DETECTADO ---")
        print(f"Vuelo: {summary['vuelo']}")
        print(f"Matrícula: {summary['matricula']}")
        print(f"Tiempo de Vuelo: {summary['tiempo_vuelo']}")
        print(f"Tripulación ({len(summary['tripulacion'])} personas):")
        for p in summary['tripulacion']:
            print(f"  - {p}")
        print("-------------------------\n")
        
        # Guardar como texto plano estructurado
        txt_output = "resultado_extraccion.txt"
        extractor.save_to_text(txt_output)
        print(f"Texto extraído y resumen guardados en: {txt_output}")
        
        # Guardar como JSON para análisis de datos
        json_output = "resultado_analisis.json"
        extractor.save_to_json(json_output)
        print(f"Datos estructurados guardados en: {json_output}")
    else:
        print("No se encontró el archivo 'muestra.pdf' en el directorio.")
