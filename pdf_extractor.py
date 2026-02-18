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

        # Better flight time extraction from Page 1 area
        # Schedule LT 01:25 06:15 -> Time Difference or Total
        # Usually it's in the Briefing summary area
        time_match = re.search(r'(\d{1,2}h\s+\d{1,2}m)', text)
        if time_match:
            self.summary['tiempo_vuelo'] = time_match.group(1)

    def _extract_crew(self, text):
        crew_lines = text.split('\n')
        recording = False
        for line in crew_lines:
            if "POS" in line and "Name" in line:
                recording = True
                continue
            if recording:
                if not line.strip() or "Cabin Crew" in line or "Flight Info" in line:
                    if "Cabin Crew" in line: continue
                    if "Flight Info" in line: break
                    continue
                
                # Match POS Name BP
                # CP CRISTIAN MELO DASTRES 01338177 14108348-1
                match = re.search(r'^\s*([A-Z]{2,3})\s+(.*?)\s+\d{8}', line)
                if match:
                    pos = match.group(1)
                    name = match.group(2).strip()
                    self.summary['tripulacion'].append(f"{pos}: {name}")

    def _extract_mel_advanced(self, text):
        # Sample: MOC N° 553449 L WING LIGHT INOP. T00XASQN
        # MEL C-33-41-01 LIMOPS: YES
        mocs = re.findall(r'MOC N°\s+(\d+)\s+(.*?)\s+T00', text)
        mels = re.findall(r'MEL\s+([A-D])-(\d{2}-\d{2}-\d{2})', text)
        
        for i in range(min(len(mocs), len(mels))):
            self.summary['mel_items'].append({
                'number': mels[i][1],
                'level': mels[i][0],
                'description': mocs[i][1].strip()
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
        # Look for more specific patterns for Weights
        # EZFW 157867 ...
        zfw_match = re.search(r'EZFW\s+(\d{6})', full_text)
        tow_match = re.search(r'ETOW\s+(\d{6})', full_text)
        if zfw_match:
            self.summary['limitacion_peso'] = 'EZFW'
            self.summary['limitacion_valor'] = zfw_match.group(1)
        elif tow_match:
            self.summary['limitacion_peso'] = 'ETOW'
            self.summary['limitacion_valor'] = tow_match.group(1)

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
