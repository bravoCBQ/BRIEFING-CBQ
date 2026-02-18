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
            'meteorologia': []
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
                    
                    if "DEFERRED ITEM LIST" in text:
                        self._extract_mel_advanced(text)
                
                self._extract_basic_info_fallback(full_text)
                self._extract_turbulence(full_text)
                self._extract_weights_advanced(full_text)
                self._extract_met_advanced(full_text)
                
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
        # Re-evaluating MEL extraction from PÁGINA 3 format
        # Sample: 33-41-01 MEL C L WING LIGHT INOP.
        items = re.findall(r'(\d{2}-\d{2}-\d{2})\s+MEL\s+([A-D])\s+(.*?)(?=\s+\d{2}/\d{2}|PROCEDURE|$)', text)
        for num, lvl, desc in items:
            self.summary['mel_items'].append({
                'number': num,
                'level': lvl,
                'description': desc.strip()
            })

    def _extract_turbulence(self, full_text):
        # Look for the Nav Log section
        # Format: [WAYPOINT] [NUM] [NUM]
        # We also want to exclude "PAGE", "SIGMET", "creation", "UTC"
        exclude = ["PAGE", "SIGMET", "UTC", "TIME", "FILE", "DATE"]
        lines = full_text.split('\n')
        max_turb = 0
        max_loc = "N/A"
        repeated = {}

        for line in lines:
            # Look for waypoint name (4-5 letters) followed by turbulence (1-2 digits) and Flight Level (3 digits)
            match = re.search(r'\b([A-Z0-9]{4,5})\b\s+(\d{1,2})\b\s+(\d{3})\b', line)
            if match:
                wpt = match.group(1)
                if any(x in wpt for x in exclude): continue
                
                turb = int(match.group(2))
                if turb > max_turb:
                    max_turb = turb
                    max_loc = wpt
                
                if turb >= 5:
                    t_str = str(turb)
                    if t_str not in repeated:
                        repeated[t_str] = []
                    if wpt not in repeated[t_str]:
                        repeated[t_str].append(wpt)

        self.summary['turbulencia_max'] = f"{max_turb:02d}"
        self.summary['turbulencia_loc'] = max_loc
        self.summary['turbulencias_repetidas'] = {k: v for k, v in repeated.items() if len(v) > 1}

    def _extract_weights_advanced(self, full_text):
        # Extract pairs of (Estimated, Maximum)
        # Sample: EZFW 157867 ... MZFW 181436
        # Sample: ETOW 252650 ... MTOW 252650
        # Sample: ELDW 169741 ... MLDW 192776
        
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
                weights_found.append({
                    'type': key,
                    'est': est_val,
                    'max': max_val,
                    'margin': margin
                })
        
        if weights_found:
            # Sort by margin (ascending) to find the most restrictive
            weights_found.sort(key=lambda x: x['margin'])
            critical = weights_found[0]
            
            self.summary['limitacion_peso'] = critical['type']
            self.summary['limitacion_valor'] = f"{critical['est']} / {critical['max']}"
            self.summary['limitacion_margen'] = critical['margin']
            self.summary['limitacion_critica'] = critical['margin'] < 1000

    def _extract_met_advanced(self, full_text):
        # METARs
        # Pattern: SCEL -SCL - SANTIAGO INTL
        # followed by SA 020100Z ...
        # Simplified: Find [ICAO] -[ANY] and then SA [TIME]
        sections = re.findall(r'([A-Z]{4})\s+-\s+.*?(?=([A-Z]{4}\s+-\s+|$))', full_text, re.DOTALL)
        
        seen_airports = set()
        for apt, next_lookahead in sections:
            if apt in seen_airports or len(apt) != 4: continue
            
            # Find the block belonging to this apt
            # We search for SA after the apt name until the next apt or EOF
            pattern = re.escape(apt) + r'\s+-.*?SA\s+\d{6}Z\s+(.*?)(?=[A-Z]{4}\s+-\s+|$)'
            sa_match = re.search(pattern, full_text, re.DOTALL)
            
            if sa_match:
                metar_text = sa_match.group(1)
                # Extract visibility: 9999, 4000, 0800, CAVOK, 1/4SM
                vis_match = re.search(r'\b(\d{4}|CAVOK)\b', metar_text)
                if vis_match:
                    vis = vis_match.group(1)
                    vis_val = 9999 if vis == 'CAVOK' else int(vis)
                    self.summary['meteorologia'].append({
                        'airport': apt,
                        'visibility': vis_val,
                        'low_vis': vis_val < 2000
                    })
                    seen_airports.add(apt)


    def get_flight_summary(self):
        return self.summary

if __name__ == "__main__":
    # Test
    extractor = HighPrecisionPDFExtractor("muestra.pdf")
    print(json.dumps(extractor.get_flight_summary(), indent=4))
