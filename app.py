import streamlit as st
import pdfplumber
import pandas as pd
import os
import tempfile
from pdf_extractor import HighPrecisionPDFExtractor

# Configuración de página con estética "Premium"
st.set_page_config(
    page_title="PDF Flight Extractor Pro",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilo CSS personalizado para el efecto "WOW" y optimización móvil
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap');
    
    .stApp {
        background: linear-gradient(135deg, #eef2f3 0%, #8e9eab 100%);
        font-family: 'Inter', sans-serif;
    }
    .metric-card {
        background-color: white;
        padding: 15px;
        border-radius: 12px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        text-align: center;
        border-left: 5px solid #007bff;
        margin-bottom: 10px;
    }
    .crew-badge {
        display: inline-block;
        padding: 6px 14px;
        margin: 4px;
        background-color: #007bff;
        color: white;
        border-radius: 20px;
        font-size: 0.85em;
        font-weight: 600;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    }
    .mel-item {
        background-color: #f8f9fa;
        padding: 10px;
        border-radius: 8px;
        margin-bottom: 8px;
        border-left: 4px solid #6c757d;
    }
    .met-badge {
        display: inline-block;
        padding: 5px 12px;
        border-radius: 15px;
        margin: 3px;
        font-weight: 700;
        color: white;
    }
    .low-vis {
        background-color: #dc3545;
        animation: pulse 2s infinite;
    }
    .normal-vis {
        background-color: #28a745;
    }
    @keyframes pulse {
        0% { opacity: 1; }
        50% { opacity: 0.7; }
        100% { opacity: 1; }
    }
    /* Optimización para móviles */
    @media (max-width: 640px) {
        .metric-card h2 {
            font-size: 1.2rem !important;
        }
        .stTabs [data-baseweb="tab"] {
            padding-left: 10px;
            padding-right: 10px;
            font-size: 0.8rem;
        }
    }
    </style>
""", unsafe_allow_html=True)

def main():
    st.sidebar.image("https://img.icons8.com/clouds/200/airplane-take-off.png", width=120)
    st.sidebar.title("Flight Extractor Pro")
    st.sidebar.markdown("### 📱 Acceso Móvil")
    st.sidebar.info("Para usar en tu celular, conéctalo al mismo Wi-Fi y usa la URL de red que aparece en la terminal.")

    st.title("✈️ PDF Flight Extractor Pro")
    st.markdown("---")

    uploaded_file = st.file_uploader("Sube tu archivo PDF de vuelo", type="pdf")

    if uploaded_file is not None:
        # Botón central para extraer información
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚀 EXTRAER TODA LA INFORMACIÓN", use_container_width=True, type="primary"):
            with st.spinner("Procesando con alta precisión..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_path = tmp_file.name

                try:
                    extractor = HighPrecisionPDFExtractor(tmp_path)
                    summary = extractor.get_flight_summary()
                    
                    # --- RESULTADOS AUTOMÁTICOS ---
                    st.success("✅ Extracción Completada")
                    
                    # Fila 1: Datos Principales
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.markdown(f'<div class="metric-card"><p style="color: #666; font-size: 0.8em; margin: 0;">VUELO</p><h2 style="margin: 0; color: #007bff;">{summary["vuelo"]}</h2></div>', unsafe_allow_html=True)
                    with col2:
                        st.markdown(f'<div class="metric-card"><p style="color: #666; font-size: 0.8em; margin: 0;">MATRÍCULA</p><h2 style="margin: 0; color: #007bff;">{summary["matricula"]}</h2></div>', unsafe_allow_html=True)
                    with col3:
                        st.markdown(f'<div class="metric-card"><p style="color: #666; font-size: 0.8em; margin: 0;">DURACIÓN</p><h2 style="margin: 0; color: #007bff;">{summary["tiempo_vuelo"]}</h2></div>', unsafe_allow_html=True)

                    # Fila 2: Meteorología y Operación
                    st.markdown("<br>", unsafe_allow_html=True)
                    col4, col5, col6, col7 = st.columns(4)
                    
                    # Extraer datos de turbulencia de forma segura
                    t_max = summary.get("turbulencia_max", "N/A")
                    t_loc = summary.get("turbulencia_loc", "No detectada")
                    t_sev = summary.get("turbulencias_severas", [])
                    t_rep = summary.get("turbulencias_repetidas", {})
                    
                    # Card 1: Turbulencia Máxima (Fondo Blanco, Borde Amarillo)
                    max_turb_html = f'<div class="metric-card" style="border-left-color: #ffc107; text-align: left; min-height: 120px;">'
                    max_turb_html += f'<p style="color: #666; font-size: 0.85em; margin: 0; font-weight: 700;">TURBULENCIA MÁXIMA</p>'
                    max_turb_html += f'<h2 style="margin: 5px 0; color: #ffc107; font-size: 2.2em; font-weight: 800;">{t_max}</h2>'
                    max_turb_html += f'<p style="margin: 0; font-size: 1.0em; color: #666; font-weight: 600;">{t_loc}</p>'
                    max_turb_html += '</div>'
                    
                    # Card 2: Otras Turbulencias (Fondo Blanco, Borde Naranja)
                    extra_html = f'<div class="metric-card" style="border-left-color: #fd7e14; text-align: left; min-height: 120px;">'
                    extra_html += '<p style="color: #666; font-size: 0.85em; margin: 0; font-weight: 700;">OTRAS TURBULENCIAS</p>'
                    
                    extra_points = []
                    # Limpiar comparación: extraer nombre y asegurar grado como entero
                    max_wp_name = t_loc.split(" (")[0] if " (" in t_loc else t_loc
                    try:
                        max_grade_int = int(t_max)
                    except ValueError: # Catch specific error for int conversion
                        max_grade_int = -1 # Default to a value that won't match
                    
                    seen = {f"{max_wp_name}_{max_grade_int}"}
                    
                    for t in t_sev:
                        key = f"{t['punto']}_{t['grado']}"
                        if key not in seen:
                            extra_points.append(t)
                            seen.add(key)
                    
                    for deg, pts in t_rep.items():
                        for p in pts:
                            key = f"{p['punto']}_{p['grado']}"
                            if key not in seen:
                                extra_points.append(p)
                                seen.add(key)
                    
                    if extra_points:
                        for p in extra_points:
                            extra_html += f'<div style="margin-top: 8px; border-top: 1px solid #eee; padding-top: 5px;">'
                            extra_html += f'<h2 style="margin: 0; display: inline; color: #fd7e14; font-size: 1.6em; font-weight: 800;">{p["grado"]:02}</h2>'
                            extra_html += f'<span style="font-size: 1.0em; color: #666; margin-left: 5px; font-weight: 600;">{p["punto"]} ({p["eet"]})</span>'
                            extra_html += '</div>'
                    else:
                        extra_html += '<p style="margin: 15px 0; font-size: 0.9em; color: #28a745; font-weight: 600;">No se detectaron más variaciones.</p>'
                    
                    extra_html += '</div>'

                    with col4:
                        st.markdown(max_turb_html, unsafe_allow_html=True)
                    with col5:
                        st.markdown(extra_html, unsafe_allow_html=True)
                    with col6:
                        st.markdown(f'<div class="metric-card" style="border-left-color: #28a745;"><p style="color: #666; font-size: 0.8em; margin: 0;">VIENTO ARR</p><h2 style="margin: 0; color: #28a745;">{summary["viento_arribo"]}</h2></div>', unsafe_allow_html=True)
                    with col7:
                        st.markdown(f'<div class="metric-card" style="border-left-color: #17a2b8;"><p style="color: #666; font-size: 0.8em; margin: 0;">PISTA USO</p><h2 style="margin: 0; color: #17a2b8;">{summary["pista_uso"]}</h2></div>', unsafe_allow_html=True)

                    # Fila 3: Limitaciones de Peso
                    st.markdown("<br>", unsafe_allow_html=True)
                    limit_color = "#dc3545" if summary["limitacion_critica"] else "#6c757d"
                    st.markdown(f"""
                        <div class="metric-card" style="border-left: 5px solid {limit_color}; text-align: left; padding-left: 20px;">
                            <p style="color: #666; font-size: 0.8em; margin: 0;">LIMITACIÓN MÁS RESTRICTIVA</p>
                            <h3 style="margin: 5px 0; color: {limit_color};">{summary["limitacion_peso"]} ({summary["limitacion_valor"]})</h3>
                            <p style="margin: 0; font-weight: 700; color: {limit_color};">MARGEN: {summary["limitacion_margen"]} kg</p>
                        </div>
                    """, unsafe_allow_html=True)

                    # --- NUEVAS SECCIONES: MEL y MET ---
                    col_mel, col_met = st.columns(2)
                    
                    with col_mel:
                        st.subheader("🛠️ MEL Items")
                        if summary.get("mel_items"):
                            for item in summary["mel_items"]:
                                st.markdown(f"""
                                    <div class="mel-item">
                                        <b style="color: #007bff;">{item['number']} (Level {item['level']})</b><br>
                                        <span style="font-size: 0.9em; color: #444;">{item['description']}</span>
                                    </div>
                                """, unsafe_allow_html=True)
                        else:
                            st.info("No se detectaron MEL items diferidos.")

                    with col_met:
                        st.subheader("🌡️ Meteorología (Visibilidad)")
                        if summary.get("meteorologia"):
                            met_html = ""
                            for met in summary["meteorologia"]:
                                cls = "low-vis" if met['low_vis'] else "normal-vis"
                                vis_str = "CAVOK" if met['visibility'] >= 9999 else f"{met['visibility']}m"
                                met_html += f'<div class="met-badge {cls}">{met["airport"]}: {vis_str}</div>'
                            st.markdown(f'<div style="background: white; padding: 15px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.05);">{met_html}</div>', unsafe_allow_html=True)
                        else:
                            st.info("No se detectó información detallada de visibilidad en METARs.")

                    st.subheader("👥 Tripulación Detectada")
                    crew_html = "".join([f'<span class="crew-badge">{person}</span>' for person in summary['tripulacion']])
                    st.markdown(f'<div style="background: white; padding: 15px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.05);">{crew_html}</div>', unsafe_allow_html=True)

                    # ÁREA DE COPIADO RÁPIDO
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    # Preparar texto de turbulencias adicionales
                    extra_turb = ""
                    if summary.get("turbulencias_severas"):
                        extra_turb += "- ⚠️ SEVERAS (>05): " + ", ".join([f"{t['punto']} ({t['eet']})" for t in summary["turbulencias_severas"]]) + "\n"
                    if summary.get("turbulencias_repetidas"):
                        for deg, pts in summary["turbulencias_repetidas"].items():
                            extra_turb += f"- 🔄 REPETIDAS ({deg:02}): " + ", ".join([f"{t['punto']} ({t['eet']})" for t in pts]) + "\n"

                    # Preparar texto de MEL
                    mel_text = ""
                    if summary.get("mel_items"):
                        mel_text = "🛠️ MEL ITEMS:\n" + "\n".join([f"- {m['number']} ({m['level']}): {m['description']}" for m in summary['mel_items']]) + "\n\n"

                    # Preparar texto de Meteorología
                    met_text = ""
                    if summary.get("meteorologia"):
                        met_text = "🌡️ VISIBILIDAD:\n" + ", ".join([f"{m['airport']}: {m['visibility']}m" for m in summary['meteorologia']]) + "\n\n"

                    summary_text = (
                        f"✈️ RESUMEN DE VUELO\n--------------------\n"
                        f"Vuelo: {summary['vuelo']}\n"
                        f"Matrícula: {summary['matricula']}\n"
                        f"Tiempo: {summary['tiempo_vuelo']}\n\n"
                        f"{mel_text}"
                        f"{met_text}"
                        f"⚖️ LIMITACIONES DE PESO:\n"
                        f"- Limitación: {summary['limitacion_peso']} ({summary['limitacion_valor']})\n"
                        f"- Margen: {summary['limitacion_margen']} kg {'(CRÍTICA)' if summary['limitacion_critica'] else ''}\n\n"
                        f"🌦️ METEOROLOGÍA:\n"
                        f"- Turbulencia Máxima: {summary['turbulencia_max']} en {summary['turbulencia_loc']}\n"
                        f"{extra_turb}"
                        f"- Viento Arribo: {summary['viento_arribo']}\n\n"
                        f"🛫 OPERACIÓN:\n"
                        f"- Pista en Uso: {summary['pista_uso']}\n\n"
                        f"👥 TRIPULACIÓN:\n" + "\n".join([f"- {p}" for p in summary['tripulacion']])
                    )
                    st.text_area("📋 Resumen para copiar:", value=summary_text, height=400)

                except Exception as e:
                    st.error(f"Error: {e}")
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
    else:
        st.info("Selecciona un PDF de vuelo para extraer la información.")
        st.image("https://img.icons8.com/clouds/500/pdf.png", width=200)

if __name__ == "__main__":
    main()
