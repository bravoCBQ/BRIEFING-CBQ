import pdfplumber
import fitz  # PyMuPDF
import re
import json
import os

class HighPrecisionPDFExtractor:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.summary = {
            'vuelo': 'N/A',
            'matricula': 'N/A',
            'tiempo_vuelo': 'N/A',
            'viento_arribo': '000/00',
            'pista_uso': 'N/A',
            'limitacion_peso': 'N/A',
            'limitacion_valor': '0',
            'limitacion_margen': '0',
            'limitacion_critica': False,
            'tripulacion': [],
            'turbulencia_max': '00',
            'turbulencia_loc': 'N/A',
            'turbulencias_severas': [],
            'turbulencias_repetidas': {},
            'mel_items': [],
            'meteorologia': [],
            'notams_criticos': []
        }
        self._extract_all()

    def _extract_all(self):
        try:
            with pdfplumber.open(self.pdf_path) as pdf:
                full_text = ""
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    full_text += f"\n--- PAGE {i+1} ---\n{text}"
                    
                    if i == 0:
                        self._extract_crew(text)
                    
                    # Page 13 usually has the clean flight summary line
                    if i == 12: 
                        self._extract_flight_summary_line(text)
                    
                    if "DEFERRED ITEM LIST" in text or "Operational Limitations Report" in text:
                        self._extract_mel_advanced(text)
                
                self.summary['notams_criticos'] = []
                self._extract_basic_info_fallback(full_text)
                self._extract_turbulence(full_text)
                self._extract_weights_advanced(full_text)
                self._extract_met_advanced(full_text)
                self._extract_notams_advanced(full_text)
                
        except Exception as e:
            print(f"Error extracting PDF data: {e}")

    def _extract_flight_summary_line(self, text):
        # Sample: LAN809 02FEB26 CCBGE LA789 SCEL 0425 YSSY 1915
        match = re.search(r'([A-Z]{3}\d{3,4})\s+\d{2}[A-Z]{3}\d{2}\s+([A-Z]{2}[A-Z]{3})', text)
        if match:
            self.summary['vuelo'] = match.group(1)
            reg = match.group(2)
            if '-' not in reg and len(reg) == 5:
                reg = f"{reg[:2]}-{reg[2:]}"
            self.summary['matricula'] = reg

    def _extract_basic_info_fallback(self, text):
        if self.summary['vuelo'] == 'N/A':
            match = re.search(r'Flight\s+([A-Z0-9-]+)', text)
            if match: self.summary['vuelo'] = match.group(1)
        
        if self.summary['matricula'] == 'N/A':
            match = re.search(r'Acft\.\s+Regist\s+([A-Z0-9-]+)', text)
            if match: self.summary['matricula'] = match.group(1)

        # Total flight time from LATAM FLIGHT RELEASE section
        # Sample: DEST YSSY 82909 1351 (1351 is time)
        time_match = re.search(r'DEST\s+[A-Z]{4}\s+\d+\s+(\d{2})(\d{2})', text)
        if time_match:
            hh, mm = time_match.group(1), time_match.group(2)
            self.summary['tiempo_vuelo'] = f"{hh}h {mm}m"

        # Arrival Wind and Runway from Navigation Summary / Nav Log
        # Sample: ... RIVET DCT YSSYR16L ... AVG WIND 248/029
        # Destination YSSY is standard for this user based on log
        
        # 1. Runway: Look for YSSYR[Number][LRC]
        rwy_match = re.search(r'YSSYR(\d{2}[LRC])', text)
        if rwy_match:
            self.summary['pista_uso'] = rwy_match.group(1)
        
        # 2. Wind: Look for YSSY METAR/TAF wind specifically
        # Pattern: YSSY -SYD - SYDNEY K.SMITH.\nSA 020100Z 19023KT
        wind_match = re.search(r'YSSY\s+-SYD\s+-.*?\nSA\s+\d{6}Z\s+([A-Z0-9]{5})KT', text, re.DOTALL)
        if wind_match:
            wind_raw = wind_match.group(1)
            self.summary['viento_arribo'] = f"{wind_raw[:3]}/{wind_raw[3:]}"
        else:
            # Fallback to TAF if METAR SA is missing
            taf_wind = re.search(r'YSSY\s+-SYD\s+-.*?\nFT\s+\d{6}Z\s+\d{4}\/\d{4}\s+([A-Z0-9]{5})KT', text, re.DOTALL)
            if taf_wind:
                wind_raw = taf_wind.group(1)
                self.summary['viento_arribo'] = f"{wind_raw[:3]}/{wind_raw[3:]}"

    def _extract_crew(self, text):
        # Improved crew extraction to handle Cockpit Crew specifically first
        # We search specifically for CMD, CP, FO positions
        cockpit_match = re.search(r'Cockpit Crew(.*?)(?:Cabin Crew|$)', text, re.DOTALL)
        if cockpit_match:
            lines = cockpit_match.group(1).split('\n')
            for line in lines:
                # CMD CLAUDIO MARCELO BRAVO QUEZADA 00002726
                # CP CRISTIAN MELO DASTRES 01338177
                match = re.search(r'^\s*([A-Z]{2,3})\s+(.*?)\s+\d{8}', line)
                if match:
                    pos = match.group(1)
                    name = match.group(2).strip()
                    self.summary['tripulacion'].append(f"{pos}: {name}")

    def _extract_mel_advanced(self, text):
        # Ultra-robust MEL parser
        # Capture all possible variations of MEL headers
        sections = re.split(r'(\d{2}-\d{2}-\d{2})\s+MEL\s+([A-D])\s*', text)
        
        if len(sections) > 1:
            for i in range(1, len(sections), 3):
                num = sections[i]
                lvl = sections[i+1]
                content = sections[i+2]
                
                # Take up to 6 lines to ensure we don't miss anything
                content_lines = content.split('\n')[:6]
                raw_full_text = " ".join([l.strip() for l in content_lines]).strip()
                
                # Heuristic cleanup: remove common PDF noise but keep potential description words
                # Remove dates accurately
                full_mel_text = re.sub(r'\d{2}/\d{2}/\d{1,4}', '', raw_full_text)
                
                # Remove PAGE/LATAM/RELEASE/MOC but don't strip everything
                noise_patterns = [
                    r'MOC\s*N?º?\s*\d+',
                    r'PAGE\s+\d+',
                    r'LATAM\s+OPERATIONAL.*?',
                    r'MAINTENANCE\s+PROCEDURES.*?',
                    r'CREW\s+PROCEDURE.*?',
                    r'--+',
                    r'BAR\s+CODE.*?',
                    r'A/C\s+Registration.*?',
                    r'Defect\s+Found.*?',
                    r'Moc\s+No.*?',
                    r'Open\s+Description.*?',
                    r'Report.*?',
                    r'Repetetive.*?'
                ]
                for p in noise_patterns:
                    full_mel_text = re.sub(p, '', full_mel_text, flags=re.IGNORECASE)
                
                # Remove Registration patterns (usually 3 uppercase letters preceded by a number or space)
                # Sample: "9 BGE", "CC-BGE", "97 BGF"
                full_mel_text = re.sub(r'\b\d{1,3}\s+[A-Z]{3}\b', '', full_mel_text)
                full_mel_text = re.sub(r'\bCC-[A-Z]{3}\b', '', full_mel_text)
                
                full_mel_text = re.sub(r'\s+', ' ', full_mel_text).strip()
                
                # Separation heuristic: Defect vs Description
                # Try to find common status words like "INOP", "LIMIT", "RESTR", "FAIL"
                status_split = re.split(r'\b(INOP|LIMIT|RESTR|FAIL|REQUIRED|ACTION)\b', full_mel_text, 1, flags=re.IGNORECASE)
                
                if len(status_split) > 1:
                    defect = status_split[0].strip()
                    description = (status_split[1] + status_split[2]).strip()
                else:
                    # If no obvious split word, use first 4 words as defect
                    words = full_mel_text.split()
                    if len(words) > 4:
                        defect = " ".join(words[:4])
                        description = " ".join(words[4:])
                    else:
                        defect = full_mel_text
                        description = ""

                if not any(item['number'] == num for item in self.summary['mel_items']):
                    self.summary['mel_items'].append({
                        'number': num,
                        'level': lvl,
                        'defect': defect,
                        'description': description
                    })

    def _extract_notams_advanced(self, full_text):
        # High-impact operational NOTAMs only
        crit_patterns = [
            r'RWY.*?CLOSED',
            r'ILS.*?RWY.*?U/S',
            r'ILS.*?U/S',
            r'LOC.*?U/S',
            r'GP.*?U/S',
            r'CURFEW',
            r'NOT\s+AVBL\s+FOR\s+DEPARTURE',
            r'NORTH\s+END\s+CLOSED',
            r'SOUTH\s+END\s+CLOSED',
            r'SISTEMAS\s+INOP'
        ]

        lines = full_text.split('\n')
        found_notams = []
        current_apt = "UNKNOWN"

        for i in range(len(lines)):
            line = lines[i].strip()
            l_up = line.upper()
            
            # Detect airport header (e.g., "SCEL -SCL - SANTIAGO INTL")
            apt_match = re.match(r'^([A-Z]{4})\s+-\s*([A-Z]{3})?\s*-', l_up)
            if apt_match:
                current_apt = apt_match.group(1)

            if any(re.search(p, l_up) for p in crit_patterns):
                # Capture just the matching line and the one after for concise context
                context = lines[i:min(len(lines), i+2)]
                notam_text = " ".join([c.strip() for c in context]).strip()
                notam_text = re.sub(r'\s+', ' ', notam_text)
                
                # Deduplicate and filter out obvious noisy strings
                if notam_text and len(notam_text) > 10:
                    # Final check: skip if it's just about TWY or secondary lights unless it mentions RWY CLOSED
                    if 'TWY' in notam_text.upper() and 'RWY' not in notam_text.upper() and 'CLOSED' not in notam_text.upper():
                        continue
                    
                    # Prefix with current airport
                    full_entry = f"{current_apt}: {notam_text}"
                    if full_entry not in found_notams:
                        found_notams.append(full_entry)

        self.summary['notams_criticos'] = found_notams

    def _extract_turbulence(self, full_text):
        # Anchor-based Navigation Log Parser
        lines = full_text.split('\n')
        max_turb = 0
        max_loc = "N/A"
        max_time = "N/A"
        repeated = {} 
        
        last_posn = "N/A"
        
        for i in range(len(lines)):
            line = lines[i].strip()
            if not line: continue
            
            # Position identification: Starts with word (not coordinate)
            posn_match = re.match(r'^([A-Z0-9]{3,7})\b', line)
            # Avoid coordinate-like start and headers
            if posn_match and not re.match(r'^[SN]\d{4}', line) and \
               not any(x in line for x in ["PAGE", "LATAM", "RELEASE", "FREQ", "COORD", "POSN", "POS"]):
                last_posn = posn_match.group(1)
            
            # Data line starts with coordinate
            if re.match(r'^[SN]\d{4}', line):
                wind_match = re.search(r'\b(\d{3}/\d{3})\b', line)
                if wind_match:
                    parts = line.split()
                    try:
                        # Find wind index
                        wind_idx = -1
                        for idx, p in enumerate(parts):
                            if p == wind_match.group(1):
                                wind_idx = idx
                                break
                        
                        if wind_idx != -1 and len(parts) > wind_idx + 1:
                            wsr_str = parts[wind_idx + 1]
                            if wsr_str.isdigit():
                                wsr = int(wsr_str)
                                
                                # ACT (Time) is 3 positions after WSR (DTGO, ACBOF, ACT)
                                time_val = "N/A"
                                if len(parts) > wind_idx + 4:
                                    act = parts[wind_idx + 4]
                                    if len(act) == 4 and act.isdigit():
                                        time_val = f"{act[:2]}:{act[2:]}"
                                
                                if wsr > max_turb:
                                    max_turb = wsr
                                    max_loc = last_posn
                                    max_time = time_val
                                
                                # Report all turbulences above 06 as requested
                                if wsr >= 6:
                                    t_str = str(wsr)
                                    if t_str not in repeated:
                                        repeated[t_str] = []
                                    entry = {
                                        'grado': wsr,
                                        'punto': last_posn,
                                        'eet': time_val
                                    }
                                    if not any(e['punto'] == last_posn and e['grado'] == wsr for e in repeated[t_str]):
                                        repeated[t_str].append(entry)
                    except (ValueError, IndexError):
                        continue

        self.summary['turbulencia_max'] = f"{max_turb:02d}"
        self.summary['turbulencia_loc'] = f"{max_loc} ({max_time})"
        self.summary['turbulencias_repetidas'] = repeated

    def _extract_weights_advanced(self, full_text):
        weights_found = []
        patterns = {
            'ZFW': (r'EZFW\s+(\d+)', r'MZFW\s+(\d+)'),
            'TOW': (r'ETOW\s+(\d+)', r'MTOW\s+(\d+)'),
            'LDW': (r'ELDW\s+(\d+)', r'MLDW\s+(\d+)')
        }
        for key, (est_p, max_p) in patterns.items():
            est_m = re.search(est_p, full_text)
            max_m = re.search(max_p, full_text)
            if est_m and max_m:
                est_val = int(est_m.group(1))
                max_val = int(max_m.group(1))
                margin = max_val - est_val
                weights_found.append({'type': key, 'est': est_val, 'max': max_val, 'margin': margin})
        
        if weights_found:
            weights_found.sort(key=lambda x: x['margin'])
            critical = weights_found[0]
            self.summary['limitacion_peso'] = critical['type']
            self.summary['limitacion_valor'] = f"{critical['est']} / {critical['max']}"
            self.summary['limitacion_margen'] = critical['margin']
            self.summary['limitacion_critica'] = critical['margin'] < 1000

    def _extract_met_advanced(self, full_text):
        sections = re.findall(r'([A-Z]{4})\s+-\s+.*?(?=([A-Z]{4}\s+-\s+|$))', full_text, re.DOTALL)
        seen_airports = set()
        for apt, next_lookahead in sections:
            if apt in seen_airports or len(apt) != 4: continue
            pattern = re.escape(apt) + r'\s+-.*?SA\s+\d{6}Z\s+(.*?)(?=[A-Z]{4}\s+-\s+|$)'
            sa_match = re.search(pattern, full_text, re.DOTALL)
            if sa_match:
                metar_text = sa_match.group(1)
                vis_match = re.search(r'\b(\d{4}|CAVOK)\b', metar_text)
                if vis_match:
                    vis = vis_match.group(1)
                    vis_val = 9999 if vis == 'CAVOK' else int(vis)
                    self.summary['meteorologia'].append({'airport': apt, 'visibility': vis_val, 'low_vis': vis_val < 2000})
                    seen_airports.add(apt)


    def get_flight_summary(self):
        return self.summary

if __name__ == "__main__":
    # Test
    extractor = HighPrecisionPDFExtractor("muestra.pdf")
    print(json.dumps(extractor.get_flight_summary(), indent=4))
