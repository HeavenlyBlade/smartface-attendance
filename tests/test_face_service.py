"""
tests/test_face_service.py -- Property-based tests for face service

Properties covered:
  Property 1: Facial encoding serialization round-trip (Task 2.2)
  Property 2: Cache-database alignment after reload (Task 2.3)
  Property 6: Confidence formula correctness (Task 3.4)
  Property 7: Unknown face classification above tolerance (Task 3.5)
  Property 11: N faces in frame -> N entries in response (Task 3.6)
"""

import sys
import base64
from pathlib import Path
from unittest.mock import patch

import numpy as np
import cv2
import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import lists, floats, integers
from hypothesis.extra.numpy import arrays as np_arrays

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.face_service import (
    serialize_encoding,
    deserialize_encoding,
    compute_confidence,
    classify_face_match,
)
import config


# ===========================================================================
# Property 1: Facial Encoding Serialization Round-Trip
# Task 2.2 | Validates: Requirements 3.7, 4.2
# ===========================================================================

@given(np_arrays(dtype=np.float64, shape=128, elements=floats(
    min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
)))
@settings(max_examples=100, deadline=None)
def test_property_1_encoding_round_trip(enc):
    """
    Feature: smartface-attendance-system, Property 1: Encoding round-trip

    For any 128-dim float64 numpy array of finite values (matching the valid
    domain of dlib facial encodings), serializing with .tobytes() and
    deserializing with np.frombuffer must produce an array element-wise equal
    to the original.

    Validates: Requirements 3.7, 4.2
    """
    blob      = serialize_encoding(enc)
    recovered = deserialize_encoding(blob)

    assert recovered.shape == (128,), f"Shape mismatch: {recovered.shape}"
    assert recovered.dtype == np.float64, f"Dtype mismatch: {recovered.dtype}"
    assert np.array_equal(enc, recovered, equal_nan=True), "Round-trip encoding not equal to original"


# ===========================================================================
# Property 2: Cache-Database Alignment After Reload
# Task 2.3 | Validates: Requirements 4.2, 4.4
# ===========================================================================

@given(lists(
    np_arrays(dtype=np.float64, shape=128, elements=floats(
        min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
    )),
    min_size=0, max_size=50
))
@settings(max_examples=50, deadline=None)
def test_property_2_encoding_list_alignment(encoding_list):
    """
    Feature: smartface-attendance-system, Property 2: Cache-DB alignment after reload

    For any list of finite-valued encodings (matching the valid domain of dlib
    facial encodings), after serializing and deserializing each one the resulting
    list must have the same length and each entry must be element-wise equal to
    the original.

    Validates: Requirements 4.2, 4.4
    """
    serialized   = [serialize_encoding(enc) for enc in encoding_list]
    deserialized = [deserialize_encoding(blob) for blob in serialized]

    assert len(deserialized) == len(encoding_list), (
        f"Length mismatch: {len(deserialized)} != {len(encoding_list)}"
    )

    for i, (original, recovered) in enumerate(zip(encoding_list, deserialized)):
        assert np.array_equal(original, recovered, equal_nan=True), f"Encoding at index {i} differs after round-trip"


# ===========================================================================
# Property 6: Confidence Formula Correctness
# Task 3.4 | Validates: Requirements 5.6
# ===========================================================================

@given(floats(min_value=0.0, max_value=0.45, allow_nan=False, allow_infinity=False))
@settings(max_examples=100, deadline=None)
def test_property_6_confidence_formula(distance):
    """
    Feature: smartface-attendance-system, Property 6: Confidence formula correctness

    For any face distance in [0.0, 0.45], the computed confidence must equal
    round((1 - distance) * 100, 2) and lie within [55.0, 100.0].
    """
    result   = compute_confidence(distance)
    expected = round((1 - distance) * 100, 2)

    assert result == expected, f"compute_confidence({distance}) = {result}, expected {expected}"
    assert 55.0 <= result <= 100.0, f"Confidence {result} out of range [55.0, 100.0] for distance {distance}"


# ===========================================================================
# Property 7: Unknown Face Classification Above Tolerance
# Task 3.5 | Validates: Requirements 5.7, 6.1
# ===========================================================================

@given(floats(min_value=0.451, max_value=2.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=100, deadline=None)
def test_property_7_unknown_face_above_tolerance(distance):
    """
    Feature: smartface-attendance-system, Property 7: Unknown face classification above tolerance

    For any face whose best distance exceeds TOLERANCE (0.45), the recognition
    result must have user_id=None and full_name="Unknown".
    """
    result = classify_face_match(distance)

    assert result["user_id"] is None, (
        f"Expected user_id=None for distance {distance}, got {result['user_id']}"
    )
    assert result["full_name"] == "Unknown", (
        f"Expected full_name='Unknown' for distance {distance}, got {result['full_name']}"
    )


# ===========================================================================
# Property 11: N Faces in Frame -> N Entries in Response
# Task 3.6 | Validates: Requirements 5.10
# ===========================================================================

@given(integers(min_value=0, max_value=5))
@settings(max_examples=20, deadline=None)
def test_property_11_multi_face_count_mock(n_faces):
    """
    Feature: smartface-attendance-system, Property 11: N faces in frame -> N entries in response

    Validates that recognize_frame returns exactly N entries for N detected faces
    by mocking the face_recognition library responses.
    """
    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    _, jpeg_buf = cv2.imencode(".jpg", dummy_frame)
    frame_b64   = base64.b64encode(jpeg_buf.tobytes()).decode("utf-8")

    fake_locs = [(10 * i, 10 * i + 50, 10 * i + 50, 10 * i) for i in range(n_faces)]
    fake_encs = [np.zeros(128, dtype=np.float64) for _ in range(n_faces)]

    with patch("face_recognition.face_locations", return_value=fake_locs), \
         patch("face_recognition.face_encodings", return_value=fake_encs):
        import services.face_service as fs
        result = fs.recognize_frame(frame_b64)

    assert len(result) == n_faces, (
        f"Expected {n_faces} faces in response, got {len(result)}"
    )
