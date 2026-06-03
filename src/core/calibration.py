# -*- coding: utf-8 -*-
"""
Calibration system - coordinate transformation between game and map
"""

import os
import json
from datetime import datetime
from typing import Optional, Dict, List, Any

import numpy as np


class CalibrationPoint:
    """Calibration point data structure"""
    
    def __init__(self, x: float, y: float, lat: float, lon: float):
        """
        Initialize a calibration point
        
        Args:
            x: Game X coordinate
            y: Game Y coordinate
            lat: Map latitude
            lon: Map longitude
        """
        self.x = x
        self.y = y
        self.lat = lat
        self.lon = lon


class TransformMatrix:
    """
    Affine transformation matrix for coordinate conversion
    
    lat = a*x + b*y + c
    lon = d*x + e*y + f
    """
    
    def __init__(self, a: float = 0, b: float = 0, c: float = 0,
                 d: float = 0, e: float = 0, f: float = 0):
        self.a = a  # lat = a*x + b*y + c
        self.b = b
        self.c = c
        self.d = d  # lon = d*x + e*y + f
        self.e = e
        self.f = f
    
    def transform(self, x: float, y: float) -> tuple:
        """
        Transform game coordinates to map coordinates
        
        Args:
            x: Game X coordinate
            y: Game Y coordinate
            
        Returns:
            Tuple of (lat, lon)
        """
        lat = self.a * x + self.b * y + self.c
        lon = self.d * x + self.e * y + self.f
        return lat, lon
    
    def to_dict(self) -> Dict[str, float]:
        """Convert matrix to dictionary for serialization"""
        return {
            "a": self.a, "b": self.b, "c": self.c,
            "d": self.d, "e": self.e, "f": self.f
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> 'TransformMatrix':
        """Create matrix from dictionary"""
        return cls(
            data.get("a", 0), data.get("b", 0), data.get("c", 0),
            data.get("d", 0), data.get("e", 0), data.get("f", 0)
        )


class CalibrationSystem:
    """Map calibration system core logic"""
    
    @staticmethod
    def calculate_transform_matrix(points: List[CalibrationPoint]) -> TransformMatrix:
        """
        Calculate affine transformation matrix from calibration points
        
        Args:
            points: List of calibration points (minimum 2 required)
            
        Returns:
            TransformMatrix for coordinate conversion
            
        Raises:
            ValueError: If insufficient points or calculation fails
        """
        if len(points) < 2:
            raise ValueError("At least 2 calibration points required")
        
        # Build linear system Ax = b
        n = len(points)
        A = np.zeros((2 * n, 6))
        b = np.zeros(2 * n)
        
        for i, point in enumerate(points):
            # lat = a*x + b*y + c
            A[2 * i] = [point.x, point.y, 1, 0, 0, 0]
            b[2 * i] = point.lat
            
            # lon = d*x + e*y + f
            A[2 * i + 1] = [0, 0, 0, point.x, point.y, 1]
            b[2 * i + 1] = point.lon
        
        # Solve using least squares
        try:
            x = np.linalg.lstsq(A, b, rcond=None)[0]
            return TransformMatrix(x[0], x[1], x[2], x[3], x[4], x[5])
        except np.linalg.LinAlgError:
            raise ValueError("Cannot calculate transform matrix, please check calibration points")
    
    @staticmethod
    def transform(x: float, y: float, matrix: Optional[TransformMatrix]) -> tuple:
        """
        Transform game coordinates to map coordinates using given matrix
        
        Args:
            x: Game X coordinate
            y: Game Y coordinate
            matrix: Transformation matrix
            
        Returns:
            Tuple of (lat, lon)
            
        Raises:
            ValueError: If matrix is None
        """
        if matrix is None:
            raise ValueError("Transform matrix not initialized")
        
        return matrix.transform(x, y)


class CalibrationDataManager:
    """Manages calibration data persistence"""
    
    def __init__(self, calibration_file: Optional[str] = None):
        """
        Initialize calibration data manager
        
        Args:
            calibration_file: Path to calibration data file.
                            Defaults to calibration_data.json in script directory.
        """
        if calibration_file is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            # Go up to src directory
            src_dir = os.path.dirname(script_dir)
            self.calibration_file = os.path.join(src_dir, "calibration_data.json")
        else:
            self.calibration_file = calibration_file
    
    def get_map_key(self, mode: str, provider_or_map_name: str, 
                    area_id: Optional[str] = None) -> str:
        """
        Generate unique key for a map
        
        Args:
            mode: 'online' or 'local'
            provider_or_map_name: Provider key or local map name
            area_id: Optional area ID for online maps
            
        Returns:
            Unique map key string
        """
        if mode == 'online':
            return f"online_{provider_or_map_name}_{area_id or 'default'}"
        else:
            return f"local_{provider_or_map_name}"
    
    def save_calibration(self, mode: str, provider_or_map_name: str,
                        transform_matrix: TransformMatrix,
                        area_id: Optional[str] = None) -> bool:
        """
        Save calibration data to file
        
        Args:
            mode: 'online' or 'local'
            provider_or_map_name: Provider key or local map name
            transform_matrix: The transformation matrix to save
            area_id: Optional area ID for online maps
            
        Returns:
            True if save successful, False otherwise
        """
        try:
            print(f"[DEBUG] Saving calibration: mode={mode}, provider={provider_or_map_name}, area_id={area_id}")
            
            # Load existing data
            data = self.load_all_calibrations()
            
            # Generate map key
            map_key = self.get_map_key(mode, provider_or_map_name, area_id)
            
            # Save calibration data
            calibration_data = {
                "mode": mode,
                "provider_or_map_name": provider_or_map_name,
                "area_id": area_id,
                "matrix": transform_matrix.to_dict(),
                "timestamp": datetime.now().isoformat()
            }
            
            data[map_key] = calibration_data
            
            # Write to file
            with open(self.calibration_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            print(f"Calibration data saved: {map_key}")
            return True
            
        except Exception as e:
            print(f"Failed to save calibration data: {e}")
            return False
    
    def load_calibration(self, mode: str, provider_or_map_name: str,
                        area_id: Optional[str] = None) -> Optional[TransformMatrix]:
        """
        Load calibration data for a specific map
        
        Args:
            mode: 'online' or 'local'
            provider_or_map_name: Provider key or local map name
            area_id: Optional area ID for online maps
            
        Returns:
            TransformMatrix if found, None otherwise
        """
        try:
            data = self.load_all_calibrations()
            map_key = self.get_map_key(mode, provider_or_map_name, area_id)
            
            if map_key in data:
                calibration_data = data[map_key]
                matrix_data = calibration_data["matrix"]
                transform_matrix = TransformMatrix.from_dict(matrix_data)
                print(f"Loaded calibration data: {map_key}")
                return transform_matrix
            
            return None
            
        except Exception as e:
            print(f"Failed to load calibration data: {e}")
            return None
    
    def load_all_calibrations(self) -> Dict[str, Any]:
        """
        Load all calibration data from file
        
        Returns:
            Dictionary of all calibration data
        """
        try:
            if os.path.exists(self.calibration_file):
                with open(self.calibration_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception:
            return {}
    
    def has_calibration(self, mode: str, provider_or_map_name: str,
                       area_id: Optional[str] = None) -> bool:
        """
        Check if calibration data exists for a map
        
        Args:
            mode: 'online' or 'local'
            provider_or_map_name: Provider key or local map name
            area_id: Optional area ID for online maps
            
        Returns:
            True if calibration exists, False otherwise
        """
        data = self.load_all_calibrations()
        map_key = self.get_map_key(mode, provider_or_map_name, area_id)
        return map_key in data
    
    def delete_calibration(self, mode: str, provider_or_map_name: str,
                          area_id: Optional[str] = None) -> bool:
        """
        Delete calibration data for a map
        
        Args:
            mode: 'online' or 'local'
            provider_or_map_name: Provider key or local map name
            area_id: Optional area ID for online maps
            
        Returns:
            True if deletion successful, False otherwise
        """
        try:
            data = self.load_all_calibrations()
            map_key = self.get_map_key(mode, provider_or_map_name, area_id)
            
            if map_key in data:
                del data[map_key]
                with open(self.calibration_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                print(f"Deleted calibration data: {map_key}")
                return True
            return False
            
        except Exception as e:
            print(f"Failed to delete calibration data: {e}")
            return False
