#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for two-stage jump suspect confirmation system

Tests the suspect buffering, confirmation, and rejection logic
for teleport jump detection in OCR coordinate tracking.
"""

import sys
from pathlib import Path

# Add src directory to path
src_path = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(src_path))

import pytest
from typing import Tuple, Optional
from ocr_engine import OCRWorker, RecognitionState


class MockOCRWorker(OCRWorker):
    """Mock OCR worker for testing without full initialization"""
    
    def __init__(self):
        # Minimal initialization without QThread or model
        self.logger = self._setup_minimal_logger()
        
        # Core tracking state
        self.recognition_state = RecognitionState.LOCKED
        self.last_valid_coord = (1000, 2000, 100)
        self.last_valid_detections = None
        self.consecutive_failures = 0
        self.last_emitted_coord = None
        
        # Two-stage jump suspect system
        self.suspect_jump = None
        self.suspect_confirmation_window = 2
        
        # Thresholds
        self.max_speed_threshold = 1000
        self.z_axis_threshold = 50
    
    def _setup_minimal_logger(self):
        """Setup minimal logger for testing"""
        import logging
        logger = logging.getLogger('test_ocr')
        logger.setLevel(logging.DEBUG)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
            logger.addHandler(handler)
        return logger


class TestJumpSuspectConfirmation:
    """Test two-stage jump suspect confirmation system"""
    
    def test_confirmed_jump_2_frames(self):
        """Test jump confirmation after 2 consistent frames"""
        worker = MockOCRWorker()
        
        # Start with stable position
        stable_coord = (1000, 2000, 100)
        worker.last_valid_coord = stable_coord
        
        # Frame 1: Jump detected (large distance)
        jump_coord = (3500, 4500, 120)
        result = worker._process_suspect_jump(jump_coord)
        
        # Should enter suspect mode, return None
        assert result is None, "Frame 1 should not emit coordinate"
        assert worker.suspect_jump is not None, "Should enter suspect mode"
        assert worker.suspect_jump['count'] == 1
        assert worker.suspect_jump['coord'] == jump_coord
        assert worker.suspect_jump['stable_coord'] == stable_coord
        
        # Frame 2: Consistent with jump (within tolerance)
        jump_coord_frame2 = (3510, 4490, 118)  # Near jump_coord
        result = worker._process_suspect_jump(jump_coord_frame2)
        
        # Should confirm and return jump coordinate
        assert result is not None, "Frame 2 should confirm and emit coordinate"
        assert result == jump_coord, "Should emit original suspect coordinate"
        assert worker.suspect_jump is None, "Should exit suspect mode after confirmation"
    
    def test_rejected_jump_revert_to_stable(self):
        """Test jump rejection when frames revert to stable position"""
        worker = MockOCRWorker()
        
        # Start with stable position
        stable_coord = (1000, 2000, 100)
        worker.last_valid_coord = stable_coord
        
        # Frame 1: Jump detected
        jump_coord = (3500, 4500, 120)
        result = worker._process_suspect_jump(jump_coord)
        
        assert result is None
        assert worker.suspect_jump is not None
        
        # Frame 2: Revert to stable (not near jump_coord)
        revert_coord = (1010, 2005, 102)  # Near stable_coord
        result = worker._process_suspect_jump(revert_coord)
        
        # Should reject and return stable coordinate
        assert result is not None, "Should reject and emit coordinate"
        assert result == stable_coord, "Should emit stable coordinate, not jump"
        assert worker.suspect_jump is None, "Should exit suspect mode after rejection"
    
    def test_suspect_timeout_on_no_data(self):
        """Test suspect rejection when no valid data for 2 frames"""
        worker = MockOCRWorker()
        
        # Start with stable position
        stable_coord = (1000, 2000, 100)
        worker.last_valid_coord = stable_coord
        
        # Frame 1: Jump detected
        jump_coord = (3500, 4500, 120)
        result = worker._process_suspect_jump(jump_coord)
        
        assert result is None
        assert worker.suspect_jump is not None
        
        # Frame 2: No valid data (timeout scenario)
        timeout_result = worker._reset_suspect_on_failure()
        
        # Should reject and return stable coordinate
        assert timeout_result is not None, "Timeout should emit stable coordinate"
        assert timeout_result == stable_coord, "Should return stable coordinate on timeout"
        assert worker.suspect_jump is None, "Should exit suspect mode after timeout"
    
    def test_normal_movement_no_suspect(self):
        """Test normal movement without entering suspect mode"""
        worker = MockOCRWorker()
        
        # Start with stable position
        stable_coord = (1000, 2000, 100)
        worker.last_valid_coord = stable_coord
        
        # Normal movement (small distance)
        normal_coord = (1050, 2030, 102)
        
        # Check if jump is detected
        is_jump = worker._is_teleport_jump(normal_coord)
        
        assert not is_jump, "Normal movement should not be detected as jump"
        assert worker.suspect_jump is None, "Should not enter suspect mode for normal movement"
    
    def test_suspect_confirmation_window_is_2_frames(self):
        """Test that confirmation window is exactly 2 frames"""
        worker = MockOCRWorker()
        
        assert worker.suspect_confirmation_window == 2, "Confirmation window must be exactly 2 frames"
        
        stable_coord = (1000, 2000, 100)
        worker.last_valid_coord = stable_coord
        
        jump_coord = (3500, 4500, 120)
        
        # Frame 1
        result = worker._process_suspect_jump(jump_coord)
        assert result is None
        assert worker.suspect_jump['count'] == 1
        
        # Frame 2 (should confirm on this frame)
        jump_coord_frame2 = (3505, 4498, 119)
        result = worker._process_suspect_jump(jump_coord_frame2)
        
        assert result is not None, "Should confirm exactly on frame 2"
        assert result == jump_coord
    
    def test_is_near_tolerance(self):
        """Test _is_near helper with default tolerance"""
        worker = MockOCRWorker()
        
        coord1 = (1000, 2000, 100)
        coord2_near = (1050, 2030, 105)  # Distance ~68
        coord2_far = (1200, 2200, 150)   # Distance ~291
        
        assert worker._is_near(coord1, coord2_near), "Coordinates within 100 should be near"
        assert not worker._is_near(coord1, coord2_far), "Coordinates beyond 100 should not be near"
    
    def test_z_axis_jump_triggers_suspect(self):
        """Test that Z-axis jumps also trigger suspect mode"""
        worker = MockOCRWorker()
        
        stable_coord = (1000, 2000, 100)
        worker.last_valid_coord = stable_coord
        
        # Jump only in Z axis (exceeds z_axis_threshold=50)
        z_jump_coord = (1010, 2005, 200)
        
        is_jump = worker._is_teleport_jump(z_jump_coord)
        assert is_jump, "Z-axis jump should be detected"
        
        # Should enter suspect mode
        result = worker._process_suspect_jump(z_jump_coord)
        assert result is None
        assert worker.suspect_jump is not None
    
    def test_multiple_rejections_in_sequence(self):
        """Test multiple suspect-reject cycles in sequence"""
        worker = MockOCRWorker()
        
        stable_coord = (1000, 2000, 100)
        worker.last_valid_coord = stable_coord
        
        # First suspect-reject cycle
        jump1 = (3500, 4500, 120)
        worker._process_suspect_jump(jump1)
        revert1 = (1005, 2002, 101)
        result1 = worker._process_suspect_jump(revert1)
        
        assert result1 == stable_coord
        assert worker.suspect_jump is None
        
        # Second suspect-reject cycle
        jump2 = (4000, 5000, 130)
        worker._process_suspect_jump(jump2)
        revert2 = (1008, 2003, 99)
        result2 = worker._process_suspect_jump(revert2)
        
        assert result2 == stable_coord
        assert worker.suspect_jump is None


if __name__ == "__main__":
    # Run with verbose output
    pytest.main([__file__, '-v', '-s'])
