"""
Generador de PDFs usando wkhtmltopdf.
Maneja la conversión de HTML a PDF con configuraciones específicas.
"""

from __future__ import annotations

import os
import re
import unicodedata
import pdfkit
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from src.data.sheets_reader import SheetsReader
from config.constants import Config, FilePaths
from config.paths import PathManager
from src.templates.template_manager import template_manager
from utils.helpers import setup_logging

logger = setup_logging(__name__)

class PDFGenerator:
    """Generador de PDFs con wkhtmltopdf"""
    
    def __init__(
        self,
        resources: Dict[str, str],
        output_dir: Optional[str] = None,
        pagos_df: Optional[pd.DataFrame] = None
    ):
        """
        Inicializa el generador de PDFs.
        
        Args:
            resources: Recursos necesarios (imágenes, fuentes, etc.)
            output_dir: Directorio de salida (opcional)
            pagos_df: DataFrame con pagos (pestaña 2 del Excel), opcional
        """
        self.resources = resources
        self.output_dir = Path(output_dir) if output_dir else PathManager.get_output_dir()
        self.pdf_config = self._setup_pdf_config()
        self.pagos_por_obra: Dict[str, List[Dict[str, Any]]] = self._build_pagos_index(pagos_df)
        
        # Asegurar que existe el directorio de salida
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"[OK] PDF Generator inicializado. Output: {self.output_dir}")
        if self.pagos_por_obra:
            total = sum(len(v) for v in self.pagos_por_obra.values())
            logger.info(f"[OK] Pagos indexados: {total} registros (obras con pagos: {len(self.pagos_por_obra)})")
        else:
            logger.info("[~] No hay pagos indexados (hoja pagos vacía o sin llave de obra)")

    @staticmethod
    def _normalize_column_name(name: Any) -> str:
        """Normaliza nombre de columna: lower, sin acentos, solo a-z0-9_."""
        text = str(name).strip().lower()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
        return text

    @staticmethod
    def _pick_first_existing(columns: List[str], candidates: List[str]) -> Optional[str]:
        for c in candidates:
            if c in columns:
                return c
        return None

    def _build_pagos_index(self, pagos_df: Optional[pd.DataFrame]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Indexa pagos por id_obra.
        Devuelve dict[id_obra] -> lista de pagos (ordenados desc por fecha si existe).
        """
        if pagos_df is None or getattr(pagos_df, "empty", True):
            return {}

        # Importar DataFormatters para formateo
        from src.processors.formatters import DataFormatters
        
        df = pagos_df.copy()
        df.columns = [self._normalize_column_name(c) for c in df.columns]

        # Buscar columna ID de obra
        key_col = self._pick_first_existing(
            list(df.columns),
            ["id_obra", "obra_id", "idobra", "id", "obra", "codigo_obra", "cod_obra"]
        )
        if not key_col:
            return {}

        # Buscar columnas con nombres específicos del Excel
        col_trata = self._pick_first_existing(
            list(df.columns),
            ["trata"]
        )
        col_nro_cert = self._pick_first_existing(
            list(df.columns),
            ["certificado_dga"]
        )
        col_expediente = self._pick_first_existing(
            list(df.columns),
            ["expediente", "expediente_gdeba", "exp"]
        )
        col_devengado = self._pick_first_existing(
            list(df.columns),
            ["importe_devengado", "devengado", "monto_devengado"]
        )
        col_fecha_pago = self._pick_first_existing(
            list(df.columns),
            ["fecha_pago", "fecha_de_pago", "fecha", "fecha_pago_real"]
        )

        # Parse de fecha para ordenar (si existe)
        fecha_dt = None
        if col_fecha_pago:
            fecha_dt = pd.to_datetime(df[col_fecha_pago], errors='coerce')

        # Función auxiliar para limpiar valores
        def _clean_value(val):
            """Convierte valores NaN, None, NaT a string vacío"""
            if pd.isna(val):
                return None
            if isinstance(val, (int, float)):
                return str(val)
            return str(val).strip() if val else None

        pagos_por_obra: Dict[str, List[Dict[str, Any]]] = {}
        for idx, r in df.iterrows():
            obra_id_raw = r.get(key_col)
            if pd.isna(obra_id_raw):
                continue
                
            obra_id = str(obra_id_raw).strip()
            if not obra_id or obra_id == "--":
                continue

            # Obtener valores sin formatear
            trata_raw = _clean_value(r.get(col_trata)) if col_trata else None
            nro_cert_raw = r.get(col_nro_cert) if col_nro_cert else None
            nro_cert_formatted = None
            if nro_cert_raw is not None and not pd.isna(nro_cert_raw):
                nro_cert_formatted = DataFormatters.formatear_numero(nro_cert_raw)
            expediente_raw = _clean_value(r.get(col_expediente)) if col_expediente else None
            
            # Para devengado: obtener valor y formatear
            devengado_raw = r.get(col_devengado) if col_devengado else None
            devengado_formatted = None
            if devengado_raw is not None and not pd.isna(devengado_raw):
                devengado_formatted = DataFormatters.formatear_moneda_sin_decimales(devengado_raw)
            
            # Para fecha_pago: obtener valor y formatear
            fecha_pago_raw = r.get(col_fecha_pago) if col_fecha_pago else None
            fecha_pago_formatted = None
            if fecha_pago_raw is not None and not pd.isna(fecha_pago_raw):
                fecha_pago_formatted = DataFormatters.formatear_fecha(fecha_pago_raw)

            # Calcular estado basado en fecha_pago e importe_devengado
            if fecha_dt is not None and not pd.isna(fecha_dt.loc[idx]):
                estado_calculado = "Pagado"
            elif devengado_raw is not None and not pd.isna(devengado_raw):
                estado_calculado = "Devengado sin pagar"
            else:
                estado_calculado = None

            pago: Dict[str, Any] = {
                "trata": trata_raw,
                "nro": nro_cert_formatted,
                "expediente": expediente_raw,
                "devengado": devengado_formatted,
                "fecha_pago": fecha_pago_formatted,
                "estado_calculado": estado_calculado,
                "_sort_fecha": fecha_dt.loc[idx] if fecha_dt is not None else pd.NaT,
                "_sort_idx": idx,
            }
            pagos_por_obra.setdefault(obra_id, []).append(pago)

        # Ordenar cada lista de pagos por fecha descendente (si aplica)
        for obra_id in pagos_por_obra:
            pagos_por_obra[obra_id].sort(key=lambda p: p["_sort_idx"])
        return pagos_por_obra

    @staticmethod
    def _to_display(value: Any) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "--"
        text = str(value).strip()
        return text if text else "--"
    
    def _setup_pdf_config(self) -> pdfkit.configuration:
        """
        Configura wkhtmltopdf.
        
        Returns:
            Configuración de wkhtmltopdf
        """
        try:
            config = pdfkit.configuration(wkhtmltopdf=Config.WKHTMLTOPDF_PATH)
            logger.info("[OK] Configuración wkhtmltopdf cargada")
            return config
        except Exception as e:
            logger.error(f"[!] Error configurando wkhtmltopdf: {e}")
            raise
    
    def generate_pdf(self, html_content: str, filename: str) -> bool:
        """
        Genera un PDF desde contenido HTML.
        
        Args:
            html_content: Contenido HTML a convertir
            filename: Nombre del archivo de salida
            
        Returns:
            True si se generó exitosamente, False en caso contrario
        """
        try:
            # Crear ruta completa del archivo
            output_path = self.output_dir / filename
            
            # Configurar opciones de PDF
            options = self._get_pdf_options()
            
            # Generar PDF
            pdfkit.from_string(html_content, str(output_path), 
                             configuration=self.pdf_config, options=options)
            
            logger.info(f"[+] PDF generado: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"[!] Error generando PDF {filename}: {e}")
            return False
    
    def generate_all(self, df, filter_prefix: str = "OTRAS") -> None:
        """
        Genera PDFs para todas las obras en el DataFrame.
        
        Args:
            df: DataFrame con datos de obras
            filter_prefix: Prefijo para filtrar obras ("OTRAS", "CONVE", "TODAS")
        """
        logger.info(f"[>] Iniciando generación masiva (filtro: {filter_prefix})")
        
        # Filtrar datos según prefijo
        filtered_df = self._filter_dataframe(df, filter_prefix)
        
        if filtered_df.empty:
            logger.warning(f"[!] No hay obras con prefijo '{filter_prefix}'")
            return
        
        logger.info(f"[>] Procesando {len(filtered_df)} obras...")
        
        success_count = 0
        error_count = 0
        
        for idx, row in filtered_df.iterrows():
            try:
                # Generar contexto para el template
                context = self._build_template_context(row)
                
                # Renderizar HTML
                html = template_manager.render_template('informe_template.html', context)
                
                # Generar nombre de archivo seguro
                filename = self._generate_safe_filename(row['id_obra'])
                
                # Generar PDF
                if self.generate_pdf(html, filename):
                    success_count += 1
                else:
                    error_count += 1
                    
            except Exception as e:
                logger.error(f"[!] Error en obra {idx}: {e}")
                error_count += 1
                
                # Guardar HTML para debugging
                try:
                    debug_filename = f"error_{idx}.html"
                    with open(debug_filename, 'w', encoding='utf-8') as f:
                        f.write(html)
                except:
                    pass
        
        logger.info(f"[OK] Proceso completado. Exitosos: {success_count}, Errores: {error_count}")
    
    def _filter_dataframe(self, df, filter_prefix: str) -> 'pd.DataFrame':
        """
        Filtra el DataFrame según el prefijo especificado.
        
        Args:
            df: DataFrame a filtrar
            filter_prefix: Prefijo para filtrar
            
        Returns:
            DataFrame filtrado
        """
        if filter_prefix == "TODAS":
            return df
        elif filter_prefix == "OTRAS":
            return df[df['id_obra'].str.startswith('OTRAS-', na=False)]
        elif filter_prefix == "CONVE":
            return df[df['id_obra'].str.startswith('CONVE-', na=False)]
        else:
            return df
    
    def _build_template_context(self, row) -> Dict[str, Any]:
        """
        Construye el contexto para el template desde una fila del DataFrame.
        
        Args:
            row: Fila del DataFrame
            
        Returns:
            Diccionario con contexto para el template
        """
        from src.processors.formatters import DataFormatters
        from src.processors.calculations import CalculosFinancieros
        
        # Procesar imágenes de la obra
        from src.processors.resources import ResourceProcessor

        obra_images = ResourceProcessor.get_work_images(
            obra_id=row.get('id_obra', '')
        )

        # Obtener UVIs restantes del merge
        #uvis_restantes = DataFormatters.formatear_moneda(row.get('UVI Restante', '--'))
        #if pd.isna(uvis_restantes):
        #    uvis_restantes = '--'
            
        # =========================
        # NOTICIAS DESDE GOOGLE SHEETS
        # =========================
        try:
            noticias = SheetsReader.obtener_noticias_por_obra(
                sheet_id=Config.GOOGLE_SHEET_ID_NOTICIAS,
                hoja_noticias=Config.GOOGLE_SHEET_NAME_NOTICIAS, 
                id_obra=row.get('id_obra')
            )
        except Exception as e:
            logger.warning(f"[!] Error trayendo noticias para {row.get('id_obra')}: {e}")
            noticias = []

        context = {
            # Recursos visuales
            'banner_path': self.resources.get('banner', ''),
            'footer_path': self.resources.get('footer', ''),
            'doble_flecha': self.resources.get('doble_flecha', ''),
            'fuente_regular': self.resources.get('fuente_regular', ''),
            'fuente_bold': self.resources.get('fuente_bold', ''),
            
            # Datos básicos
            'Memoria_Descriptiva': row.get('descripcion', '--'),
            'Imagen_Obra': obra_images.get('principal', ''),
            'Imagenes_Extra': obra_images.get('adicionales', []),
            'ID_obra': row.get('id_obra', '--'),
            'ID_historico': row.get('id_historico', '--'),
            'Descripcion_Corta': DataFormatters.extraer_descripcion_corta(row.get('descripcion', '--')),       
            
            # Datos formateados
            'Viviendas_Totales': DataFormatters.formatear_numero(row.get('viv_totales', '--')),
            'Viviendas_Entregadas': DataFormatters.formatear_numero(row.get('viv_entregadas', '--')),
            'Viviendas_Restantes': CalculosFinancieros.calculo_viviendas_restantes(
                row.get('viv_totales', '--'), 
                row.get('viv_entregadas', '--')
            ),
            'Estado': row.get('estado', '--'),
            'Solicitante_Financiamiento': row.get('solicitante_financiero', '--'),
            'Solicitante_Presupuestario': row.get('solicitante_presupuestario', '--'),
            'Municipio': row.get('municipio', '--'),
            'Localidad': row.get('localidad', '--'),
            'Modalidad': row.get('modalidad', '--'),
            'Programa': 'Programa COMPLETAR',
            'noticias': noticias,
            
            # Códigos
            'Cod_emprendimiento': DataFormatters.formatear_integer(row.get('emprendimiento_incluidos', '--')),
            'Cod_obra': DataFormatters.formatear_integer(row.get('codigos_incluidos', '--')),
            
            # Información financiera
            'Monto_Convenio': DataFormatters.formatear_moneda(row.get('monto_convenio', '--')),
            'Fecha_UVI': DataFormatters.formatear_fecha(row.get('fecha_cotizacion_uvi_convenio')),
            'Total_UVI': DataFormatters.formatear_numero(row.get('cantidad_uvis', '--')),
            #'Uvis_Restantes': CalculosFinancieros.calcular_uvi_restantes(
            #    row.get('cantidad_uvis', '--'),
            #    row.get('porcentaje_avance_fisico', '--'),
            #    uvis_restantes
            #),
            'Exp_GDEBA': '' if pd.isna(row.get('expediente_gdeba')) else str(row.get('expediente_gdeba')),
            
            # Avances
            'Avance_fisico': DataFormatters.formatear_porcentaje(row.get('porcentaje_avance_fisico', '--')),
            'Avance_Restante': CalculosFinancieros.calculate_progreso_restante(row.get('porcentaje_avance_fisico', '--')
            ),
            'Avance_financiero': DataFormatters.formatear_porcentaje(row.get('avance_financiero', '--')),
            
            # Montos
            """ 'Saldo_UVI_Pendiente': saldo_uvi_pendiente,
            'Saldo_Obra_Actualizado': saldo_actualizado_formateado, """
            
            'Monto_Restante_Actualizado': CalculosFinancieros.calcular_monto_restante(
                row.get('monto_actualizado', '--'),
                row.get('monto_pagado', '--')
            ),
            'Monto_Devengado': DataFormatters.formatear_moneda(row.get('monto_devengado', '--')),
            'Monto_Pagado': DataFormatters.formatear_moneda(row.get('monto_pagado', '--')),
            'Fecha_ultimo_pago': DataFormatters.formatear_fecha(row.get('fecha_ultimo_pago'))
        }

        # =========================
        # PAGOS (pestaña 2 del Excel)
        # =========================
        obra_id = str(row.get('id_obra', '')).strip()
        pagos = self.pagos_por_obra.get(obra_id, [])

        # Campos usados SOLO en la tabla de pagos del template
        context.update({
            'pagos_lista': pagos,
            'Nro': self._to_display(pagos[0].get('certificado_dga')) if pagos[0] else "--",
            'Expediente': self._to_display(pagos[0].get('expediente')) if pagos[0] else "--",
            'Nro_Operatoria': self._to_display(pagos[0].get('OP')) if pagos[0] else "--",
            'Contratista': self._to_display(pagos[0].get('ente')) if pagos[0] else "--",
            'Estado_Pago': self._to_display(pagos[0].get('estado_pago')) if pagos[0] else "--",
            'Devengado': DataFormatters.formatear_moneda(pagos[0].get('importe_devengado')) if pagos[0] else "--",
            'Fecha_Pago': DataFormatters.formatear_fecha(pagos[0].get('fecha_pago')) if pagos[0] else "--",
        })
        
        return context
    
    def _get_pdf_options(self) -> Dict[str, Any]:
        """
        Obtiene las opciones de configuración para wkhtmltopdf.
        
        Returns:
            Diccionario con opciones de PDF
        """
        return {
            'enable-local-file-access': None,
            'margin-top': '30mm',
            'margin-bottom': '20mm',
            'margin-left': '4mm',
            'margin-right': '4mm',
            'footer-html': FilePaths.FOOTER_RENDERED_HTML.resolve().as_uri(),
            'header-html': FilePaths.HEADER_RENDERED_HTML.resolve().as_uri(),
            'encoding': Config.ENCODING,
        }
    
    def _generate_safe_filename(self, obra_id: str) -> str:
        """
        Genera un nombre de archivo seguro desde el ID de obra.
        
        Args:
            obra_id: ID de la obra
            
        Returns:
            Nombre de archivo seguro
        """
        # Crear nombre base
        nombre_base = f"informe_{obra_id}"
        
        # Remover caracteres peligrosos
        nombre_seguro = re.sub(r'[\\/*?:"<>|]', '', nombre_base)
        
        # Asegurar extensión
        if not nombre_seguro.endswith('.pdf'):
            nombre_seguro += '.pdf'
        
        return nombre_seguro
