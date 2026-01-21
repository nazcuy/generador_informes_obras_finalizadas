"""
Lector especializado para archivos Excel.
"""

from __future__ import annotations

import pandas as pd
from typing import Optional, List, Union
from pathlib import Path

from config.constants import Config
from utils.helpers import setup_logging

logger = setup_logging(__name__)

class ExcelReader:
    """Lector especializado para archivos Excel"""

    @staticmethod
    def _resolve_sheet_name(file_path: str, preferred_names: List[str], fallback_index: int) -> Union[str, int]:
        """
        Resuelve el nombre de hoja a leer.

        - Intenta encontrar una hoja por nombre (case-insensitive) dentro de preferred_names
        - Si no la encuentra, usa el índice fallback_index si existe
        - Si tampoco existe, usa la primera hoja
        """
        xls = pd.ExcelFile(file_path, engine='openpyxl')
        name_map = {str(n).strip().lower(): n for n in xls.sheet_names}

        for pref in preferred_names:
            key = str(pref).strip().lower()
            if key in name_map:
                return name_map[key]

        if 0 <= fallback_index < len(xls.sheet_names):
            return xls.sheet_names[fallback_index]

        return xls.sheet_names[0]

    @staticmethod
    def read_obras(path: Optional[str] = None) -> pd.DataFrame:
        """
        Lee la pestaña 1 del Excel (obras).
        Preferencia: hoja llamada 'obras' (case-insensitive). Fallback: primera hoja.
        """
        file_path = path or Config.EXCEL_PATH
        sheet = ExcelReader._resolve_sheet_name(file_path, preferred_names=["obras"], fallback_index=0)
        logger.info(f"[>] Leyendo Excel (obras): {file_path} | hoja: {sheet}")
        return pd.read_excel(file_path, sheet_name=sheet, engine='openpyxl')

    @staticmethod
    def read_pagos(path: Optional[str] = None) -> pd.DataFrame:
        """
        Lee la pestaña 2 del Excel (pagos).
        Preferencia: hoja llamada 'pagos' (case-insensitive). Fallback: segunda hoja.
        """
        file_path = path or Config.EXCEL_PATH
        sheet = ExcelReader._resolve_sheet_name(file_path, preferred_names=["pagos"], fallback_index=1)
        logger.info(f"[>] Leyendo Excel (pagos): {file_path} | hoja: {sheet}")
        return pd.read_excel(file_path, sheet_name=sheet, engine='openpyxl')
    
    @staticmethod
    def read_excel(path: Optional[str] = None) -> pd.DataFrame:
        """
        Lee archivo Excel con validación y manejo de errores.
        
        Args:
            path: Ruta al archivo Excel (opcional, usa Config.EXCEL_PATH por defecto)
            
        Returns:
            DataFrame con los datos del Excel
            
        Raises:
            FileNotFoundError: Si el archivo no existe
            ValueError: Si hay problemas de lectura
        """
        file_path = path or Config.EXCEL_PATH
        
        try:
            # Compatibilidad: por defecto leemos la pestaña de obras
            df = ExcelReader.read_obras(file_path)
            logger.info(f"[OK] Excel cargado: {len(df)} registros")
            return df
            
        except FileNotFoundError:
            raise FileNotFoundError(f"No se encontró el archivo Excel: {file_path}")
        except Exception as e:
            raise ValueError(f"Error leyendo Excel {file_path}: {e}")
    
    @staticmethod
    def validate_dataframe(df: pd.DataFrame, required_columns: List[str]) -> bool:
        """
        Valida que el DataFrame tenga las columnas requeridas.
        
        Args:
            df: DataFrame a validar
            required_columns: Lista de columnas requeridas
            
        Returns:
            True si es válido, False en caso contrario
        """
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            logger.warning(f"[!] Columnas faltantes en Excel: {missing_columns}")
            return False
        
        logger.info(f"[OK] Validación de columnas exitosa")
        return True
    
    @staticmethod
    def filter_by_prefix(df: pd.DataFrame, column: str, prefix: str) -> pd.DataFrame:
        """
        Filtra DataFrame por prefijo en una columna específica.
        
        Args:
            df: DataFrame a filtrar
            column: Nombre de la columna para filtrar
            prefix: Prefijo a buscar
            
        Returns:
            DataFrame filtrado
        """
        return df[df[column].str.startswith(prefix, na=False)]
    
    @staticmethod
    def exclude_by_prefix(df: pd.DataFrame, column: str, prefix: str) -> pd.DataFrame:
        """
        Excluye filas por prefijo en una columna específica.
        
        Args:
            df: DataFrame a filtrar
            column: Nombre de la columna para filtrar
            prefix: Prefijo a excluir
            
        Returns:
            DataFrame filtrado
        """
        return df[~df[column].str.startswith(prefix, na=False)]
